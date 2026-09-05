"""Canva Connect API client: token refresh, brand-template autofill, PNG export.

Only the slice the pipeline needs. All async Canva jobs (autofill, export) are
polled here with an injectable ``sleep`` so tests run instantly.

IMPORTANT (from Canva docs): the Autofill API requires the acting user to belong
to a Canva Enterprise organisation, or to be within the limited development
trial. If autofill returns ``feature_not_available`` / ``trial_quota_exceeded``,
that is an account-tier problem, not a bug here.

Canva rotates the refresh token on every exchange and invalidates the old one.
For unattended CI the new token MUST be persisted: pass ``on_token_refresh`` and
wire it to whatever stores the secret.
"""

from __future__ import annotations

import base64
import time
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import requests

_API = "https://api.canva.com/rest/v1"
_TERMINAL = {"success", "failed"}


def _safe_url(url: str) -> str:
    """Drop the query string — Canva download URLs carry signed credentials."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class CanvaError(RuntimeError):
    """Any Canva API failure (auth, job failure, timeout, HTTP error)."""


class CanvaClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_token_refresh: Callable[[str], None] | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token: str | None = None
        self._session = session or requests.Session()
        self._sleep = sleep
        self._on_token_refresh = on_token_refresh
        self._poll_interval = poll_interval

    # --- auth ---------------------------------------------------------------

    def refresh(self) -> None:
        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        resp = self._session.post(
            f"{_API}/oauth/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            timeout=30,
        )
        if resp.status_code != 200:
            raise CanvaError(
                f"token refresh failed ({resp.status_code}): "
                f"{self._scrub(resp.text)}")
        payload = resp.json()
        self.access_token = payload["access_token"]
        new_refresh = payload.get("refresh_token", self.refresh_token)
        if new_refresh != self.refresh_token:
            self.refresh_token = new_refresh
            if self._on_token_refresh:
                self._on_token_refresh(new_refresh)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if self.access_token is None:
            self.refresh()
        url = path if path.startswith("http") else f"{_API}{path}"
        headers = {"Authorization": f"Bearer {self.access_token}", **kwargs.pop("headers", {})}
        resp = self._session.request(method, url, headers=headers, timeout=60, **kwargs)
        if resp.status_code == 401:
            self.refresh()
            headers["Authorization"] = f"Bearer {self.access_token}"
            resp = self._session.request(method, url, headers=headers, timeout=60, **kwargs)
        if resp.status_code >= 400:
            raise CanvaError(
                f"{method} {_safe_url(url)} -> {resp.status_code}: "
                f"{self._scrub(resp.text)}")
        return resp

    def _scrub(self, text: str) -> str:
        """Redact this client's own tokens from any text bound for logs/errors."""
        for secret in (self.access_token, self.refresh_token,
                       self._client_secret):
            if secret:
                text = text.replace(secret, "***")
        return text

    # --- autofill ---------------------------------------------------------

    def create_autofill(self, template_id: str, fields: dict[str, str],
                        *, title: str | None = None) -> str:
        body: dict = {
            "brand_template_id": template_id,
            "data": {name: {"type": "text", "text": value}
                     for name, value in fields.items()},
        }
        if title:
            body["title"] = title
        resp = self._request("POST", "/autofills", json=body)
        return resp.json()["job"]["id"]

    def wait_autofill(self, job_id: str, *, timeout: float = 120.0,
                      interval: float | None = None) -> dict:
        job = self._poll(f"/autofills/{job_id}", timeout, interval)
        if job["status"] == "failed":
            raise CanvaError(f"autofill failed: {self._job_error(job)}")
        return job["result"]["design"]

    # --- export ---------------------------------------------------------

    def create_export(self, design_id: str, *, fmt: str = "png") -> str:
        resp = self._request("POST", "/exports", json={
            "design_id": design_id, "format": {"type": fmt}})
        return resp.json()["job"]["id"]

    def wait_export(self, job_id: str, *, timeout: float = 120.0,
                    interval: float | None = None) -> list[str]:
        job = self._poll(f"/exports/{job_id}", timeout, interval)
        if job["status"] == "failed":
            raise CanvaError(f"export failed: {self._job_error(job)}")
        return job.get("urls", [])

    def download(self, url: str) -> bytes:
        # Canva export URLs are pre-signed; send no Authorization header.
        resp = self._session.get(url, timeout=60)
        if resp.status_code >= 400:
            raise CanvaError(f"GET {_safe_url(url)} -> {resp.status_code}")
        return resp.content

    # --- high level ----------------------------------------------------

    def render(self, *, template_id: str, fields: dict[str, str],
               title: str | None = None) -> tuple[bytes, str]:
        """Autofill the template, export page 1 as PNG, return (bytes, design_url)."""
        job_id = self.create_autofill(template_id, fields, title=title)
        design = self.wait_autofill(job_id)
        export_id = self.create_export(design["id"])
        urls = self.wait_export(export_id)
        if not urls:
            raise CanvaError("export produced no download URLs")
        return self.download(urls[0]), design.get("url", "")

    # --- helpers -------------------------------------------------------

    def _poll(self, path: str, timeout: float, interval: float | None) -> dict:
        interval = self._poll_interval if interval is None else interval
        deadline = time.monotonic() + timeout
        first = True
        while first or time.monotonic() < deadline:
            first = False
            job = self._request("GET", path).json()["job"]
            if job["status"] in _TERMINAL:
                return job
            self._sleep(interval)
        raise CanvaError(f"job {path} timed out after {timeout}s")

    @staticmethod
    def _job_error(job: dict) -> str:
        err = job.get("error") or {}
        return err.get("message") or err.get("code") or "unknown error"
