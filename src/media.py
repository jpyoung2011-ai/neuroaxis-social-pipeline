"""Make a rendered PNG publicly reachable so Metricool can fetch it weeks later.

Canva export URLs expire in 24h; posts are scheduled up to a month out. So the
PNG is committed to a dedicated **public** assets repo and referenced by its
stable ``raw.githubusercontent.com`` URL.

Swap this module for an S3/Cloudinary uploader without touching anything else —
``publish_media`` is the only entry point and it just returns a URL string.
"""

from __future__ import annotations

import base64
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
    remote = f"https://github.com/{repo}.git"
    # Auth is supplied per-invocation as an HTTP header so the token never lands
    # in .git/config or a remote URL. It is still redacted from any error text.
    auth_b64 = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    auth_arg = f"http.extraheader=AUTHORIZATION: basic {auth_b64}"
    _secrets = (token, auth_b64)

    identity = {
        **os.environ,
        "GIT_AUTHOR_NAME": "NeuroAxis Pipeline",
        "GIT_AUTHOR_EMAIL": "pipeline@neuroaxis.local",
        "GIT_COMMITTER_NAME": "NeuroAxis Pipeline",
        "GIT_COMMITTER_EMAIL": "pipeline@neuroaxis.local",
    }

    def _redact(text: str) -> str:
        for secret in _secrets:
            if secret:
                text = text.replace(secret, "***")
        return text

    def git(*args: str, auth: bool = False, cwd: Path | None = None,
            check: bool = True) -> str:
        cmd = ["git", *((["-c", auth_arg] if auth else [])), *args]
        result = run(cmd, cwd=str(cwd) if cwd else None,
                     capture_output=True, text=True, env=identity)
        if check and getattr(result, "returncode", 0) != 0:
            detail = getattr(result, "stderr", "") or getattr(result, "stdout", "")
            raise MediaError(f"git {' '.join(args)} failed: {_redact(detail)}")
        return getattr(result, "stdout", "") or ""

    if (workdir / ".git").exists():
        git("pull", "--quiet", auth=True, cwd=workdir)
    else:
        workdir.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--depth", "1", remote, str(workdir), auth=True)

    rel = Path("media") / slugify(batch) / f"{slugify(slug)}.png"
    dest = workdir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)

    git("add", str(rel), cwd=workdir)
    if git("status", "--porcelain", cwd=workdir).strip():
        git("commit", "-m", f"add {rel.as_posix()}", "--quiet", cwd=workdir)
        git("push", "--quiet", remote, "HEAD:main", auth=True, cwd=workdir)

    return raw_url(repo, batch, slug)
