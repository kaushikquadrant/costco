#!/usr/bin/env python3
"""Fix remaining eval sets to expect transfer_to_agent pattern."""
import json
from pathlib import Path

eval_dir = Path("eval-adk/eval_sets")

# Files that still need fixing
UPDATES = {
    "overwatch_log_search.evalset.json": "logs_agent",
    "overwatch_log_search.evalset.json": "logs_agent",
    "overwatch_metrics.evalset.json": "metrics_agent",
    "overwatch_problems.evalset.json": "metrics_agent",
}

for filename, agent_name in UPDATES.items():
    filepath = eval_dir / filename
    if not filepath.exists():
        print(f"Skipping {filename}")
        continue

    print(f"Processing {filename}...")

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    updated = 0
    for eval_case in data.get("eval_cases", []):
        # Fix tool_uses
        for conversation in eval_case.get("conversation", []):
            inter_data = conversation.get("intermediate_data", {})
            for tool in inter_data.get("tool_uses", []):
                if tool.get("name") == "transfer_to_agent":
                    old_args = tool.get("args", {})
                    if old_args != {"agent_name": agent_name}:
                        tool["args"] = {"agent_name": agent_name}
                        updated += 1

        # Fix expected_tools
        metadata = eval_case.get("_metadata", {})
        if "expected_tools" in metadata:
            if metadata["expected_tools"][0] != ["transfer_to_agent"]:
                metadata["expected_tools"] = [["transfer_to_agent"]]

    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  Updated {updated} tool args to agent_name: {agent_name}")

print("\n✓ All eval sets processed!")
