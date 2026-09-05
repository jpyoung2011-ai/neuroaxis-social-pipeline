"""Pure scheduling logic: turn a bag of content items into dated post slots.

No I/O, no network — just calendar maths, so it is exhaustively unit-tested.
``build_schedule`` spreads items across a multi-week horizon, honours a weekly
funnel-stage mix as a target ratio, skips weekends by default, never schedules
in the past, and keeps BOFU ("advertisement") posts at least two days apart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Any

_STAGE_ORDER = {"TOFU": 0, "MOFU": 1, "BOFU": 2}


@dataclass
class ScheduledItem:
    item: Any          # a ContentItem (or any object with .funnel_stage / .title)
    when: datetime     # timezone-aware


def order_by_mix(mix: dict[str, int]) -> list[str]:
    """One week's target stage pattern, spreading each stage evenly.

    ``{"TOFU": 3, "MOFU": 1, "BOFU": 1}`` -> ``["TOFU","TOFU","MOFU","BOFU","TOFU"]``.
    """
    total = sum(mix.values())
    if total == 0:
        return []
    placed: list[tuple[float, int, str]] = []
    for stage, count in mix.items():
        if count <= 0:
            continue
        for k in range(count):
            pos = (k + 0.5) * total / count
            placed.append((pos, _STAGE_ORDER.get(stage, 9), stage))
    placed.sort()
    return [stage for _, _, stage in placed]


def _week_slots(start: date, eligible_weekdays: list[int],
                per_week: int, slots: list[str]) -> list[tuple[date, str]]:
    """The (date, "HH:MM") pairs for a single week beginning at ``start``."""
    days = [start + timedelta(days=i) for i in range(7)
            if (start + timedelta(days=i)).weekday() in eligible_weekdays]
    per_day_cap = max(1, math.ceil(per_week / max(1, len(days))))
    usable_slots = slots[:per_day_cap] if per_day_cap <= len(slots) else slots
    # slot-major fill so posts spread across days before doubling up on a day
    pairs: list[tuple[date, str]] = []
    for slot in usable_slots:
        for day in days:
            pairs.append((day, slot))
    pairs = pairs[:per_week]
    pairs.sort(key=lambda p: (p[0], p[1]))
    return pairs


def _assign_items(target_stages: list[str], items: list[Any]) -> list[Any]:
    """Fill the target stage sequence from per-stage buckets, falling back to
    whichever bucket has the most left when the requested stage is exhausted."""
    buckets: dict[str, list[Any]] = {}
    for it in items:
        buckets.setdefault(it.funnel_stage, []).append(it)

    out: list[Any] = []
    for stage in target_stages:
        if buckets.get(stage):
            out.append(buckets[stage].pop(0))
            continue
        fallback = max(
            (s for s in buckets if buckets[s]),
            key=lambda s: len(buckets[s]),
            default=None,
        )
        if fallback is None:
            break
        out.append(buckets[fallback].pop(0))
    return out


def _bofu_violations(scheduled: list[ScheduledItem]) -> int:
    """Number of BOFU posts scheduled within a day of the previous BOFU post."""
    days = sorted(s.when.date() for s in scheduled
                  if getattr(s.item, "funnel_stage", None) == "BOFU")
    return sum(1 for a, b in zip(days, days[1:]) if (b - a).days < 2)


def _repair_bofu_spacing(scheduled: list[ScheduledItem]) -> None:
    """Swap items between slots to remove consecutive-day BOFU posts.

    Greedy: keep any pairwise item swap that reduces the violation count.
    Slot datetimes never move, so the list stays time-ordered.
    """
    for _ in range(6):
        current = _bofu_violations(scheduled)
        if current == 0:
            return
        improved = False
        for a in range(len(scheduled)):
            for b in range(a + 1, len(scheduled)):
                scheduled[a].item, scheduled[b].item = (
                    scheduled[b].item, scheduled[a].item)
                if _bofu_violations(scheduled) < current:
                    current = _bofu_violations(scheduled)
                    improved = True
                else:
                    scheduled[a].item, scheduled[b].item = (
                        scheduled[b].item, scheduled[a].item)
        if not improved:
            return


def build_schedule(
    items: list[Any],
    *,
    start: date,
    weeks: int,
    per_week: int,
    mix: dict[str, int],
    tz: str,
    slots: list[str],
    include_weekends: bool = False,
    now: datetime | None = None,
) -> list[ScheduledItem]:
    zone = ZoneInfo(tz)
    now = now or datetime.now(zone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=zone)

    effective_start = max(start, now.astimezone(zone).date())
    # roll forward to Monday of that week for stable week boundaries
    effective_start -= timedelta(days=effective_start.weekday())

    eligible = list(range(7)) if include_weekends else list(range(5))

    # candidate datetimes across the whole horizon
    candidates: list[datetime] = []
    for w in range(weeks):
        week_start = effective_start + timedelta(days=7 * w)
        for day, hhmm in _week_slots(week_start, eligible, per_week, slots):
            hh, mm = (int(x) for x in hhmm.split(":"))
            candidates.append(datetime.combine(day, time(hh, mm), tzinfo=zone))
    candidates = [c for c in candidates if c > now]
    candidates.sort()

    week_pattern = order_by_mix(mix) or ["TOFU"]
    target_stages = (week_pattern * (weeks + 1))[: len(candidates)]
    ordered_items = _assign_items(target_stages, items)

    n = min(len(ordered_items), len(candidates))
    scheduled = [ScheduledItem(item=ordered_items[i], when=candidates[i])
                 for i in range(n)]
    _repair_bofu_spacing(scheduled)
    return scheduled
