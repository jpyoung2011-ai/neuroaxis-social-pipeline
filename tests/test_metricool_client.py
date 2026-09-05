import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import responses

from src.metricool_client import MetricoolClient, MetricoolError

BASE = "https://app.metricool.com/api"


def make_client(**kw):
    kw.setdefault("timezone", "Europe/London")
    return MetricoolClient("tok", "42", "99", **kw)


@responses.activate
def test_normalize_media_returns_url_from_plain_string():
    responses.add(responses.GET, f"{BASE}/actions/normalize/image/url",
                  body='"https://cdn.metricool/x.png"',
                  content_type="application/json")
    c = make_client()
    assert c.normalize_media("https://raw/x.png") == "https://cdn.metricool/x.png"
    assert "url=https%3A%2F%2Fraw%2Fx.png" in responses.calls[0].request.url
    assert responses.calls[0].request.headers["X-Mc-Auth"] == "tok"


@responses.activate
def test_normalize_media_returns_url_from_object():
    responses.add(responses.GET, f"{BASE}/actions/normalize/image/url",
                  json={"data": "https://cdn.metricool/y.png"})
    c = make_client()
    assert c.normalize_media("https://raw/y.png") == "https://cdn.metricool/y.png"


@responses.activate
def test_create_scheduled_post_builds_body_and_returns_id():
    responses.add(responses.GET, f"{BASE}/actions/normalize/image/url",
                  json={"data": "https://cdn.metricool/x.png"})
    responses.add(responses.POST, f"{BASE}/v2/scheduler/posts",
                  json={"data": {"id": "post-123"}})
    c = make_client()
    when = datetime(2026, 9, 20, 10, 0, tzinfo=ZoneInfo("Europe/London"))
    post_id = c.create_scheduled_post(
        text="Hello world",
        media_urls=["https://raw/x.png"],
        publish_dt=when,
        networks=["instagram", "facebook"],
    )
    assert post_id == "post-123"
    req = responses.calls[-1].request
    assert "userId=42" in req.url and "blogId=99" in req.url
    body = json.loads(req.body)
    assert body["text"] == "Hello world"
    assert body["providers"] == [{"network": "instagram"}, {"network": "facebook"}]
    assert body["publicationDate"] == {
        "dateTime": "2026-09-20T10:00:00", "timezone": "Europe/London"}
    assert body["autoPublish"] is True
    assert body["draft"] is False
    assert body["media"] == ["https://cdn.metricool/x.png"]


@responses.activate
def test_create_scheduled_post_draft_disables_autopublish():
    responses.add(responses.POST, f"{BASE}/v2/scheduler/posts",
                  json={"data": {"id": "p"}})
    c = make_client()
    c.create_scheduled_post(text="t", media_urls=[], publish_dt=datetime(2026, 9, 1, 9, 0),
                            networks=["twitter"], draft=True)
    body = json.loads(responses.calls[-1].request.body)
    assert body["draft"] is True
    assert body["autoPublish"] is False


@responses.activate
def test_network_aliases_normalised():
    responses.add(responses.POST, f"{BASE}/v2/scheduler/posts", json={"data": {"id": "p"}})
    c = make_client()
    c.create_scheduled_post(text="t", media_urls=[], publish_dt=datetime(2026, 9, 1, 9, 0),
                            networks=["X", "googlebusiness"])
    body = json.loads(responses.calls[-1].request.body)
    assert body["providers"] == [{"network": "twitter"}, {"network": "gmb"}]


@responses.activate
def test_http_error_raises():
    responses.add(responses.POST, f"{BASE}/v2/scheduler/posts", status=422,
                  body="bad networks")
    c = make_client()
    with pytest.raises(MetricoolError, match="bad networks"):
        c.create_scheduled_post(text="t", media_urls=[],
                                publish_dt=datetime(2026, 9, 1, 9, 0), networks=["instagram"])


@responses.activate
def test_list_scheduled_posts():
    responses.add(responses.GET, f"{BASE}/v2/scheduler/posts",
                  json={"data": [{"id": "1"}, {"id": "2"}]})
    c = make_client()
    posts = c.list_scheduled_posts(start="2026-09-01", end="2026-10-01")
    assert [p["id"] for p in posts] == ["1", "2"]
