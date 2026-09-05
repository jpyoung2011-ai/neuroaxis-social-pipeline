import json
from datetime import datetime, timedelta, timezone

import pytest
import responses

from src.notion_client import NotionClient, QueueRow

API = "https://api.notion.com/v1"
DB = "db-123"


class Item:
    funnel_stage = "TOFU"
    topic = "time-blindness"
    title = "Time Blindness Explainer"
    caption = "Ever lose an hour? Learn more at neuroaxis-adhd.com"
    hashtags = ["#ADHD", "#TimeBlindness"]
    platforms = ["instagram", "facebook"]
    canva_design_url = "https://canva.com/d/ABC"


def make_client():
    return NotionClient("ntn_secret", DB)


@responses.activate
def test_create_content_row_builds_properties():
    responses.add(responses.POST, f"{API}/pages", json={"id": "page-1"})
    c = make_client()
    page_id = c.create_content_row(
        Item(), batch_label="Batch 2 - 2026-09-12", status="Pending",
        image_url="https://img/x.png")
    assert page_id == "page-1"
    body = json.loads(responses.calls[0].request.body)
    props = body["properties"]
    assert body["parent"] == {"database_id": DB}
    assert props["Name"]["title"][0]["text"]["content"] == "Time Blindness Explainer"
    assert props["Status"]["select"]["name"] == "Pending"
    assert props["Content Type"]["select"]["name"] == "Educational Short"
    assert props["Funnel Stage"]["select"]["name"] == "TOFU"
    assert {o["name"] for o in props["Platform"]["multi_select"]} == {
        "Instagram", "Facebook"}
    assert props["Canva Link"]["url"] == "https://canva.com/d/ABC"
    assert props["Thumbnail"]["files"][0]["external"]["url"] == "https://img/x.png"
    assert "#ADHD" in props["Notes"]["rich_text"][0]["text"]["content"]


@responses.activate
def test_create_content_row_maps_bofu_to_ad():
    responses.add(responses.POST, f"{API}/pages", json={"id": "p"})
    c = make_client()
    it = Item()
    it.funnel_stage = "BOFU"
    c.create_content_row(it, batch_label="B", status="Approved",
                         image_url="https://i/x.png")
    props = json.loads(responses.calls[0].request.body)["properties"]
    assert props["Content Type"]["select"]["name"] == "Ad"


@responses.activate
def test_query_ready_review_mode_filters_on_approved():
    responses.add(responses.POST, f"{API}/databases/{DB}/query", json={"results": [
        _page("p1", status="Approved", caption="hi", img="https://i/1.png",
              platforms=["Instagram"]),
    ]})
    c = make_client()
    rows = c.query_ready_to_publish(mode="review")
    assert len(rows) == 1
    assert isinstance(rows[0], QueueRow)
    assert rows[0].page_id == "p1"
    assert rows[0].image_url == "https://i/1.png"
    assert rows[0].platforms == ["Instagram"]
    sent = json.loads(responses.calls[0].request.body)
    assert sent["filter"]["property"] == "Status"
    assert sent["filter"]["select"]["equals"] == "Approved"


@responses.activate
def test_query_ready_skips_rows_with_metricool_id():
    responses.add(responses.POST, f"{API}/databases/{DB}/query", json={"results": [
        _page("p1", status="Approved", caption="a", img="https://i/1.png", metricool="55"),
        _page("p2", status="Approved", caption="b", img="https://i/2.png"),
    ]})
    c = make_client()
    rows = c.query_ready_to_publish(mode="review")
    assert [r.page_id for r in rows] == ["p2"]


@responses.activate
def test_query_ready_veto_mode_respects_age():
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    responses.add(responses.POST, f"{API}/databases/{DB}/query", json={"results": [
        _page("old", status="Pending", caption="a", img="https://i/1.png", created=old),
        _page("new", status="Pending", caption="b", img="https://i/2.png", created=fresh),
    ]})
    c = make_client()
    rows = c.query_ready_to_publish(mode="veto", veto_hours=48)
    assert [r.page_id for r in rows] == ["old"]


@responses.activate
def test_mark_row_patches_status_and_schedule_and_id():
    responses.add(responses.PATCH, f"{API}/pages/page-9", json={"id": "page-9"})
    c = make_client()
    when = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    c.mark_row("page-9", status="Posted", scheduled_dt=when, metricool_id="777")
    props = json.loads(responses.calls[0].request.body)["properties"]
    assert props["Status"]["select"]["name"] == "Posted"
    assert props["Scheduled Date"]["date"]["start"].startswith("2026-09-20T10:00")
    assert props["Metricool ID"]["rich_text"][0]["text"]["content"] == "777"


@responses.activate
def test_ensure_properties_adds_missing():
    responses.add(responses.GET, f"{API}/databases/{DB}", json={
        "properties": {"Name": {"type": "title"}, "Status": {"type": "select"}}})
    responses.add(responses.PATCH, f"{API}/databases/{DB}", json={"id": DB})
    c = make_client()
    c.ensure_properties()
    patched = json.loads(responses.calls[1].request.body)["properties"]
    assert "Metricool ID" in patched
    assert "Funnel Stage" in patched


@responses.activate
def test_ensure_properties_noop_when_present():
    responses.add(responses.GET, f"{API}/databases/{DB}", json={"properties": {
        "Metricool ID": {"type": "rich_text"}, "Funnel Stage": {"type": "select"}}})
    c = make_client()
    c.ensure_properties()
    assert len(responses.calls) == 1


def _page(pid, *, status, caption, img, platforms=None, metricool=None,
          created=None):
    props = {
        "Name": {"type": "title", "title": [{"plain_text": "n"}]},
        "Status": {"type": "select", "select": {"name": status}},
        "Notes": {"type": "rich_text", "rich_text": [{"plain_text": caption}]},
        "Funnel Stage": {"type": "select", "select": {"name": "TOFU"}},
        "Thumbnail": {"type": "files",
                      "files": [{"type": "external", "external": {"url": img}}]},
        "Platform": {"type": "multi_select",
                     "multi_select": [{"name": p} for p in (platforms or [])]},
        "Metricool ID": {"type": "rich_text",
                         "rich_text": ([{"plain_text": metricool}] if metricool else [])},
    }
    return {"id": pid, "created_time": created or "2026-09-01T00:00:00.000Z",
            "properties": props}
