from datetime import datetime, date
from zoneinfo import ZoneInfo

import pytest

from src.scheduling import build_schedule, order_by_mix


class Item:
    def __init__(self, stage, name):
        self.funnel_stage = stage
        self.title = name

    def __repr__(self):
        return f"Item({self.funnel_stage},{self.title})"


def make_items(spec):
    """spec like {'TOFU': 6, 'MOFU': 2, 'BOFU': 2}"""
    out = []
    for stage, n in spec.items():
        for i in range(n):
            out.append(Item(stage, f"{stage}-{i}"))
    return out


TZ = "Europe/London"
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=ZoneInfo(TZ))  # Monday 09:00


def test_order_by_mix_spreads_stages_evenly():
    seq = order_by_mix({"TOFU": 3, "MOFU": 1, "BOFU": 1})
    assert seq.count("TOFU") == 3
    assert seq.count("MOFU") == 1
    assert seq.count("BOFU") == 1
    # BOFU and MOFU should not both be at the very start
    assert seq[0] == "TOFU"


def test_schedules_all_items_when_capacity_allows():
    items = make_items({"TOFU": 6, "MOFU": 2, "BOFU": 2})
    sched = build_schedule(
        items, start=date(2026, 9, 7), weeks=4, per_week=5,
        mix={"TOFU": 3, "MOFU": 1, "BOFU": 1},
        tz=TZ, slots=["10:00", "13:00", "17:00"],
        include_weekends=False, now=NOW,
    )
    assert len(sched) == 10
    times = [s.when for s in sched]
    assert times == sorted(times)
    assert all(t > NOW for t in times)


def test_never_schedules_in_the_past():
    items = make_items({"TOFU": 10})
    sched = build_schedule(
        items, start=date(2026, 1, 1), weeks=4, per_week=5, mix={"TOFU": 5},
        tz=TZ, slots=["10:00"], include_weekends=False, now=NOW,
    )
    assert all(s.when > NOW for s in sched)


def test_skips_weekends_by_default():
    items = make_items({"TOFU": 20})
    sched = build_schedule(
        items, start=date(2026, 9, 7), weeks=4, per_week=5, mix={"TOFU": 5},
        tz=TZ, slots=["10:00"], include_weekends=False, now=NOW,
    )
    assert all(s.when.weekday() < 5 for s in sched)


def test_includes_weekends_when_asked():
    items = make_items({"TOFU": 20})
    sched = build_schedule(
        items, start=date(2026, 9, 7), weeks=2, per_week=7, mix={"TOFU": 7},
        tz=TZ, slots=["10:00"], include_weekends=True, now=NOW,
    )
    weekdays = {s.when.weekday() for s in sched}
    assert weekdays & {5, 6}


def test_times_are_from_slots():
    items = make_items({"TOFU": 12})
    sched = build_schedule(
        items, start=date(2026, 9, 7), weeks=4, per_week=6, mix={"TOFU": 6},
        tz=TZ, slots=["10:00", "13:00", "17:00"],
        include_weekends=False, now=NOW,
    )
    for s in sched:
        assert s.when.strftime("%H:%M") in {"10:00", "13:00", "17:00"}


def test_first_week_matches_funnel_mix():
    items = make_items({"TOFU": 6, "MOFU": 3, "BOFU": 3})
    sched = build_schedule(
        items, start=date(2026, 9, 7), weeks=3, per_week=5,
        mix={"TOFU": 3, "MOFU": 1, "BOFU": 1},
        tz=TZ, slots=["10:00"], include_weekends=False, now=NOW,
    )
    first_week = [s.item.funnel_stage for s in sched[:5]]
    assert first_week.count("TOFU") == 3
    assert first_week.count("MOFU") == 1
    assert first_week.count("BOFU") == 1


def test_no_two_bofu_on_consecutive_days():
    items = make_items({"TOFU": 6, "MOFU": 2, "BOFU": 4})
    sched = build_schedule(
        items, start=date(2026, 9, 7), weeks=3, per_week=4,
        mix={"TOFU": 2, "MOFU": 1, "BOFU": 1},
        tz=TZ, slots=["10:00"], include_weekends=False, now=NOW,
    )
    bofu_days = sorted(s.when.date() for s in sched if s.item.funnel_stage == "BOFU")
    for a, b in zip(bofu_days, bofu_days[1:]):
        assert (b - a).days >= 2


def test_capacity_limits_output():
    items = make_items({"TOFU": 100})
    sched = build_schedule(
        items, start=date(2026, 9, 7), weeks=2, per_week=5, mix={"TOFU": 5},
        tz=TZ, slots=["10:00"], include_weekends=False, now=NOW,
    )
    assert len(sched) == 10


def test_fewer_items_than_capacity():
    items = make_items({"TOFU": 3})
    sched = build_schedule(
        items, start=date(2026, 9, 7), weeks=4, per_week=5, mix={"TOFU": 5},
        tz=TZ, slots=["10:00"], include_weekends=False, now=NOW,
    )
    assert len(sched) == 3
