"""Print a project's phases/items for a quality eyeball. Usage: inspect_project.py <pid>"""
import sqlite3
import sys

pid = int(sys.argv[1]) if len(sys.argv) > 1 else 6
c = sqlite3.connect("tasktracker.db")
c.row_factory = sqlite3.Row

p = c.execute("SELECT title, summary, start_date, due_date FROM projects WHERE id=?",
              (pid,)).fetchone()
print("TITLE:", p["title"])
print("SUMMARY:", p["summary"])
print("START:", p["start_date"], "DUE:", p["due_date"])
print()
for ph in c.execute("SELECT id, name FROM phases WHERE project_id=? ORDER BY position",
                    (pid,)):
    print("==", ph["name"], "==")
    for it in c.execute(
            "SELECT title, deadline, duration_days, weight, time_sensitive "
            "FROM items WHERE phase_id=? ORDER BY position LIMIT 7", (ph["id"],)):
        d = dict(it)
        print(f"   - {d['title'][:56]:56} due={d['deadline']} "
              f"w={d['weight']} dur={d['duration_days']} ts={d['time_sensitive']}")
    print()
print("EVERYDAY:")
for e in c.execute("SELECT title, cadence FROM everyday_items WHERE project_id=?", (pid,)):
    print("   -", e["title"], "|", e["cadence"])
