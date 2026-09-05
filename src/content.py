"""Claude writes the post copy — headline, body, CTA, caption, hashtags.

The model is given a per-item brief (topic + funnel stage) and must return
structured output via a forced tool call. Every returned item is run through
``compliance.check``; a failing item gets one feedback-driven retry and is then
dropped from the batch (logged) rather than failing the whole run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from src import compliance

log = logging.getLogger(__name__)

Stage = Literal["TOFU", "MOFU", "BOFU"]

# Topic bank. Each entry lists the funnel stages it naturally suits.
TOPIC_BANK: list[dict[str, Any]] = [
    {"topic": "adhd-looks-different-in-adults", "stages": ["TOFU"]},
    {"topic": "time-blindness", "stages": ["TOFU"]},
    {"topic": "rejection-sensitivity", "stages": ["TOFU"]},
    {"topic": "adhd-and-masking", "stages": ["TOFU"]},
    {"topic": "executive-function-explained", "stages": ["TOFU"]},
    {"topic": "myth-adhd-is-just-hyperactivity", "stages": ["TOFU"]},
    {"topic": "adhd-in-women", "stages": ["TOFU", "MOFU"]},
    {"topic": "what-an-assessment-involves", "stages": ["MOFU"]},
    {"topic": "no-gp-referral-needed", "stages": ["MOFU"]},
    {"topic": "remote-assessment-how-it-works", "stages": ["MOFU"]},
    {"topic": "shared-care-with-your-gp", "stages": ["MOFU"]},
    {"topic": "adhd-coaching-and-access-to-work", "stages": ["MOFU"]},
    {"topic": "book-your-assessment", "stages": ["BOFU"]},
    {"topic": "appointments-within-days-not-years", "stages": ["BOFU"]},
    {"topic": "transparent-pricing", "stages": ["BOFU"]},
    {"topic": "now-accepting-adults-and-children", "stages": ["BOFU"]},
]

_SYSTEM_PROMPT = """\
You write social media copy for {brand}, a UK private ADHD assessment service \
({website}). Audience: adults and parents in the UK exploring an ADHD assessment, \
often after long NHS waits.

Voice: professional yet warm, plain-English, empowering, never alarmist. \
Short sentences. No jargon without a plain explanation. "ADHD clarity, without the wait."

Services you may reference: private ADHD assessments for ages 6-65, remote video \
appointments, no GP referral needed, appointments within days, ADHD coaching, \
titration support, shared care with GPs, Access to Work support.

HARD COMPLIANCE RULES - copy that breaks any of these is unusable:
- NEVER claim or imply CQC registration. The only permitted phrasing is \
"Operating to CQC standards".
- NEVER promise a cure, a fix, or any guaranteed outcome.
- NEVER tell the reader they have ADHD or diagnose them; use "may", "could", \
"it's worth exploring".
- NEVER name prescription medications or imply a prescription outcome.
- NEVER make superiority claims you cannot substantiate ("fastest in the UK", "the best").
- NEVER reference Trustpilot other than a plain-text "5-star Patient Reviews" mention.
- Encourage, never pressure. No fear-based hooks.

Per funnel stage:
- TOFU: educational/relatable. Goal = reach and recognition. Soft CTA at most \
("Learn more at {website}").
- MOFU: explain how the service works, reduce friction. CTA = visit the site to read more.
- BOFU: a clear, warm invitation to book. CTA = "Book your assessment at {website}".

