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


def test_normalize_captures_time_sensitive_and_floats_it_first():
    raw = {"phases": [{"name": "P", "items": [
        {"title": "normal task"},
        {"title": "register now", "time_sensitive": True},
        {"title": "also normal"},
    ]}]}
    items = extract.normalize_extraction(raw)["phases"][0]["items"]
    # time-sensitive item floated to the front of the phase
    assert items[0]["title"] == "register now"
    assert items[0]["time_sensitive"] is True
    assert items[1]["time_sensitive"] is False


def test_normalize_time_sensitive_defaults_false():
    raw = {"phases": [{"name": "P", "items": [{"title": "x"}]}]}
    assert extract.normalize_extraction(raw)["phases"][0]["items"][0]["time_sensitive"] is False


def test_clip_document_keeps_head_and_tail():
    doc = "HEAD " + ("x" * 30000) + " TAIL-DEADLINE-LIST"
    clipped = extract.clip_document(doc, 1000)
    assert len(clipped) < 1100
    assert clipped.startswith("HEAD")
    assert clipped.endswith("TAIL-DEADLINE-LIST")
    assert "omitted for length" in clipped


def test_normalize_drops_empty_phases():
    out = extract.normalize_extraction({
        "phases": [{"name": "Empty", "items": []},
                   {"name": "Real", "items": [{"title": "t"}]}]})
    assert [p["name"] for p in out["phases"]] == ["Real"]


def test_normalize_accepts_iso_datetime_deadline():
    out = extract.normalize_extraction({
        "phases": [{"name": "P", "items": [
            {"title": "t", "deadline": "2026-06-19T00:00:00Z"}]}]})
    assert out["phases"][0]["items"][0]["deadline"] == "2026-06-19"


def test_normalize_caps_duration():
    out = extract.normalize_extraction({
        "phases": [{"name": "P", "items": [
            {"title": "t", "duration_days": 5000}]}]})
    assert out["phases"][0]["items"][0]["duration_days"] == 90


def test_normalize_dedupes_toplevel_resources_attached_to_items():
    out = extract.normalize_extraction({
        "phases": [{"name": "P", "items": [
            {"title": "t", "resources": [
                {"title": "Spec", "url": "https://e.x/spec"}]}]}],
        "resources": [
            {"title": "Spec", "url": "https://e.x/spec"},        # dup of item's
            {"title": "Other", "url": "https://e.x/other"},
            {"title": "Other", "url": "https://e.x/other"},      # self-dup
        ]})
    urls = [r["url"] for r in out["resources"]]
    assert urls == ["https://e.x/other"]


def test_normalize_dedupes_everyday_by_title():
    out = extract.normalize_extraction({
        "everyday_items": [{"title": "Push code"}, {"title": "push CODE"},
                           {"title": "Review PRs"}]})
    assert [e["title"] for e in out["everyday_items"]] == ["Push code",
                                                           "Review PRs"]
