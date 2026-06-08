import extract


def test_normalize_drops_items_without_title():
    raw = {"title": "T", "summary": "S", "phases": [
        {"name": "P", "items": [
            {"title": "keep", "description": "d", "deadline": "2026-06-10",
             "duration_days": 2},
            {"title": "", "description": "drop me"},
        ]},
    ]}
    out = extract.normalize_extraction(raw)
    items = out["phases"][0]["items"]
    assert len(items) == 1
    assert items[0]["title"] == "keep"


def test_normalize_coerces_and_clamps():
    raw = {"phases": [{"name": "P", "items": [
        {"title": "x", "duration_days": "5"},
        {"title": "y", "duration_days": -3},
        {"title": "z", "deadline": "not-a-date"},
    ]}]}
    items = extract.normalize_extraction(raw)["phases"][0]["items"]
    assert items[0]["duration_days"] == 5
    assert items[1]["duration_days"] is None   # negative -> None
    assert items[2]["deadline"] is None        # invalid date -> None


def test_normalize_defaults_title_and_phases():
    out = extract.normalize_extraction({})
    assert out["title"] == "Untitled"
    assert out["phases"] == []
    assert out["suggested_start"] is None
    assert out["info_cards"] == []
    assert out["everyday_items"] == []
    assert out["resources"] == []


def test_normalize_validates_suggested_dates():
    out = extract.normalize_extraction(
        {"suggested_start": "2026-06-09", "suggested_due": "bad"})
    assert out["suggested_start"] == "2026-06-09"
    assert out["suggested_due"] is None


def test_extract_text_reads_markdown(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text("# Title\nbody", encoding="utf-8")
    kind, name, text = extract.extract_text(str(p))
    assert kind == "md"
    assert "body" in text


def test_extract_project_uses_backend():
    class StubBackend:
        def complete(self, prompt):
            return {"title": "T", "summary": "S", "phases": [
                {"name": "P", "items": [{"title": "i", "duration_days": 1}]}]}

    out = extract.extract_project("some doc text", StubBackend(),
                                  max_input_chars=1000)
    assert out["title"] == "T"
    assert out["phases"][0]["items"][0]["title"] == "i"


def test_normalize_preserves_info_everyday_and_resources():
    raw = {
        "info_cards": [{"title": "Constraint", "body": "Use portal A"}],
        "everyday_items": [
            {"title": "Check blocker channel", "description": "AM sweep",
             "cadence": "daily"},
        ],
        "resources": [
            {"title": "Runbook", "url": "https://example.test",
             "note": "Ops notes", "related_item_title": "Deploy"},
        ],
        "phases": [{"name": "Ship", "items": [
            {"title": "Deploy", "resources": [
                {"title": "Checklist", "note": "Release steps"},
                "bad shape",
            ]},
        ]}],
    }
    out = extract.normalize_extraction(raw)
    assert out["info_cards"][0]["body"] == "Use portal A"
    assert out["everyday_items"][0]["cadence"] == "daily"
    assert out["resources"][0]["related_item_title"] == "Deploy"
    item_resources = out["phases"][0]["items"][0]["resources"]
    assert item_resources == [{
        "title": "Checklist", "url": None, "note": "Release steps"}]


def test_normalize_clamps_weight():
    raw = {"phases": [{"name": "P", "items": [
        {"title": "a", "weight": 9},
        {"title": "b", "weight": 0},
        {"title": "c"},
        {"title": "d", "weight": "4"},
    ]}]}
    items = extract.normalize_extraction(raw)["phases"][0]["items"]
    assert [i["weight"] for i in items] == [5, 1, 3, 4]
