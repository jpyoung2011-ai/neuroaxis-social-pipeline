"""Make a rendered PNG publicly reachable so Metricool can fetch it weeks later.

Canva export URLs expire in 24h; posts are scheduled up to a month out. So the
PNG is committed to a dedicated **public** assets repo and referenced by its
stable ``raw.githubusercontent.com`` URL.

Swap this module for an S3/Cloudinary uploader without touching anything else —
``publish_media`` is the only entry point and it just returns a URL string.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable

_RUN = Callable[..., "subprocess.CompletedProcess"]


class MediaError(RuntimeError):
    pass


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def raw_url(repo: str, batch: str, slug: str) -> str:
    return (f"https://raw.githubusercontent.com/{repo}/main/"
            f"media/{slugify(batch)}/{slugify(slug)}.png")


def publish_media(
    png: bytes,
    *,
    slug: str,
    batch: str,
    repo: str,
    token: str,
    workdir: str | Path,
    run: _RUN = subprocess.run,
) -> str:
    workdir = Path(workdir)
    remote = f"https://x-access-token:{token}@github.com/{repo}.git"

    identity = {
        **os.environ,
        "GIT_AUTHOR_NAME": "NeuroAxis Pipeline",
        "GIT_AUTHOR_EMAIL": "pipeline@neuroaxis.local",
        "GIT_COMMITTER_NAME": "NeuroAxis Pipeline",
        "GIT_COMMITTER_EMAIL": "pipeline@neuroaxis.local",
    }

    def git(*args: str, cwd: Path | None = None) -> None:
        result = run(["git", *args], cwd=str(cwd) if cwd else None,
                     capture_output=True, text=True, env=identity)
        if getattr(result, "returncode", 0) != 0:
            raise MediaError(
                f"git {' '.join(args)} failed: "
                f"{getattr(result, 'stderr', '') or getattr(result, 'stdout', '')}")

    if (workdir / ".git").exists():
        git("pull", "--quiet", cwd=workdir)
    else:
        workdir.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--depth", "1", remote, str(workdir))

    rel = Path("media") / slugify(batch) / f"{slugify(slug)}.png"
    dest = workdir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)

    git("add", str(rel), cwd=workdir)
    git("commit", "-m", f"add {rel.as_posix()}", "--quiet", cwd=workdir)
    git("push", "--quiet", remote, "HEAD:main", cwd=workdir)

    return raw_url(repo, batch, slug)
