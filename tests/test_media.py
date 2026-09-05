from pathlib import Path

import pytest

from src.media import MediaError, publish_media, raw_url, slugify


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
        calls.append((list(cmd), kw.get("cwd")))
        # simulate clone creating the dir
        if cmd[:2] == ["git", "clone"]:
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
            (Path(cmd[-1]) / ".git").mkdir()
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    url = publish_media(
        b"PNGDATA", slug="Time Blindness", batch="Batch 2 - 2026-09-12",
        repo="acme/assets", token="ghp_x", workdir=tmp_path / "assets", run=fake_run)

    assert url == ("https://raw.githubusercontent.com/acme/assets/main/"
                   "media/batch-2-2026-09-12/time-blindness.png")
    written = tmp_path / "assets" / "media" / "batch-2-2026-09-12" / "time-blindness.png"
    assert written.read_bytes() == b"PNGDATA"
    verbs = [c[0][1] for c in calls]
    assert "clone" in verbs and "add" in verbs and "commit" in verbs and "push" in verbs
    # token must be embedded in the clone/push remote, not left bare
    assert any("ghp_x@github.com" in " ".join(c[0]) for c in calls)


def test_publish_media_pulls_when_already_cloned(tmp_path):
    workdir = tmp_path / "assets"
    (workdir / ".git").mkdir(parents=True)
    verbs = []

    def fake_run(cmd, **kw):
        verbs.append(cmd[1])
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    publish_media(b"X", slug="x", batch="b", repo="acme/assets", token="t",
                  workdir=workdir, run=fake_run)
    assert "clone" not in verbs
    assert "pull" in verbs


def test_publish_media_raises_on_git_failure(tmp_path):
    def fake_run(cmd, **kw):
        class R:
            returncode = 1
            stdout = ""
            stderr = "boom"
        return R()

    with pytest.raises(MediaError, match="boom"):
        publish_media(b"X", slug="x", batch="b", repo="acme/assets", token="t",
                      workdir=tmp_path / "assets", run=fake_run)
