import pytest
import llm


def test_parse_json_object_strips_fences():
    assert llm.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_object_rejects_non_json():
    with pytest.raises(llm.LLMError):
        llm.parse_json_object("not json")


def test_parse_json_object_rejects_non_object():
    with pytest.raises(llm.LLMError):
        llm.parse_json_object("[1, 2, 3]")


def test_load_keys_reads_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    env = tmp_path / ".env"
    env.write_text('GEMINI_API_KEYS=a, b ,c\n', encoding="utf-8")
    assert llm.load_keys(str(env)) == ["a", "b", "c"]


def test_load_keys_missing_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    assert llm.load_keys(str(tmp_path / "none.env")) == []


def test_load_keys_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "x,y")
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEYS=a,b,c\n", encoding="utf-8")
    assert llm.load_keys(str(env)) == ["x", "y"]  # real env var not overridden


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload or {}

    def json(self):
        return self._payload


def _payload(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEYS=k1,k2\n", encoding="utf-8")
    return {"ai": {"engine": "gemini", "model": "m", "env_path": str(env)}}


def test_gemini_rotates_past_429(monkeypatch, tmp_path):
    backend = llm.GeminiBackend(_cfg(tmp_path, monkeypatch))
    seq = [_Resp(429), _Resp(200, _payload('{"ok": true}'))]
    used = []
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, **kw: (used.append(url), seq.pop(0))[1])
    assert backend.complete("p") == {"ok": True}
    assert len(used) == 2


def test_gemini_all_keys_exhausted_raises(monkeypatch, tmp_path):
    backend = llm.GeminiBackend(_cfg(tmp_path, monkeypatch))
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: _Resp(429))
    with pytest.raises(llm.LLMError):
        backend.complete("p")


def test_parse_json_object_slices_prose_wrapper():
    out = llm.parse_json_object('Here is the plan:\n{"a": 1}\nHope it helps!')
    assert out == {"a": 1}


def test_gemini_requests_json_mime(monkeypatch, tmp_path):
    backend = llm.GeminiBackend(_cfg(tmp_path, monkeypatch))
    sent = {}
    def fake_post(url, **kw):
        sent.update(kw["json"])
        return _Resp(200, _payload('{"ok": true}'))
    monkeypatch.setattr(llm.requests, "post", fake_post)
    backend.complete("p")
    assert sent["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_sends_thinking_budget_when_set(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path, monkeypatch)
    cfg["ai"]["thinking_budget"] = 8192
    backend = llm.GeminiBackend(cfg)
    sent = {}

    def fake_post(url, **kw):
        sent.update(kw["json"])
        return _Resp(200, _payload('{"ok": true}'))
    monkeypatch.setattr(llm.requests, "post", fake_post)
    backend.complete("p")
    # A bounded thinking budget keeps thinking tokens from devouring the
    # maxOutputTokens budget and truncating the plan JSON (MAX_TOKENS).
    assert sent["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 8192


def test_gemini_omits_thinking_config_when_unset(monkeypatch, tmp_path):
    backend = llm.GeminiBackend(_cfg(tmp_path, monkeypatch))  # no thinking_budget
    sent = {}

    def fake_post(url, **kw):
        sent.update(kw["json"])
        return _Resp(200, _payload('{"ok": true}'))
    monkeypatch.setattr(llm.requests, "post", fake_post)
    backend.complete("p")
    assert "thinkingConfig" not in sent["generationConfig"]


def test_gemini_second_sweep_recovers(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path, monkeypatch)
    cfg["ai"]["retry_backoff_seconds"] = 0  # keep the test fast
    backend = llm.GeminiBackend(cfg)
    # both keys 503 on sweep 1, first key works on sweep 2
    seq = [_Resp(503), _Resp(503), _Resp(200, _payload('{"ok": true}'))]
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: seq.pop(0))
    assert backend.complete("p") == {"ok": True}


def test_gemini_max_tokens_raises_actionable(monkeypatch, tmp_path):
    backend = llm.GeminiBackend(_cfg(tmp_path, monkeypatch))
    payload = {"candidates": [{"content": {"parts": [{"text": '{"x":'}]},
                               "finishReason": "MAX_TOKENS"}]}
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, **kw: _Resp(200, payload))
    with pytest.raises(llm.LLMError, match="max_output_tokens"):
        backend.complete("p")


def test_gemini_safety_block_raises(monkeypatch, tmp_path):
    backend = llm.GeminiBackend(_cfg(tmp_path, monkeypatch))
    payload = {"promptFeedback": {"blockReason": "SAFETY"}}
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, **kw: _Resp(200, payload))
    with pytest.raises(llm.LLMError, match="SAFETY"):
        backend.complete("p")


def test_gemini_parse_failure_retries_once(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path, monkeypatch)
    cfg["ai"]["retry_backoff_seconds"] = 0
    backend = llm.GeminiBackend(cfg)
    seq = [_Resp(200, _payload("garbage")),
           _Resp(200, _payload('{"ok": true}'))]
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: seq.pop(0))
    assert backend.complete("p") == {"ok": True}
