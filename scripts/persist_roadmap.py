"""Run the real upload pipeline on a file and persist it as a project for a
given user — exactly what the web /upload route does. Used to verify the
end-to-end fix with real data.

Usage: ./venv/bin/python scripts/persist_roadmap.py <file> <user_id> [start_date]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import extract
import llm
from config import load_config, load_dotenv

load_dotenv()
cfg = load_config()
path = sys.argv[1]
user_id = int(sys.argv[2])
start_date = sys.argv[3] if len(sys.argv) > 3 else None

conn = db.connect(cfg["app"]["db_path"])
source_type, source_name, text = extract.extract_text(path)
source_name = os.path.basename(path)
backend = llm.get_backend(cfg)
max_chars = cfg["ai"].get("max_input_chars", 20000)
data = extract.extract_project(text, backend, start_date=start_date,
                               due_date=None, max_input_chars=max_chars)
pid = db.create_project_from_extraction(
    conn, data, source_type, source_name, start_date, None, user_id=user_id)

p = db.get_project(conn, pid, user_id)
print(f"CREATED project id={pid} user_id={user_id} title={p['title']!r}")
phases = data.get("phases", [])
n_items = sum(len(ph.get("items", [])) for ph in phases)
print(f"phases={len(phases)} items={n_items} "
      f"everyday={len(data.get('everyday_items', []))}")
for ph in phases:
    items = ph.get("items", [])
    ts = sum(1 for it in items if it.get("time_sensitive"))
    print(f"  [{ph.get('name')}] {len(items)} items ({ts} time-sensitive)")
