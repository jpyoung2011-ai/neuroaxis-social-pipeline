"""Metricool REST API client (v2 scheduler).

Endpoint shapes verified against Metricool's public CLI wrapper
(github.com/Purple-Horizons/metricool-cli): base ``https://app.metricool.com/api``,
auth via ``userToken``/``userId``/``blogId`` query params plus an ``X-Mc-Auth``
header, posts created at ``POST /v2/scheduler/posts``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

_BASE = "https://app.metricool.com/api"

_NETWORK_ALIASES = {
    "x": "twitter",
    "twitter": "twitter",
    "googlebusiness": "gmb",
    "google_business_profile": "gmb",
    "gbp": "gmb",
    "gmb": "gmb",
}


class MetricoolError(RuntimeError):
    pass


class MetricoolClient:
    def __init__(self, token: str, user_id: str, blog_id: str, *,
                 timezone: str = "Europe/London",
                 session: requests.Session | None = None) -> None:
        self._token = token
        self._user_id = user_id
        self._blog_id = blog_id
        self.timezone = timezone
        self._session = session or requests.Session()

    # --- public -------------------------------------------------------

    def normalize_media(self, url: str) -> str:
        payload = self._request("GET", "/actions/normalize/image/url",
                                params={"url": url})
        return _extract_url(payload) or url

    def list_scheduled_posts(self, *, start: str | None = None,
                             end: str | None = None) -> list[dict]:
        params: dict[str, str] = {}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        params["timezone"] = self.timezone
        payload = self._request("GET", "/v2/scheduler/posts", params=params)
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        return data if isinstance(data, list) else []

    def create_scheduled_post(
        self, *, text: str, media_urls: list[str], publish_dt: datetime,
        networks: list[str], draft: bool = False,
        first_comment: str | None = None,
    ) -> str:
        media = [self.normalize_media(u) for u in media_urls]
        providers = [{"network": _NETWORK_ALIASES.get(n.lower(), n.lower())}
                     for n in networks]
        body: dict[str, Any] = {
            "text": text,
            "providers": providers,
            "publicationDate": {
                "dateTime": publish_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "timezone": self.timezone,
            },
            "draft": draft,
            "autoPublish": not draft,
            "media": media,
        }
        if first_comment:
            body["firstCommentText"] = first_comment
        payload = self._request("POST", "/v2/scheduler/posts", json=body)
        return _extract_id(payload)

    # --- internal ---------------------------------------------------

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        params = {
            "userToken": self._token,
            "userId": self._user_id,
            "blogId": self._blog_id,
            **kwargs.pop("params", {}),
        }
        resp = self._session.request(
            method, f"{_BASE}{endpoint}", params=params,
            headers={"X-Mc-Auth": self._token, "Content-Type": "application/json"},
            timeout=30, **kwargs)
        if resp.status_code >= 400:
            raise MetricoolError(
                f"{method} {endpoint} -> {resp.status_code}: {resp.text}")
        try:
            return resp.json()
        except ValueError:
            return resp.text


def _extract_url(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip().strip('"')
    if isinstance(payload, dict):
        for key in ("data", "url", "normalizedUrl", "result"):
            val = payload.get(key)
            if isinstance(val, str):
                return val
    return ""


def _extract_id(payload: Any) -> str:
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, dict) and data.get("id") is not None:
            return str(data["id"])
        if payload.get("id") is not None:
            return str(payload["id"])
    raise MetricoolError(f"could not find post id in Metricool response: {payload!r}")
