#!/usr/bin/env python3
"""Check for JSON syntax errors in evalsets."""
import json
from pathlib import Path

eval_sets_dir = Path(__file__).parent / "eval-adk" / "eval_sets"

for evalset_file in sorted(eval_sets_dir.glob("*.evalset.json")):
    try:
        with open(evalset_file, 'r') as f:
            json.load(f)
        print(f"[OK] {evalset_file.name}")
    except json.JSONDecodeError as e:
        print(f"[ERROR] {evalset_file.name}: {e}")
