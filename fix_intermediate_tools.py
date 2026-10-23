#!/usr/bin/env python3
"""
Update intermediate_data.tool_uses to include full tool chains.
Maps expected_tools metadata to intermediate_data structure.
"""
import json
from pathlib import Path

def fix_evalset_intermediate_tools(evalset_path):
    """Update tool_uses in intermediate_data to match expected_tools."""
    with open(evalset_path, 'r') as f:
        data = json.load(f)

    updated_count = 0

    for case in data.get("eval_cases", []):
        metadata = case.get("_metadata", {})
        expected_tools = metadata.get("expected_tools", [])

        # Get conversation and intermediate_data
        conversation = case.get("conversation", [])
        if not conversation:
            continue

        invocation = conversation[0]
        intermediate_data = invocation.get("intermediate_data", {})
        tool_uses = intermediate_data.get("tool_uses", [])

        # Build new tool_uses array based on expected_tools
        # expected_tools is like: [["transfer_to_agent"], ["get_incident"]]
        # We need to convert to tool_uses format

        new_tool_uses = []

        for tool_list in expected_tools:
            if not tool_list:
                continue

            tool_name = tool_list[0]  # Get tool name from list

            # Determine appropriate args based on tool name
            if tool_name == "transfer_to_agent":
                # Find incidents_agent, logs_agent, or metrics_agent from metadata
                agents = metadata.get("expected_agents", [])
                agent_name = agents[0] if agents else "incidents_agent"
                tool_use = {
                    "name": "transfer_to_agent",
                    "args": {"agent_name": agent_name}
                }
            elif tool_name == "get_incident":
                # Extract incident ID from question
                user_content = invocation.get("user_content", {})
                parts = user_content.get("parts", [])
                question = parts[0].get("text", "") if parts else ""

                # Simple heuristic: look for INC#### in question
                import re
                match = re.search(r'(INC\d+)', question)
                incident_id = match.group(1) if match else "INC0001"

                tool_use = {
                    "name": "get_incident",
                    "args": {"incident_id": incident_id}
                }
            elif tool_name == "count_incidents":
                tool_use = {
                    "name": "count_incidents",
                    "args": {}
                }
            elif tool_name == "list_incidents":
                tool_use = {
                    "name": "list_incidents",
                    "args": {}
                }
            elif tool_name == "search_logs":
                tool_use = {
                    "name": "search_logs",
                    "args": {}
                }
            elif tool_name == "count_logs":
                tool_use = {
                    "name": "count_logs",
                    "args": {}
                }
            elif tool_name == "error_counts_by_service":
                tool_use = {
                    "name": "error_counts_by_service",
                    "args": {}
                }
            elif tool_name == "get_metrics":
                tool_use = {
                    "name": "get_metrics",
                    "args": {}
                }
            elif tool_name == "list_problems":
                tool_use = {
                    "name": "list_problems",
                    "args": {}
                }
            elif tool_name == "count_incidents_by_service":
                tool_use = {
                    "name": "count_incidents_by_service",
                    "args": {}
                }
            elif tool_name == "get_related_incidents":
                tool_use = {
                    "name": "get_related_incidents",
                    "args": {}
                }
            else:
                continue

            new_tool_uses.append(tool_use)

        # Only update if different
        old_count = len(tool_uses)
        new_count = len(new_tool_uses)

        if old_count != new_count:
            intermediate_data["tool_uses"] = new_tool_uses
            updated_count += 1
            eval_id = case.get("eval_id", "unknown")
            print(f"  {eval_id}: Updated from {old_count} to {new_count} tool(s)")

    # Write back
    with open(evalset_path, 'w') as f:
        json.dump(data, f, indent=2)

    return updated_count

def main():
    """Fix all evalsets."""
    eval_sets_dir = Path(__file__).parent / "eval-adk" / "eval_sets"
    evalset_files = sorted(eval_sets_dir.glob("*.evalset.json"))

    total_updated = 0
    for evalset_file in evalset_files:
        print(f"\n[*] Updating {evalset_file.name}...")
        count = fix_evalset_intermediate_tools(evalset_file)
        total_updated += count
        print(f"  [OK] Updated {count} cases")

    print(f"\n[DONE] Updated {total_updated} total cases")

if __name__ == "__main__":
    main()
