"""Probe each Gemini key with the production generationConfig and print the
exact status + error body. Reveals whether a 400 is a bad key, a quota/rate
limit, or a rejected thinkingConfig.  Run on the server.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

import llm
from config import load_config, load_dotenv

load_dotenv()
ai = load_config()["ai"]
keys = llm.load_keys(ai.get("env_path", ".env"))
endpoint = ai["endpoint"].rstrip("/")
model = ai["model"]
gc = {"temperature": 0.2, "maxOutputTokens": 32768,
      "responseMimeType": "application/json",
      "thinkingConfig": {"thinkingBudget": 8192}}
body = {"contents": [{"parts": [{"text": "Return JSON: {\"ok\": true}"}]}],
        "generationConfig": gc}

print(f"model={model} num_keys={len(keys)}")
for i, k in enumerate(keys):
    url = f"{endpoint}/models/{model}:generateContent?key={k}"
    try:
        r = requests.post(url, json=body, timeout=60)
        print(f"key[{i}] ...{k[-6:]}: status={r.status_code} {r.text[:300]}")
    except Exception as e:  # noqa: BLE001
        print(f"key[{i}] ...{k[-6:]}: EXC {e}")
