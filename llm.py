"""llm.py — Gemini backend with round-robin key rotation.

Ported from Mailbox/llm.py. Differences:
  - keys are loaded from .env / GEMINI_API_KEYS (comma-separated)
  - config is read from cfg["ai"] instead of cfg["summarize"]
"""
from __future__ import annotations

import json
import os
import re

import requests


class LLMError(Exception):
    """Raised when a backend cannot return a parsed JSON object."""


_FENCE = re.compile(r"```(?:json)?\s*|\s*```", re.IGNORECASE)


def parse_json_object(text: str) -> dict:
    """Strip code fences and parse a JSON object. Raises LLMError on failure."""
    cleaned = _FENCE.sub("", text or "").strip()
    try:
        obj = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        raise LLMError(f"non-JSON model output: {e}") from e
    if not isinstance(obj, dict):
        raise LLMError("model output was not a JSON object")
    return obj


def load_keys(env_path: str = ".env", var: str = "GEMINI_API_KEYS") -> list[str]:
    """Read API keys from the GEMINI_API_KEYS entry of a .env file (comma-
    separated). The .env is loaded into os.environ first WITHOUT overriding
    already-set vars (so a real environment variable wins), then the variable
    is comma-split. Returns [] if unset."""
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    return [k.strip() for k in os.environ.get(var, "").split(",") if k.strip()]


class GeminiBackend:
    """Gemini generateContent with round-robin key rotation.

    On 429 / non-OK, advances to the next key; tries each key at most once per
    call. A JSON parse failure does NOT rotate (model-output issue, not quota)."""

    def __init__(self, cfg: dict):
        s = cfg.get("ai", {})
        self.model = s.get("model", "gemini-2.5-flash-lite")
        self.endpoint = s.get(
            "endpoint", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.temperature = float(s.get("temperature", 0.2))
        self.max_output_tokens = int(s.get("max_output_tokens", 4096))
        self.timeout = int(s.get("timeout_seconds", 60))
        self.keys = load_keys(s.get("env_path", ".env"))
        self._i = 0

    def _next_key(self) -> str:
        key = self.keys[self._i % len(self.keys)]
        self._i += 1
        return key

    def complete(self, prompt: str) -> dict:
        if not self.keys:
            raise LLMError("no keys configured (GEMINI_API_KEYS missing in .env)")
        last = "all keys exhausted"
        for _ in range(len(self.keys)):
            key = self._next_key()
            url = f"{self.endpoint}/models/{self.model}:generateContent?key={key}"
            try:
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": self.temperature,
                            "maxOutputTokens": self.max_output_tokens,
                        },
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                last = f"request failed: {e}"
                continue
            if resp.status_code == 429:
                last = "rate-limited (429)"
                continue
            if not resp.ok:
                last = f"gemini error ({resp.status_code})"
                continue
            try:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            except (ValueError, KeyError, IndexError) as e:
                last = f"unexpected response shape: {e}"
                continue
            return parse_json_object(text)  # LLMError propagates (no rotate)
        raise LLMError(last)


def get_backend(cfg: dict):
    """Return the configured backend. Only 'gemini' is implemented here."""
    engine = cfg.get("ai", {}).get("engine", "gemini").lower()
    if engine == "gemini":
        return GeminiBackend(cfg)
    raise LLMError(f"unknown ai.engine: {engine}")
