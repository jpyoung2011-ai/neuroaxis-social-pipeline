"""Notion REST wrapper for the "Marketing Content Queue" database.

The queue is the pipeline's durable state store and JP's review surface:
``generate`` writes rows, a human (or a mode) approves them, ``publish`` reads
the approved ones and marks them scheduled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import requests

_API = "https://api.notion.com/v1"
_VERSION = "2022-06-28"

_CONTENT_TYPE_BY_STAGE = {
    "TOFU": "Educational Short",
    "MOFU": "General Post",
    "BOFU": "Ad",
}
_PLATFORM_LABELS = {
    "instagram": "Instagram", "facebook": "Facebook", "linkedin": "LinkedIn",
    "tiktok": "TikTok", "x": "X", "twitter": "X", "gmb": "Google Business Profile",
    "youtube": "YouTube",
}


class NotionError(RuntimeError):
    pass


@dataclass
class QueueRow:
    page_id: str
    title: str
    caption: str
    image_url: str
    platforms: list[str]
    funnel_stage: str
    status: str
    created_time: datetime
    metricool_id: str = ""


class NotionClient:
    def __init__(self, token: str, database_id: str, *,
                 session: requests.Session | None = None) -> None:
        self._db = database_id
        self._session = session or requests.Session()
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": _VERSION,
            "Content-Type": "application/json",
        }

    # --- write ----------------------------------------------------------

    def create_content_row(self, item: Any, *, batch_label: str, status: str,
                           image_url: str,
                           scheduled_dt: datetime | None = None) -> str:
        caption = item.caption
        tags = " ".join(getattr(item, "hashtags", []) or [])
        if tags:
            caption = f"{caption}\n\n{tags}"

        props: dict[str, Any] = {
            "Name": {"title": [{"text": {"content": item.title[:2000]}}]},
            "Batch": _rich_text(batch_label),
            "Status": {"select": {"name": status}},
            "Content Type": {"select": {
                "name": _CONTENT_TYPE_BY_STAGE.get(item.funnel_stage, "General Post")}},
            "Funnel Stage": {"select": {"name": item.funnel_stage}},
            "Platform": {"multi_select": [
                {"name": _PLATFORM_LABELS.get(p.lower(), p)} for p in item.platforms]},
            "Notes": _rich_text(caption),
            "Thumbnail": {"files": [{
                "type": "external", "name": f"{item.topic}.png",
                "external": {"url": image_url}}]},
        }
        if getattr(item, "canva_design_url", None):
            props["Canva Link"] = {"url": item.canva_design_url}
        if scheduled_dt is not None:
            props["Scheduled Date"] = {"date": {"start": scheduled_dt.isoformat()}}

        resp = self._request("POST", "/pages", json={
            "parent": {"database_id": self._db}, "properties": props})
        return resp.json()["id"]

    def mark_row(self, page_id: str, *, status: str | None = None,
                 scheduled_dt: datetime | None = None,
                 metricool_id: str | None = None) -> None:
        props: dict[str, Any] = {}
        if status is not None:
            props["Status"] = {"select": {"name": status}}
        if scheduled_dt is not None:
            props["Scheduled Date"] = {"date": {"start": scheduled_dt.isoformat()}}
        if metricool_id is not None:
            props["Metricool ID"] = _rich_text(str(metricool_id))
        if not props:
            return
        self._request("PATCH", f"/pages/{page_id}", json={"properties": props})

    # --- read -----------------------------------------------------------

    def query_ready_to_publish(
        self, *, mode: Literal["review", "auto", "veto"], veto_hours: int = 48,
    ) -> list[QueueRow]:
        wanted_status = "Pending" if mode == "veto" else "Approved"
        results: list[dict] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"filter": {
                "property": "Status", "select": {"equals": wanted_status}}}
            if cursor:
                body["start_cursor"] = cursor
            page = self._request(
                "POST", f"/databases/{self._db}/query", json=body).json()
            results.extend(page.get("results", []))
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")

        cutoff = datetime.now(timezone.utc) - timedelta(hours=veto_hours)
        rows: list[QueueRow] = []
        for raw in results:
            row = _parse_row(raw)
            if row.metricool_id or row.status in ("Posted", "Rejected", "Needs Edit"):
                continue
            if mode == "veto" and row.created_time > cutoff:
                continue
            rows.append(row)
        return rows

    # --- schema -------------------------------------------------------

    def ensure_properties(self) -> None:
        existing = self._request("GET", f"/databases/{self._db}").json()
        have = set(existing.get("properties", {}))
        add: dict[str, Any] = {}
        if "Metricool ID" not in have:
            add["Metricool ID"] = {"rich_text": {}}
        if "Funnel Stage" not in have:
            add["Funnel Stage"] = {"select": {"options": [
                {"name": "TOFU", "color": "purple"},
                {"name": "MOFU", "color": "blue"},
                {"name": "BOFU", "color": "pink"},
            ]}}
        if add:
            self._request("PATCH", f"/databases/{self._db}", json={"properties": add})

    # --- internal ---------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        resp = self._session.request(
            method, f"{_API}{path}", headers=self._headers, timeout=30, **kwargs)
        if resp.status_code >= 400:
            raise NotionError(f"{method} {path} -> {resp.status_code}: {resp.text}")
        return resp


def _rich_text(text: str) -> dict:
    return {"rich_text": [{"text": {"content": chunk}}
                          for chunk in _chunks(text, 2000)] or [{"text": {"content": ""}}]}


def _chunks(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] if text else []


def _plain(prop: dict | None) -> str:
    if not prop:
        return ""
    for arr_key in ("title", "rich_text"):
        if prop.get(arr_key):
            return "".join(part.get("plain_text", "") for part in prop[arr_key])
    return ""


def _parse_row(raw: dict) -> QueueRow:
    props = raw.get("properties", {})
    thumb = props.get("Thumbnail", {}).get("files", [])
    image_url = ""
    if thumb:
        f = thumb[0]
        image_url = (f.get("external") or f.get("file") or {}).get("url", "")
    created = raw.get("created_time", "1970-01-01T00:00:00.000Z").replace("Z", "+00:00")
    return QueueRow(
        page_id=raw["id"],
        title=_plain(props.get("Name")),
        caption=_plain(props.get("Notes")),
        image_url=image_url,
        platforms=[o["name"] for o in props.get("Platform", {}).get("multi_select", [])],
        funnel_stage=(props.get("Funnel Stage", {}).get("select") or {}).get("name", ""),
        status=(props.get("Status", {}).get("select") or {}).get("name", ""),
        created_time=datetime.fromisoformat(created),
        metricool_id=_plain(props.get("Metricool ID")),
    )
