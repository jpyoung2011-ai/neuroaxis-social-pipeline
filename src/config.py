"""Loads and validates every credential and setting from the environment.

One dataclass, one entry point: ``Settings.load()``. On any problem it raises
``ConfigError`` whose message lists *every* missing or invalid key at once, so a
misconfigured CI run tells you all the gaps in a single failure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

APPROVAL_MODES = ("review", "auto", "veto")

_REQUIRED = (
    "CANVA_CLIENT_ID",
    "CANVA_CLIENT_SECRET",
    "CANVA_REFRESH_TOKEN",
    "CANVA_BRAND_TEMPLATE_ID",
    "METRICOOL_TOKEN",
    "METRICOOL_USER_ID",
    "METRICOOL_BLOG_ID",
    "ANTHROPIC_API_KEY",
    "NOTION_TOKEN",
    "NOTION_CONTENT_DB_ID",
    "MEDIA_REPO",
    "MEDIA_REPO_TOKEN",
)


class ConfigError(RuntimeError):
    """Raised when the environment is missing keys or holds invalid values."""


@dataclass(frozen=True)
class Settings:
    # --- Canva ---
    canva_client_id: str
    canva_client_secret: str
    canva_refresh_token: str
    canva_brand_template_id: str
    canva_field_map: dict[str, str]  # logical name -> Canva data-field name

    # --- Metricool ---
    metricool_token: str
    metricool_user_id: str
    metricool_blog_id: str
    networks: list[str]
    timezone: str

    # --- Anthropic ---
    anthropic_api_key: str
    anthropic_model: str

    # --- Notion ---
    notion_token: str
    notion_content_db_id: str

    # --- Media hosting ---
    media_repo: str
    media_repo_token: str

    # --- Approval flow ---
    approval_mode: Literal["review", "auto", "veto"]
    veto_hours: int

    # --- Batch / scheduling ---
    batch_count: int
    schedule_weeks: int
    posts_per_week: int
    funnel_mix: dict[str, int]
    schedule_slots: list[str]
    include_weekends: bool

    # --- Brand context ---
    brand_name: str
    brand_website: str

    errors: list[str] = field(default_factory=list, compare=False)

    @staticmethod
    def load(*, use_dotenv: bool = True) -> "Settings":
        if use_dotenv:
            try:
                from dotenv import load_dotenv

                load_dotenv()
            except ImportError:  # pragma: no cover - dotenv is a hard dep in practice
                pass

        errors: list[str] = []

        def require(key: str) -> str:
            val = os.environ.get(key, "").strip()
            if not val:
                errors.append(f"missing required env var: {key}")
            return val

        def as_int(key: str, default: int) -> int:
            raw = os.environ.get(key, "").strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                errors.append(f"{key} must be an integer, got {raw!r}")
                return default

        def as_bool(key: str, default: bool) -> bool:
            raw = os.environ.get(key, "").strip().lower()
            if not raw:
                return default
            if raw in ("1", "true", "yes", "on"):
                return True
            if raw in ("0", "false", "no", "off"):
                return False
            errors.append(f"{key} must be a boolean, got {raw!r}")
            return default

        def as_list(key: str, default: list[str]) -> list[str]:
            raw = os.environ.get(key, "").strip()
            if not raw:
                return list(default)
            return [part.strip() for part in raw.split(",") if part.strip()]

        def as_mix(key: str, default: dict[str, int]) -> dict[str, int]:
            raw = os.environ.get(key, "").strip()
            if not raw:
                return dict(default)
            out: dict[str, int] = {}
            for pair in raw.split(","):
                pair = pair.strip()
                if not pair:
                    continue
                if ":" not in pair:
                    errors.append(f"{key} entries must be STAGE:COUNT, got {pair!r}")
                    continue
                stage, _, count = pair.partition(":")
                try:
                    out[stage.strip().upper()] = int(count)
                except ValueError:
                    errors.append(f"{key} count must be an integer in {pair!r}")
            return out or dict(default)

        canva = {
            "client_id": require("CANVA_CLIENT_ID"),
            "client_secret": require("CANVA_CLIENT_SECRET"),
            "refresh_token": require("CANVA_REFRESH_TOKEN"),
            "template_id": require("CANVA_BRAND_TEMPLATE_ID"),
        }
        field_map = {
            "headline": os.environ.get("CANVA_FIELD_HEADLINE", "headline").strip(),
            "body": os.environ.get("CANVA_FIELD_BODY", "body").strip(),
            "cta": os.environ.get("CANVA_FIELD_CTA", "cta").strip(),
        }

        metricool_token = require("METRICOOL_TOKEN")
        metricool_user_id = require("METRICOOL_USER_ID")
        metricool_blog_id = require("METRICOOL_BLOG_ID")
        anthropic_key = require("ANTHROPIC_API_KEY")
        notion_token = require("NOTION_TOKEN")
        notion_db = require("NOTION_CONTENT_DB_ID")
        media_repo = require("MEDIA_REPO")
        media_repo_token = require("MEDIA_REPO_TOKEN")

        approval_mode = os.environ.get("APPROVAL_MODE", "review").strip().lower()
        if approval_mode not in APPROVAL_MODES:
            errors.append(
                f"APPROVAL_MODE must be one of {APPROVAL_MODES}, got {approval_mode!r}"
            )
            approval_mode = "review"

        settings = Settings(
            canva_client_id=canva["client_id"],
            canva_client_secret=canva["client_secret"],
            canva_refresh_token=canva["refresh_token"],
            canva_brand_template_id=canva["template_id"],
            canva_field_map=field_map,
            metricool_token=metricool_token,
            metricool_user_id=metricool_user_id,
            metricool_blog_id=metricool_blog_id,
            networks=as_list("METRICOOL_NETWORKS",
                             ["twitter", "facebook", "instagram", "gmb"]),
            timezone=os.environ.get("METRICOOL_TIMEZONE", "Europe/London").strip(),
            anthropic_api_key=anthropic_key,
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5").strip(),
            notion_token=notion_token,
            notion_content_db_id=notion_db,
            media_repo=media_repo,
            media_repo_token=media_repo_token,
            approval_mode=approval_mode,  # type: ignore[arg-type]
            veto_hours=as_int("VETO_HOURS", 48),
            batch_count=as_int("BATCH_COUNT", 5),
            schedule_weeks=as_int("SCHEDULE_WEEKS", 4),
            posts_per_week=as_int("POSTS_PER_WEEK", 5),
            funnel_mix=as_mix("FUNNEL_MIX", {"TOFU": 3, "MOFU": 1, "BOFU": 1}),
            schedule_slots=as_list("SCHEDULE_SLOTS", ["10:00", "13:00", "17:00"]),
            include_weekends=as_bool("INCLUDE_WEEKENDS", False),
            brand_name=os.environ.get("BRAND_NAME", "NeuroAxis").strip(),
            brand_website=os.environ.get("BRAND_WEBSITE", "neuroaxis-adhd.com").strip(),
            errors=errors,
        )

        if errors:
            raise ConfigError(
                "invalid configuration:\n  - " + "\n  - ".join(errors)
            )
        return settings
