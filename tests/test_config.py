import config


def test_load_config_reads_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("app:\n  db_path: x.db\nai:\n  model: m\n", encoding="utf-8")
    cfg = config.load_config(str(p))
    assert cfg["app"]["db_path"] == "x.db"
    assert cfg["ai"]["model"] == "m"


def test_load_config_missing_returns_empty(tmp_path):
    cfg = config.load_config(str(tmp_path / "nope.yaml"))
    assert cfg == {}
