"""llm.py — Gemini backend with round-robin key rotation.

Ported from Mailbox/llm.py. Differences:
  - keys are loaded from .env / GEMINI_API_KEYS (comma-separated)
  - config is read from cfg["ai"] instead of cfg["summarize"]
"""
from __future__ import annotations

import json
import os
import re
import time

import requests


class LLMError(Exception):
    """Raised when a backend cannot return a parsed JSON object."""


_FENCE = re.compile(r"```(?:json)?\s*|\s*```", re.IGNORECASE)


def parse_json_object(text: str) -> dict:
    """Strip code fences and parse a JSON object. Falls back to the outermost
    {...} slice when the model wrapped JSON in prose. Raises LLMError."""
    cleaned = _FENCE.sub("", text or "").strip()
    try:
        obj = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if 0 <= start < end:
            try:
                obj = json.loads(cleaned[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                raise LLMError(f"non-JSON model output: {e}") from e
        else:
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

    - Asks for application/json output (no fences, valid JSON by contract).
    - Transient failures (429/5xx/network) rotate to the next key; every key
      gets up to two tries (second sweep after a short backoff).
    - Hard failures (safety block, output truncation) raise immediately with
      an actionable message.
    - A JSON parse failure is retried once, then raised."""

    TRANSIENT = (429, 500, 502, 503, 504)

    def __init__(self, cfg: dict):
        s = cfg.get("ai", {})
        self.model = s.get("model", "gemini-2.5-flash-lite")
        self.endpoint = s.get(
            "endpoint", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.temperature = float(s.get("temperature", 0.2))
        self.max_output_tokens = int(s.get("max_output_tokens", 4096))
        self.timeout = int(s.get("timeout_seconds", 60))
        self.retry_backoff = float(s.get("retry_backoff_seconds", 1.5))
        # None = model default (dynamic thinking); 0 disables thinking.
        self.thinking_budget = s.get("thinking_budget")
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
        parse_retries = 1
        attempts = len(self.keys) * 2  # two sweeps over the key ring
        for attempt in range(attempts):
            if attempt == len(self.keys) and self.retry_backoff:
                time.sleep(self.retry_backoff)  # brief pause before sweep 2
            key = self._next_key()
            url = f"{self.endpoint}/models/{self.model}:generateContent?key={key}"
            gen_cfg = {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            }
            if self.thinking_budget is not None:
                gen_cfg["thinkingConfig"] = {
                    "thinkingBudget": int(self.thinking_budget)}
            try:
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": gen_cfg,
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                last = f"request failed: {e}"
                continue
            if resp.status_code in self.TRANSIENT:
                last = (f"rate-limited (429)" if resp.status_code == 429
                        else f"gemini unavailable ({resp.status_code})")
                continue
            if not resp.ok:
                last = f"gemini error ({resp.status_code})"
                continue
            try:
                data = resp.json()
            except ValueError as e:
                last = f"invalid API response: {e}"
                continue
            block = (data.get("promptFeedback") or {}).get("blockReason")
            if block:
                raise LLMError(f"request blocked by Gemini safety ({block})")
            try:
                cand = data["candidates"][0]
                text = cand["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError):
                reason = ""
                if isinstance(data.get("candidates"), list) and data["candidates"]:
                    reason = data["candidates"][0].get("finishReason", "")
                if reason == "MAX_TOKENS":
                    raise LLMError(
                        "output hit the token limit before any text — raise "
                        "ai.max_output_tokens in config.yaml")
                last = f"unexpected response shape ({reason or 'no candidates'})"
                continue
            if cand.get("finishReason") == "MAX_TOKENS":
                raise LLMError(
                    "output was truncated mid-plan (MAX_TOKENS) — raise "
                    "ai.max_output_tokens in config.yaml or shorten the document")
            try:
                return parse_json_object(text)
            except LLMError as e:
                if parse_retries > 0:
                    parse_retries -= 1
                    last = str(e)
                    continue
                raise
        raise LLMError(last)


def get_backend(cfg: dict):
    """Return the configured backend. Only 'gemini' is implemented here."""
    engine = cfg.get("ai", {}).get("engine", "gemini").lower()
    if engine == "gemini":
        return GeminiBackend(cfg)
    raise LLMError(f"unknown ai.engine: {engine}")
