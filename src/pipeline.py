"""Pipeline orchestration + CLI.

    python -m src.pipeline generate --count 5 [--batch-label "..."] [--dry-run]
    python -m src.pipeline publish [--dry-run]

``generate`` writes drafts into the Notion queue; ``publish`` schedules the
approved ones to Metricool across the configured multi-week horizon. Approval
behaviour is controlled by ``APPROVAL_MODE`` (review / auto / veto).
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from src import media as media_mod
from src.canva_client import CanvaClient
from src.config import Settings
from src.content import generate_content_items
from src.metricool_client import MetricoolClient
from src.notion_client import NotionClient
from src.scheduling import build_schedule

log = logging.getLogger("pipeline")

_STATUS_FOR_MODE = {"review": "Pending", "auto": "Approved", "veto": "Pending"}

_METRICOOL_KEY = {
    "instagram": "instagram", "facebook": "facebook", "linkedin": "linkedin",
    "tiktok": "tiktok", "youtube": "youtube", "x": "twitter", "twitter": "twitter",
    "google business profile": "gmb", "gmb": "gmb",
}


@dataclass
class Deps:
    generate_content: Callable[..., list]
    canva: Any
    publish_media: Callable[..., str]
    notion: Any
    metricool: Any


def _real_deps(settings: Settings) -> Deps:
    assets_workdir = Path(".cache") / "assets-repo"

    def publish_media(png: bytes, *, slug: str, batch: str) -> str:
        return media_mod.publish_media(
            png, slug=slug, batch=batch, repo=settings.media_repo,
            token=settings.media_repo_token, workdir=assets_workdir)

    return Deps(
        generate_content=generate_content_items,
        canva=CanvaClient(settings.canva_client_id, settings.canva_client_secret,
                          settings.canva_refresh_token),
        publish_media=publish_media,
        notion=NotionClient(settings.notion_token, settings.notion_content_db_id),
        metricool=MetricoolClient(settings.metricool_token, settings.metricool_user_id,
                                  settings.metricool_blog_id,
                                  timezone=settings.timezone),
    )


def _metricool_networks(labels: list[str], default: list[str]) -> list[str]:
    keys = [_METRICOOL_KEY.get(l.lower(), l.lower()) for l in labels]
    return keys or list(default)


# --- generate ---------------------------------------------------------

def cmd_generate(settings: Settings, args: argparse.Namespace,
                 deps: Deps | None = None) -> int:
    deps = deps or _real_deps(settings)
    count = args.count or settings.batch_count
    batch_label = args.batch_label or f"Batch - {date.today().isoformat()}"
    status = _STATUS_FOR_MODE[settings.approval_mode]

    items = deps.generate_content(settings, count, mix=settings.funnel_mix)
    if not items:
        log.warning("no content generated")
        return 1

    out_dir = Path(args.out)
    if args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    failures = 0
    for item in items:
        try:
            png, design_url = deps.canva.render(
                template_id=settings.canva_brand_template_id,
                fields={
                    settings.canva_field_map["headline"]: item.headline,
                    settings.canva_field_map["body"]: item.body,
                    settings.canva_field_map["cta"]: item.cta,
                },
                title=item.title,
            )
            item.canva_design_url = design_url

            if args.dry_run:
                dest = out_dir / f"{item.topic}.png"
                dest.write_bytes(png)
                log.info("[dry-run] %s -> %s (%d bytes), status would be %s",
                         item.title, dest, len(png), status)
                created += 1
                continue

            image_url = deps.publish_media(png, slug=item.topic, batch=batch_label)
            item.image_url = image_url
            deps.notion.create_content_row(
                item, batch_label=batch_label, status=status, image_url=image_url)
            created += 1
            log.info("queued %s (%s)", item.title, status)
        except Exception as exc:  # one bad item must not sink the batch
            failures += 1
            log.error("failed on %s: %s", getattr(item, "title", "?"), exc)

    log.info("generate: %d queued, %d failed, batch=%s", created, failures, batch_label)
    return 1 if failures else 0


# --- publish ---------------------------------------------------------

def cmd_publish(settings: Settings, args: argparse.Namespace,
                deps: Deps | None = None) -> int:
    deps = deps or _real_deps(settings)
    if not args.dry_run:
        deps.notion.ensure_properties()

    rows = deps.notion.query_ready_to_publish(
        mode=settings.approval_mode, veto_hours=settings.veto_hours)
    if not rows:
        log.info("publish: nothing ready")
        return 0

    schedule = build_schedule(
        rows, start=date.today(), weeks=settings.schedule_weeks,
        per_week=settings.posts_per_week, mix=settings.funnel_mix,
        tz=settings.timezone, slots=settings.schedule_slots,
        include_weekends=settings.include_weekends)

    scheduled = 0
    failures = 0
    for slot in schedule:
        row = slot.item
        try:
            networks = _metricool_networks(row.platforms, settings.networks)
            if args.dry_run:
                log.info("[dry-run] %s -> %s on %s",
                         row.title, slot.when.isoformat(), networks)
                scheduled += 1
                continue
            post_id = deps.metricool.create_scheduled_post(
                text=row.caption, media_urls=[row.image_url] if row.image_url else [],
                publish_dt=slot.when, networks=networks)
            deps.notion.mark_row(row.page_id, status="Posted",
                                 scheduled_dt=slot.when, metricool_id=post_id)
            scheduled += 1
            log.info("scheduled %s for %s", row.title, slot.when.isoformat())
        except Exception as exc:
            failures += 1
            log.error("failed to schedule %s: %s", row.title, exc)

    log.info("publish: %d scheduled, %d failed", scheduled, failures)
    return 1 if failures else 0


# --- CLI ------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m src.pipeline")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate a batch of drafts into Notion")
    g.add_argument("--count", type=int, default=None)
    g.add_argument("--batch-label", default=None)
    g.add_argument("--out", default="out", help="dir for --dry-run PNGs")
    g.add_argument("--dry-run", action="store_true")

    pub = sub.add_parser("publish", help="schedule approved drafts to Metricool")
    pub.add_argument("--dry-run", action="store_true")

    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    settings = Settings.load()
    if args.command == "generate":
        return cmd_generate(settings, args)
    if args.command == "publish":
        return cmd_publish(settings, args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
