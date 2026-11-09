#!/usr/bin/env python
"""Re-check the golden sets against the database.

    python eval-adk\\golden_core\\verify_golden.py

For each case in overwatch_core and overwatch_stress it runs the case's
ground_truth_sql and shows the result. It checks the result contains the
case's `ground_truth_expect` values (or, for plain answer cases, its
must_include facts). It prints query results only, never connection details.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "mcp_servers"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
from db import query  # noqa: E402

problems = 0
for name in ("overwatch_core.evalset.json", "overwatch_stress.evalset.json"):
    path = HERE / name
    if not path.exists():
        continue
    doc = json.loads(path.read_text(encoding="utf-8"))
    print(f"\n===== {doc['eval_set_id']} =====")
    for case in doc["eval_cases"]:
        m = case["_metadata"]
        print(f"\n{case['eval_id']}  [{m['category']}]  expected behaviour: {m['expected_behaviour']}")
        sql = m.get("ground_truth_sql")
        if not sql:
            print("  db      : (no query: nothing to look up for this case)")
            continue
        try:
            rows = query(sql)
        except Exception as e:  # show the error, keep going
            problems += 1
            print(f"  db      : ERROR {type(e).__name__}: {e}")
            continue
        shown = json.dumps(rows, ensure_ascii=False, default=str)
        print(f"  db      : {shown[:400]}")

        expect = m.get("ground_truth_expect")
        if expect is None and m["expected_behaviour"] == "answer":
            expect = m["must_include"]
        if not expect:
            continue
        print(f"  expects : {expect}")
        groups = [e if isinstance(e, list) else [e] for e in expect]
        missing = [g for g in groups if not any(str(o).lower() in shown.lower() for o in g)]
        if missing:
            problems += 1
            print(f"  CHECK   : not in the db result: {missing}")
        else:
            print("  ok")

print(f"\n{problems} case(s) need a look." if problems else "\nAll checked cases match the database.")
