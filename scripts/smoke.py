"""Manual end-to-end smoke check against real credentials, no writes.

    python -m scripts.smoke

Runs `generate --dry-run` for one item: loads config, calls Claude for copy,
autofills the Canva template, exports a PNG to ./out/. Does NOT touch Notion,
media hosting, or Metricool. Use it once after filling in .env to confirm the
Canva integration and Anthropic key work before trusting the schedule.
"""

from __future__ import annotations

import argparse
import sys

from src.config import ConfigError, Settings
from src.pipeline import cmd_generate


def main() -> int:
    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(exc)
        return 1

    args = argparse.Namespace(
        count=1, batch_label="smoke-test", out="out", dry_run=True)
    print(f"approval mode: {settings.approval_mode}  networks: {settings.networks}")
    print(f"model: {settings.anthropic_model}  template: {settings.canva_brand_template_id}")
    return cmd_generate(settings, args)


if __name__ == "__main__":
    sys.exit(main())
