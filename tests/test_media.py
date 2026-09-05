from pathlib import Path

import pytest

from src.media import MediaError, publish_media, raw_url, slugify


def _verb(cmd):
    """The git subcommand, skipping any leading -c <config> pairs."""
    i = 1
    while i < len(cmd) and cmd[i] == "-c":
        i += 2
    return cmd[i] if i < len(cmd) else None


def test_slugify():
    assert slugify("Time Blindness Explainer!") == "time-blindness-explainer"
    assert slugify("ADHD & You") == "adhd-you"


def test_raw_url():
    assert raw_url("acme/assets", "Batch 2 - 2026-09-12", "time-blindness") == (
        "https://raw.githubusercontent.com/acme/assets/main/"
        "media/batch-2-2026-09-12/time-blindness.png"
    )


def test_publish_media_clones_writes_commits_pushes(tmp_path):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if _verb(cmd) == "clone":
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
            (Path(cmd[-1]) / ".git").mkdir()
        out = " M media/x.png" if _verb(cmd) == "status" else ""
        return type("R", (), {"returncode": 0, "stdout": out, "stderr": ""})()

    url = publish_media(
        b"PNGDATA", slug="Time Blindness", batch="Batch 2 - 2026-09-12",
        repo="acme/assets", token="ghp_supersecret", workdir=tmp_path / "assets",
        run=fake_run)

    assert url == ("https://raw.githubusercontent.com/acme/assets/main/"
                   "media/batch-2-2026-09-12/time-blindness.png")
    written = tmp_path / "assets" / "media" / "batch-2-2026-09-12" / "time-blindness.png"
    assert written.read_bytes() == b"PNGDATA"
    verbs = {_verb(c) for c in calls}
    assert {"clone", "add", "commit", "push"} <= verbs

    flat = " ".join(" ".join(c) for c in calls)
    assert "ghp_supersecret" not in flat            # raw token never on the cmd line
    assert "ghp_supersecret@github.com" not in flat  # nor in a remote URL
    assert "http.extraheader=AUTHORIZATION: basic " in flat


def test_publish_media_pulls_when_already_cloned(tmp_path):
    workdir = tmp_path / "assets"
    (workdir / ".git").mkdir(parents=True)
    verbs = []

    def fake_run(cmd, **kw):
        verbs.append(_verb(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    publish_media(b"X", slug="x", batch="b", repo="acme/assets", token="t",
                  workdir=workdir, run=fake_run)
    assert "clone" not in verbs
    assert "pull" in verbs


def test_publish_media_skips_commit_when_nothing_changed(tmp_path):
    workdir = tmp_path / "assets"
    (workdir / ".git").mkdir(parents=True)
    verbs = []

    def fake_run(cmd, **kw):
        verbs.append(_verb(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    publish_media(b"X", slug="x", batch="b", repo="acme/assets", token="t",
                  workdir=workdir, run=fake_run)
    assert "commit" not in verbs
    assert "push" not in verbs


def test_publish_media_raises_on_git_failure_and_redacts_token(tmp_path):
    def fake_run(cmd, **kw):
        return type("R", (), {
            "returncode": 1, "stdout": "",
            "stderr": "fatal: could not read from https://x-access-token:tok123@github.com",
        })()

    with pytest.raises(MediaError) as exc:
        publish_media(b"X", slug="x", batch="b", repo="acme/assets", token="tok123",
                      workdir=tmp_path / "assets", run=fake_run)
    assert "tok123" not in str(exc.value)
    assert "***" in str(exc.value)
