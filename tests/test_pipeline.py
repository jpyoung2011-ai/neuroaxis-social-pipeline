import argparse
from datetime import datetime, timezone

import pytest

from src.pipeline import Deps, cmd_generate, cmd_publish
from src.content import ContentItem
from src.notion_client import QueueRow


class Settings:
    canva_brand_template_id = "TMPL"
    canva_field_map = {"headline": "headline", "body": "body", "cta": "cta"}
    approval_mode = "review"
    veto_hours = 48
    batch_count = 3
    schedule_weeks = 4
    posts_per_week = 5
    funnel_mix = {"TOFU": 3, "MOFU": 1, "BOFU": 1}
    schedule_slots = ["10:00"]
    include_weekends = False
    timezone = "Europe/London"
    networks = ["twitter", "facebook", "instagram", "gmb"]


def item(topic="time-blindness", stage="TOFU"):
    return ContentItem(funnel_stage=stage, topic=topic, title=topic.title(),
                       headline="H", body="B", cta="C", caption="A kind caption",
                       hashtags=["#ADHD"], platforms=["instagram", "facebook"])


class FakeCanva:
    def __init__(self, fail_on=()):
        self.calls = []
        self._fail_on = set(fail_on)

    def render(self, *, template_id, fields, title):
        self.calls.append(title)
        if title in self._fail_on:
            raise RuntimeError("canva boom")
        return b"PNG:" + title.encode(), f"https://canva/{title}"


class FakeNotion:
    def __init__(self, rows=None):
        self.created = []
        self.marked = []
        self.ensured = 0
        self._rows = rows or []

    def create_content_row(self, it, *, batch_label, status, image_url):
        self.created.append((it.title, status, image_url, batch_label))
        return f"page-{it.title}"

    def ensure_properties(self):
        self.ensured += 1

    def query_ready_to_publish(self, *, mode, veto_hours):
        return list(self._rows)

    def mark_row(self, page_id, *, status=None, scheduled_dt=None, metricool_id=None):
        self.marked.append((page_id, status, metricool_id))


class FakeMetricool:
    def __init__(self):
        self.posts = []

    def create_scheduled_post(self, *, text, media_urls, publish_dt, networks):
        self.posts.append((text, media_urls, publish_dt, networks))
        return f"mc-{len(self.posts)}"


def gen_args(**kw):
    kw.setdefault("count", None)
    kw.setdefault("batch_label", "Batch 9")
    kw.setdefault("out", "out")
    kw.setdefault("dry_run", False)
    return argparse.Namespace(**kw)


def make_deps(items, canva=None, notion=None, metricool=None, media=None):
    return Deps(
        generate_content=lambda s, c, mix: items,
        canva=canva or FakeCanva(),
        publish_media=media or (lambda png, *, slug, batch: f"https://img/{slug}.png"),
        notion=notion or FakeNotion(),
        metricool=metricool or FakeMetricool(),
    )


def test_generate_creates_pending_rows_in_review_mode():
    notion = FakeNotion()
    deps = make_deps([item("a"), item("b")], notion=notion)
    rc = cmd_generate(Settings(), gen_args(), deps)
    assert rc == 0
    assert [c[1] for c in notion.created] == ["Pending", "Pending"]
    assert notion.created[0][2] == "https://img/a.png"


def test_generate_auto_mode_creates_approved_rows():
    s = Settings()
    s.approval_mode = "auto"
    notion = FakeNotion()
    cmd_generate(s, gen_args(), make_deps([item("a")], notion=notion))
    assert notion.created[0][1] == "Approved"


def test_generate_dry_run_writes_pngs_and_skips_writes(tmp_path):
    notion = FakeNotion()
    calls = []
    deps = make_deps([item("a"), item("b")], notion=notion,
                     media=lambda *a, **k: calls.append("media") or "x")
    rc = cmd_generate(Settings(), gen_args(dry_run=True, out=str(tmp_path)), deps)
    assert rc == 0
    assert notion.created == []
    assert calls == []
    assert (tmp_path / "a.png").read_bytes() == b"PNG:A"


def test_generate_isolates_failing_item():
    notion = FakeNotion()
    deps = make_deps([item("a"), item("b"), item("c")], notion=notion,
                     canva=FakeCanva(fail_on={"B"}))
    rc = cmd_generate(Settings(), gen_args(), deps)
    assert rc == 1
    assert {c[0] for c in notion.created} == {"A", "C"}


def test_publish_schedules_and_marks_rows():
    rows = [
        QueueRow("p1", "T1", "cap one", "https://img/1.png", ["Instagram"], "TOFU",
                 "Approved", datetime(2026, 9, 1, tzinfo=timezone.utc)),
        QueueRow("p2", "T2", "cap two", "https://img/2.png",
                 ["Google Business Profile", "X"], "BOFU", "Approved",
                 datetime(2026, 9, 1, tzinfo=timezone.utc)),
    ]
    notion = FakeNotion(rows)
    mc = FakeMetricool()
    deps = make_deps([], notion=notion, metricool=mc)
    rc = cmd_publish(Settings(), argparse.Namespace(dry_run=False), deps)
    assert rc == 0
    assert notion.ensured == 1
    assert len(mc.posts) == 2
    assert {tuple(sorted(p[3])) for p in mc.posts} == {("instagram",), ("gmb", "twitter")}
    assert all(m[1] == "Posted" and m[2].startswith("mc-") for m in notion.marked)


def test_publish_dry_run_makes_no_external_writes():
    rows = [QueueRow("p1", "T1", "c", "https://img/1.png", ["Instagram"], "TOFU",
                     "Approved", datetime(2026, 9, 1, tzinfo=timezone.utc))]
    notion = FakeNotion(rows)
    mc = FakeMetricool()
    cmd_publish(Settings(), argparse.Namespace(dry_run=True),
                make_deps([], notion=notion, metricool=mc))
    assert mc.posts == []
    assert notion.marked == []
    assert notion.ensured == 0


def test_publish_nothing_ready_returns_zero():
    deps = make_deps([], notion=FakeNotion([]))
    assert cmd_publish(Settings(), argparse.Namespace(dry_run=False), deps) == 0