Return every post through the submit_batch tool. hashtags: 3-5, relevant, UK-oriented \
(e.g. #ADHDUK), no spaces inside a tag.
"""

_TOOL = {
    "name": "submit_batch",
    "description": "Submit the finished batch of social posts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "posts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string",
                                  "description": "Short internal name for this post"},
                        "headline": {"type": "string"},
                        "body": {"type": "string"},
                        "cta": {"type": "string"},
                        "caption": {"type": "string",
                                    "description": "Full post text, no hashtags"},
                        "hashtags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title", "headline", "body", "cta", "caption",
                                 "hashtags"],
                },
            }
        },
        "required": ["posts"],
    },
}


class ContentError(RuntimeError):
    pass


@dataclass
class ContentItem:
    funnel_stage: Stage
    topic: str
    title: str
    headline: str
    body: str
    cta: str
    caption: str
    hashtags: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    image_url: str | None = None
    canva_design_url: str | None = None


def _largest_remainder(count: int, mix: dict[str, int]) -> dict[str, int]:
    total = sum(mix.values()) or 1
    raw = {k: count * v / total for k, v in mix.items()}
    floored = {k: int(v) for k, v in raw.items()}
    remainder = count - sum(floored.values())
    for k in sorted(raw, key=lambda k: raw[k] - floored[k], reverse=True)[:remainder]:
        floored[k] += 1
    return floored


def plan_briefs(count: int, mix: dict[str, int], *,
                now: datetime | None = None) -> list[dict[str, str]]:
    now = now or datetime.now()
    offset = now.timetuple().tm_yday
    per_stage = _largest_remainder(count, mix)

    briefs: list[dict[str, str]] = []
    for stage, n in per_stage.items():
        pool = [t["topic"] for t in TOPIC_BANK if stage in t["stages"]]
        if not pool:
            pool = [t["topic"] for t in TOPIC_BANK]
        for i in range(n):
            briefs.append({"funnel_stage": stage,
                           "topic": pool[(offset + i) % len(pool)]})
    # interleave stages so a batch isn't all-TOFU-then-all-BOFU
    briefs.sort(key=lambda b: {"TOFU": 0, "MOFU": 1, "BOFU": 2}[b["funnel_stage"]])
    interleaved: list[dict[str, str]] = []
    buckets: dict[str, list[dict[str, str]]] = {}
    for b in briefs:
        buckets.setdefault(b["funnel_stage"], []).append(b)
    while any(buckets.values()):
        for stage in ("TOFU", "MOFU", "BOFU"):
            if buckets.get(stage):
                interleaved.append(buckets[stage].pop(0))
    return interleaved


def _make_client(settings: Any):
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _extract_posts(message: Any) -> list[dict]:
    for block in getattr(message, "content", []):
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_batch":
            return list(block.input.get("posts", []))
    raise ContentError("model did not call submit_batch")


def _call(client: Any, model: str, system: str, user: str) -> list[dict]:
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "submit_batch"},
        messages=[{"role": "user", "content": user}],
    )
    return _extract_posts(message)


def generate_content_items(
    settings: Any,
    count: int,
    *,
    mix: dict[str, int],
    client: Any | None = None,
    now: datetime | None = None,
) -> list[ContentItem]:
    client = client or _make_client(settings)
    system = _SYSTEM_PROMPT.format(brand=settings.brand_name,
                                   website=settings.brand_website)
    briefs = plan_briefs(count, mix, now=now)

    user = (
        "Write these posts. Return exactly one entry per brief, in order:\n"
        + json.dumps(briefs, indent=2)
    )
    posts = _call(client, settings.anthropic_model, system, user)
    if len(posts) != len(briefs):
        raise ContentError(
            f"expected {len(briefs)} posts, model returned {len(posts)}")

    items: list[ContentItem] = []
    retries: list[tuple[int, dict[str, str]]] = []
    staged: dict[int, dict] = {}

    for idx, (brief, post) in enumerate(zip(briefs, posts)):
        violations = _violations(post)
        if violations:
            log.warning("post %d (%s) failed compliance: %s",
                        idx, brief["topic"], violations)
            retries.append((idx, brief))
            staged[idx] = post
        else:
            staged[idx] = post

    if retries:
        retry_user = (
            "These posts broke compliance rules. Rewrite them, fixing the issues:\n"
            + json.dumps(
                [{"brief": b, "problems": _violations(staged[i])} for i, b in retries],
                indent=2)
        )
        fixed = _call(client, settings.anthropic_model, system, retry_user)
        for (idx, _brief), new_post in zip(retries, fixed):
            staged[idx] = new_post

    for idx, brief in enumerate(briefs):
        post = staged[idx]
        if _violations(post):
            log.error("dropping post %d (%s): still non-compliant after retry",
                      idx, brief["topic"])
            continue
        items.append(ContentItem(
            funnel_stage=brief["funnel_stage"],  # type: ignore[arg-type]
            topic=brief["topic"],
            title=post["title"],
            headline=post["headline"],
            body=post["body"],
            cta=post["cta"],
            caption=post["caption"],
            hashtags=list(post.get("hashtags", [])),
            platforms=list(settings.networks),
        ))
    return items


def _violations(post: dict) -> list[str]:
    text = " ".join(str(post.get(k, "")) for k in
                    ("headline", "body", "cta", "caption"))
    return compliance.check(text)
