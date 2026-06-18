import os

import config

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_config_yaml_leaves_room_for_the_plan_json():
    """Regression guard for the MAX_TOKENS truncation bug: gemini-2.5-flash is
    a thinking model whose thinking tokens count against maxOutputTokens, so a
    large plan's JSON got truncated mid-output. thinking_budget must be bounded
    AND the output ceiling high enough that the JSON still fits afterwards."""
    cfg = config.load_config(os.path.join(_REPO, "config.yaml"))
    ai = cfg["ai"]
    tb = ai.get("thinking_budget")
    assert tb is not None, "thinking_budget must be set (bounded), not dynamic"
    assert int(ai["max_output_tokens"]) - int(tb) >= 20000, (
        "need >=20k output tokens left for the plan JSON after thinking")


def test_load_config_reads_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("app:\n  db_path: x.db\nai:\n  model: m\n", encoding="utf-8")
    cfg = config.load_config(str(p))
    assert cfg["app"]["db_path"] == "x.db"
    assert cfg["ai"]["model"] == "m"


def test_load_config_missing_returns_empty(tmp_path):
    cfg = config.load_config(str(tmp_path / "nope.yaml"))
    assert cfg == {}
