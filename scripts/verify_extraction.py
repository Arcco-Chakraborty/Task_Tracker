"""Manual verification harness for the Gemini extraction pipeline.

Run:  python scripts/verify_extraction.py
Calls the real Gemini API with a trap-laden document and scores the result
against expectations (ordering, time-sensitivity, weights, dates, structure).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extract
import llm
from config import load_config

DOC = """\
CS2104 Course Project — Personal Finance Tracker App

Overview
Build a personal finance tracker as a webapp over the next 6 weeks. Work in
pairs. Final demo is on 2026-07-24 in room AC-2 110. The demo counts 30% of
the grade, the report 20%, weekly checkpoints 50%.

Phase guidance
First understand the dataset format (CSV bank exports, see resources). Then
design the schema, build the import pipeline, add charts, and polish the UI.
Write the final report at the end (LaTeX, 8 pages max, template on portal).

You should watch Prof. Mehta's 4-hour recorded lecture on double-entry
bookkeeping before designing the schema. It is dense — budget a full day.

Ongoing expectations
- Push code at least once a day.
- Review your partner's PRs every week.
- Keep a running work log (update it daily).

Useful links
- Dataset spec: https://example.edu/cs2104/dataset-spec
- Report template: https://example.edu/cs2104/report-template

Contact: Prof. Mehta <mehta@example.edu>, TA hours Tue/Thu 5pm, lab B-204.

IMPORTANT — Time-sensitive actions (do all of these in week 1):
* Register your team on the course portal (closes 2026-06-19!)
* Email the TA your GitHub usernames to get repo access
* Book a demo slot — slots go fast
* Order the Raspberry Pi kit from the lab store if you want the hardware bonus
"""


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return 1 if ok else 0


def main():
    cfg = load_config()
    print(f"model: {cfg['ai'].get('model')}")
    backend = llm.get_backend(cfg)
    t0 = time.time()
    data = extract.extract_project(DOC, backend, start_date="2026-06-15",
                                   due_date="2026-07-24")
    elapsed = time.time() - t0
    print(f"extraction took {elapsed:.1f}s\n")
    print(json.dumps(data, indent=2)[:4500])
    print("\n--- checks ---")

    items = [(pi, ii, it) for pi, ph in enumerate(data["phases"])
             for ii, it in enumerate(ph["items"])]
    flat = [it for _, _, it in items]
    titles = [it["title"].lower() for it in flat]
    score = 0
    total = 0

    def find(*words):
        for idx, t in enumerate(titles):
            if all(w in t for w in words):
                return idx
        return None

    # 1. the buried time-sensitive list is expanded into individual items
    reg, ta, slot, kit = (find("register"), find("github") or find("ta"),
                          find("slot") or find("book"), find("kit") or find("order"))
    total += 1; score += check("time-sensitive list expanded into >=4 items",
                               None not in (reg, ta, slot, kit))
    # 2. they sit in the FIRST half of the plan despite being last in the doc
    if None not in (reg, ta, slot, kit):
        early = all(i < len(flat) / 2 for i in (reg, ta, slot, kit))
        total += 1; score += check("week-1 actions placed early", early,
                                   f"positions {reg},{ta},{slot},{kit} of {len(flat)}")
    # 3. flagged time_sensitive
    if reg is not None:
        total += 1; score += check("registration flagged time_sensitive",
                                   flat[reg]["time_sensitive"])
    # 4. registration deadline captured (2026-06-19)
    if reg is not None:
        total += 1; score += check("registration deadline = 2026-06-19",
                                   flat[reg]["deadline"] == "2026-06-19",
                                   str(flat[reg]["deadline"]))
    # 5. weights vary (lecture should be heavy, emailing TA trivial)
    weights = {it["weight"] for it in flat}
    total += 1; score += check("weights use a range (>=3 distinct)",
                               len(weights) >= 3, str(sorted(weights)))
    lec = find("lecture") or find("bookkeeping")
    if lec is not None and ta is not None:
        total += 1; score += check("lecture weight > email-TA weight",
                                   flat[lec]["weight"] > flat[ta]["weight"],
                                   f"{flat[lec]['weight']} vs {flat[ta]['weight']}")
    # 6. no week-1 item got a 7-day duration (the classic misread)
    week1 = [i for i in (reg, ta, slot, kit) if i is not None]
    total += 1; score += check(
        "no week-1 action mistaken for a 7-day task",
        all((flat[i]["duration_days"] or 0) < 7 for i in week1))
    # 7. everyday items captured (daily pushes, work log; weekly PR review)
    ev = [e["title"].lower() for e in data["everyday_items"]]
    total += 1; score += check("recurring work in everyday_items (>=2)",
                               len(ev) >= 2, "; ".join(ev))
    # 8. resources with real URLs only
    urls = [r["url"] for r in data["resources"] if r.get("url")]
    for ph in data["phases"]:
        for it in ph["items"]:
            urls += [r["url"] for r in it.get("resources", []) if r.get("url")]
    total += 1; score += check("dataset-spec URL preserved",
                               any("dataset-spec" in (u or "") for u in urls))
    total += 1; score += check("no hallucinated URLs",
                               all("example.edu" in u for u in urls),
                               "; ".join(urls))
    # 9. info preserved (grading split / contact / room)
    blob = json.dumps(data["info_cards"]).lower()
    total += 1; score += check("grading split in info cards",
                               "30%" in blob or "50%" in blob)
    total += 1; score += check("contact/TA info preserved",
                               "mehta" in blob or "b-204" in blob or "ta" in blob)
    # 10. final demo date
    total += 1; score += check("suggested_due or a deadline hits 2026-07-24",
                               data["suggested_due"] == "2026-07-24"
                               or any(it["deadline"] == "2026-07-24" for it in flat))
    # 11. report written at the END
    rep = find("report")
    if rep is not None:
        total += 1; score += check("report near the end",
                                   rep > len(flat) * 0.6,
                                   f"pos {rep}/{len(flat)}")

    print(f"\nSCORE: {score}/{total}")


if __name__ == "__main__":
    main()
