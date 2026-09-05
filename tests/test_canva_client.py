import json

import pytest
import responses

from src.canva_client import CanvaClient, CanvaError

API = "https://api.canva.com/rest/v1"
TOKEN_URL = f"{API}/oauth/token"


def make_client(**kw):
    kw.setdefault("sleep", lambda _s: None)
    return CanvaClient("cid", "csecret", "rt-old", **kw)


@responses.activate
def test_refresh_sets_tokens_and_invokes_callback():
    seen = []
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at-1", "refresh_token": "rt-new", "expires_in": 14400,
    })
    c = make_client(on_token_refresh=seen.append)
    c.refresh()
    assert c.access_token == "at-1"
    assert c.refresh_token == "rt-new"
    assert seen == ["rt-new"]
    # Basic auth header present
    sent = responses.calls[0].request
    assert sent.headers["Authorization"].startswith("Basic ")
    assert "grant_type=refresh_token" in sent.body


@responses.activate
def test_refresh_callback_skipped_when_token_unchanged():
    seen = []
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at-1", "refresh_token": "rt-old", "expires_in": 14400,
    })
    c = make_client(on_token_refresh=seen.append)
    c.refresh()
    assert seen == []


@responses.activate
def test_create_autofill_sends_text_fields():
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at", "refresh_token": "rt-old", "expires_in": 999})
    responses.add(responses.POST, f"{API}/autofills",
                  json={"job": {"id": "job-1", "status": "in_progress"}})
    c = make_client()
    job_id = c.create_autofill("TMPL", {"headline": "Hi", "body": "There"}, title="T")
    assert job_id == "job-1"
    body = json.loads(responses.calls[-1].request.body)
    assert body["brand_template_id"] == "TMPL"
    assert body["title"] == "T"
    assert body["data"]["headline"] == {"type": "text", "text": "Hi"}


@responses.activate
def test_wait_autofill_polls_until_success():
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at", "refresh_token": "rt-old", "expires_in": 999})
    responses.add(responses.GET, f"{API}/autofills/job-1",
                  json={"job": {"id": "job-1", "status": "in_progress"}})
    responses.add(responses.GET, f"{API}/autofills/job-1", json={"job": {
        "id": "job-1", "status": "success",
        "result": {"type": "create_design",
                   "design": {"id": "DSGN", "url": "https://canva.com/d/DSGN"}}}})
    c = make_client()
    design = c.wait_autofill("job-1")
    assert design["id"] == "DSGN"


@responses.activate
def test_wait_autofill_raises_on_failure():
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at", "refresh_token": "rt-old", "expires_in": 999})
    responses.add(responses.GET, f"{API}/autofills/job-x", json={"job": {
        "id": "job-x", "status": "failed",
        "error": {"code": "autofill_error", "message": "bad field"}}})
    c = make_client()
    with pytest.raises(CanvaError, match="bad field"):
        c.wait_autofill("job-x")


@responses.activate
def test_wait_autofill_times_out():
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at", "refresh_token": "rt-old", "expires_in": 999})
    responses.add(responses.GET, f"{API}/autofills/slow",
                  json={"job": {"id": "slow", "status": "in_progress"}})
    c = make_client()
    with pytest.raises(CanvaError, match="timed out"):
        c.wait_autofill("slow", timeout=0)


@responses.activate
def test_export_flow_returns_urls():
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at", "refresh_token": "rt-old", "expires_in": 999})
    responses.add(responses.POST, f"{API}/exports",
                  json={"job": {"id": "ex-1", "status": "in_progress"}})
    responses.add(responses.GET, f"{API}/exports/ex-1",
                  json={"job": {"id": "ex-1", "status": "success",
                                "urls": ["https://dl.canva/x.png"]}})
    c = make_client()
    job_id = c.create_export("DSGN")
    urls = c.wait_export(job_id)
    assert urls == ["https://dl.canva/x.png"]
    body = json.loads(responses.calls[-2].request.body)
    assert body == {"design_id": "DSGN", "format": {"type": "png"}}


@responses.activate
def test_render_end_to_end():
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at", "refresh_token": "rt-old", "expires_in": 999})
    responses.add(responses.POST, f"{API}/autofills",
                  json={"job": {"id": "j", "status": "in_progress"}})
    responses.add(responses.GET, f"{API}/autofills/j", json={"job": {
        "id": "j", "status": "success",
        "result": {"design": {"id": "DSGN", "url": "https://canva.com/d/DSGN"}}}})
    responses.add(responses.POST, f"{API}/exports",
                  json={"job": {"id": "e", "status": "in_progress"}})
    responses.add(responses.GET, f"{API}/exports/e",
                  json={"job": {"id": "e", "status": "success",
                                "urls": ["https://dl.canva/final.png"]}})
    responses.add(responses.GET, "https://dl.canva/final.png",
                  body=b"\x89PNG_bytes", content_type="image/png")
    c = make_client()
    png, design_url = c.render(template_id="TMPL",
                               fields={"headline": "H", "body": "B", "cta": "C"})
    assert png == b"\x89PNG_bytes"
    assert design_url == "https://canva.com/d/DSGN"


@responses.activate
def test_401_triggers_one_refresh_and_retry():
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at-1", "refresh_token": "rt-old", "expires_in": 999})
    responses.add(responses.POST, f"{API}/autofills", status=401,
                  json={"code": "invalid_access_token", "message": "expired"})
    responses.add(responses.POST, TOKEN_URL, json={
        "access_token": "at-2", "refresh_token": "rt-old", "expires_in": 999})
    responses.add(responses.POST, f"{API}/autofills",
                  json={"job": {"id": "ok", "status": "in_progress"}})
    c = make_client()
    assert c.create_autofill("T", {"headline": "x"}) == "ok"
    assert c.access_token == "at-2"
