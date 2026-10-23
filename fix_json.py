#!/usr/bin/env python3
"""Fix JSON syntax errors by removing stray closing braces."""
import json
from pathlib import Path

def fix_stray_braces(file_path):
    """Remove stray closing braces in JSON tool_uses array."""
    with open(file_path, 'r') as f:
        content = f.read()

    # Fix pattern: remove extra } before },\n            ],
    fixed = content.replace('}\n              }\n            ]', '}\n            ]')

    with open(file_path, 'w') as f:
        f.write(fixed)

    # Validate it's valid JSON now
    with open(file_path, 'r') as f:
        try:
            json.load(f)
            print(f"[OK] Fixed {file_path.name}")
            return True
        except json.JSONDecodeError as e:
            print(f"[ERROR] Still broken: {e}")
            return False

eval_sets_dir = Path(__file__).parent / "eval-adk" / "eval_sets"
fix_stray_braces(eval_sets_dir / "overwatch_aggregation.evalset.json")
