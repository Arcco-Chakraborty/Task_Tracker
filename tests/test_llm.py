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
