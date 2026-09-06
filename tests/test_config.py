import pytest

from src.config import ConfigError, Settings

REQUIRED_ENV = {
    "CANVA_CLIENT_ID": "cid",
    "CANVA_CLIENT_SECRET": "csecret",
    "CANVA_REFRESH_TOKEN": "crt",
    "CANVA_BRAND_TEMPLATE_ID": "tmpl123",
    "METRICOOL_TOKEN": "mtok",
    "METRICOOL_USER_ID": "42",
    "METRICOOL_BLOG_ID": "99",
    "ANTHROPIC_API_KEY": "sk-ant",
    "NOTION_TOKEN": "ntn",
    "NOTION_CONTENT_DB_ID": "db123",
    "MEDIA_REPO": "acme/assets",
    "MEDIA_REPO_TOKEN": "ghp_x",
}


def _load(env, monkeypatch):
    for key in list(REQUIRED_ENV) + [
        "CANVA_FIELD_HEADLINE", "CANVA_FIELD_BODY", "CANVA_FIELD_CTA",
        "METRICOOL_NETWORKS", "METRICOOL_TIMEZONE", "APPROVAL_MODE", "VETO_HOURS",
        "BATCH_COUNT", "SCHEDULE_WEEKS", "POSTS_PER_WEEK", "FUNNEL_MIX",
        "SCHEDULE_SLOTS", "INCLUDE_WEEKENDS", "ANTHROPIC_MODEL",
        "BRAND_NAME", "BRAND_WEBSITE",
    ]:
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings.load(use_dotenv=False)


def test_loads_when_all_required_present(monkeypatch):
    s = _load(REQUIRED_ENV, monkeypatch)
    assert s.canva_client_id == "cid"
    assert s.notion_content_db_id == "db123"
    assert s.metricool_user_id == "42"


def test_missing_keys_are_all_reported(monkeypatch):
    env = {k: v for k, v in REQUIRED_ENV.items()
           if k not in ("METRICOOL_TOKEN", "NOTION_TOKEN")}
    with pytest.raises(ConfigError) as exc:
        _load(env, monkeypatch)
    msg = str(exc.value)
    assert "METRICOOL_TOKEN" in msg
    assert "NOTION_TOKEN" in msg


def test_defaults_applied(monkeypatch):
    s = _load(REQUIRED_ENV, monkeypatch)
    assert s.approval_mode == "review"
    assert s.veto_hours == 48
    assert s.schedule_weeks == 4
    assert s.posts_per_week == 5
    assert s.funnel_mix == {"TOFU": 3, "MOFU": 1, "BOFU": 1}
    assert s.schedule_slots == ["10:00", "13:00", "17:00"]
    assert s.include_weekends is False
    assert s.networks == ["twitter", "facebook", "instagram", "gmb"]
    assert s.canva_field_map == {"headline": "headline", "body": "body", "cta": "cta"}


def test_overrides_parsed(monkeypatch):
    env = {
        **REQUIRED_ENV,
        "APPROVAL_MODE": "veto",
        "VETO_HOURS": "24",
        "POSTS_PER_WEEK": "3",
        "FUNNEL_MIX": "TOFU:2,MOFU:1",
        "SCHEDULE_SLOTS": "09:30, 18:00",
        "INCLUDE_WEEKENDS": "true",
        "METRICOOL_NETWORKS": "facebook, instagram",
        "CANVA_FIELD_HEADLINE": "title_field",
    }
    s = _load(env, monkeypatch)
    assert s.approval_mode == "veto"
    assert s.veto_hours == 24
    assert s.posts_per_week == 3
    assert s.funnel_mix == {"TOFU": 2, "MOFU": 1}
    assert s.schedule_slots == ["09:30", "18:00"]
    assert s.include_weekends is True
    assert s.networks == ["facebook", "instagram"]
    assert s.canva_field_map["headline"] == "title_field"


def test_invalid_approval_mode_rejected(monkeypatch):
    with pytest.raises(ConfigError):
        _load({**REQUIRED_ENV, "APPROVAL_MODE": "yolo"}, monkeypatch)


def test_invalid_int_rejected(monkeypatch):
    with pytest.raises(ConfigError):
        _load({**REQUIRED_ENV, "SCHEDULE_WEEKS": "lots"}, monkeypatch)


def test_smoke_scope_only_needs_canva_and_anthropic(monkeypatch):
    env = {
        "CANVA_CLIENT_ID": "c", "CANVA_CLIENT_SECRET": "c",
        "CANVA_REFRESH_TOKEN": "c", "CANVA_BRAND_TEMPLATE_ID": "t",
        "ANTHROPIC_API_KEY": "sk",
    }
    for key in list(REQUIRED_ENV) + ["APPROVAL_MODE"]:
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = Settings.load(use_dotenv=False, scope="smoke")
    assert s.canva_client_id == "c"


def test_publish_scope_does_not_need_canva(monkeypatch):
    env = {
        "NOTION_TOKEN": "n", "NOTION_CONTENT_DB_ID": "db",
        "METRICOOL_TOKEN": "m", "METRICOOL_USER_ID": "1", "METRICOOL_BLOG_ID": "2",
    }
    for key in list(REQUIRED_ENV):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = Settings.load(use_dotenv=False, scope="publish")
    assert s.notion_token == "n"

    monkeypatch.delenv("METRICOOL_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="METRICOOL_TOKEN"):
        Settings.load(use_dotenv=False, scope="publish")
