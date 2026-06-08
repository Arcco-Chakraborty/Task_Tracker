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
