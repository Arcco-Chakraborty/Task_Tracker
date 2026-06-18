"""Diagnose a real extraction end-to-end with token accounting.

Run on the server:  ./venv/bin/python scripts/extract_diag.py /tmp/roadmap.pdf

Prints: extracted text length, the raw Gemini finishReason + token usage
(prompt / thinking / output), and either the normalized plan summary
(phases + item counts) or the full error. This pins down MAX_TOKENS
truncation vs. a genuine failure.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

import extract
import llm
from config import load_config, load_dotenv

load_dotenv()
cfg = load_config()
path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/roadmap.pdf"

source_type, source_name, text = extract.extract_text(path)
print(f"source={source_type} name={source_name} text_chars={len(text)}")

ai = cfg.get("ai", {})
max_chars = ai.get("max_input_chars", 20000)
doc = extract.clip_document(text or "", max_chars)
prompt = extract.build_prompt(doc, start_date=None, due_date=None)
print(f"clipped_chars={len(doc)} prompt_chars={len(prompt)} "
      f"model={ai.get('model')} max_output_tokens={ai.get('max_output_tokens')} "
      f"thinking_budget={ai.get('thinking_budget')}")

# Make one raw call so we can read usageMetadata + finishReason directly.
keys = llm.load_keys(ai.get("env_path", ".env"))
endpoint = ai.get("endpoint").rstrip("/")
model = ai.get("model")
gen_cfg = {
    "temperature": float(ai.get("temperature", 0.2)),
    "maxOutputTokens": int(ai.get("max_output_tokens", 4096)),
    "responseMimeType": "application/json",
}
if ai.get("thinking_budget") is not None:
    gen_cfg["thinkingConfig"] = {"thinkingBudget": int(ai["thinking_budget"])}
url = f"{endpoint}/models/{model}:generateContent?key={keys[0]}"
resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": gen_cfg}, timeout=120)
data = resp.json()
print("http_status:", resp.status_code)
print("usageMetadata:", json.dumps(data.get("usageMetadata", {})))
cands = data.get("candidates") or [{}]
print("finishReason:", cands[0].get("finishReason"))

# Now run the real pipeline (so normalization is exercised too).
print("\n--- full extract_project ---")
try:
    backend = llm.get_backend(cfg)
    result = extract.extract_project(text, backend, max_input_chars=max_chars)
    phases = result.get("phases", [])
    everyday = result.get("everyday_items", [])
    n_items = sum(len(p.get("items", [])) for p in phases)
    print(f"OK: title={result.get('title')!r}")
    print(f"phases={len(phases)} items={n_items} everyday={len(everyday)}")
    for p in phases:
        print(f"  [{p.get('name')}] {len(p.get('items', []))} items")
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    print("FAILED:", e)
