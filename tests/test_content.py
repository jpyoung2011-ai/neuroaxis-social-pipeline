import types
from datetime import datetime

import pytest

from src.content import (
    ContentError, ContentItem, generate_content_items, plan_briefs,
)


class Settings:
    anthropic_api_key = "sk-ant"
    anthropic_model = "claude-sonnet-5"
    brand_name = "NeuroAxis"
    brand_website = "neuroaxis-adhd.com"
    networks = ["twitter", "facebook", "instagram", "gmb"]


def tool_msg(posts):
    block = types.SimpleNamespace(type="tool_use", name="submit_batch",
                                  input={"posts": posts})
    return types.SimpleNamespace(content=[block])


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

        outer = self

        class _Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return outer._responses.pop(0)

        self.messages = _Messages()


def _post(headline="ADHD in adults", body="It can look different.",
          cta="Learn more at neuroaxis-adhd.com", caption="A clean caption.",
          hashtags=None, title="ADHD in adults"):
    return {"title": title, "headline": headline, "body": body, "cta": cta,
            "caption": caption, "hashtags": hashtags or ["#ADHD"]}


NOW = datetime(2026, 9, 12, 9, 0)


def test_plan_briefs_respects_mix_ratio():
    briefs = plan_briefs(10, {"TOFU": 3, "MOFU": 1, "BOFU": 1}, now=NOW)
    stages = [b["funnel_stage"] for b in briefs]
    assert len(briefs) == 10
    assert stages.count("TOFU") == 6
    assert stages.count("MOFU") == 2
    assert stages.count("BOFU") == 2


def test_plan_briefs_rotates_topics_between_runs():
    a = [b["topic"] for b in plan_briefs(3, {"TOFU": 1}, now=datetime(2026, 9, 1))]
    b = [b["topic"] for b in plan_briefs(3, {"TOFU": 1}, now=datetime(2026, 10, 1))]
    assert a != b


def test_generate_returns_parsed_items():
    client = FakeClient([tool_msg([_post(), _post(), _post()])])
    items = generate_content_items(Settings(), 3, mix={"TOFU": 3, "MOFU": 1, "BOFU": 1},
                                   client=client, now=NOW)
    assert len(items) == 3
    assert all(isinstance(i, ContentItem) for i in items)
    assert items[0].platforms == ["twitter", "facebook", "instagram", "gmb"]
    assert items[0].funnel_stage in ("TOFU", "MOFU", "BOFU")


def test_generate_retries_then_drops_noncompliant_item():
    bad = _post(headline="We cure ADHD guaranteed")
    good = _post()
    # first call: item 0 bad, items 1-2 good. retry call: still bad.
    client = FakeClient([
        tool_msg([bad, good, good]),
        tool_msg([_post(headline="Still we cure it")]),
    ])
    items = generate_content_items(Settings(), 3, mix={"TOFU": 3},
                                   client=client, now=NOW)
    assert len(items) == 2
    assert len(client.calls) == 2


def test_generate_keeps_item_when_retry_fixes_it():
    bad = _post(caption="Guaranteed cure")
    client = FakeClient([
        tool_msg([bad, _post(), _post()]),
        tool_msg([_post(caption="Now compliant and kind.")]),
    ])
    items = generate_content_items(Settings(), 3, mix={"TOFU": 3},
                                   client=client, now=NOW)
    assert len(items) == 3


def test_generate_raises_if_model_returns_wrong_count():
    client = FakeClient([tool_msg([_post()])])
    with pytest.raises(ContentError):
        generate_content_items(Settings(), 3, mix={"TOFU": 3}, client=client, now=NOW)


def test_system_prompt_passed_and_tool_forced():
    client = FakeClient([tool_msg([_post()])])
    generate_content_items(Settings(), 1, mix={"TOFU": 1}, client=client, now=NOW)
    call = client.calls[0]
    assert "NeuroAxis" in call["system"]
    assert "CQC" in call["system"]
    assert call["tool_choice"]["name"] == "submit_batch"
