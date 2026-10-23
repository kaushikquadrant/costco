#!/usr/bin/env python3
"""
Fix evalsets to include sub-agent tool calls for multi-agent evaluation.
Maps questions to expected tools based on agent instructions.
"""
import json
from pathlib import Path

# Mapping of question keywords to tools for each agent
INCIDENTS_AGENT_TOOLS = {
    "how many": ["count_incidents"],
    "which service has the most": ["count_incidents_by_service"],
    "waiting the longest": ["list_incidents"],
    "root cause": ["get_incident"],
    "status": ["get_incident"],
    "priority": ["get_incident"],
    "summary": ["get_incident"],
    "opened": ["get_incident"],
    "resolved": ["get_incident"],
    "change": ["get_incident"],
    "team": ["get_incident"],
    "owner": ["get_incident"],
    "reopened": ["get_incident"],
    "related": ["get_related_incidents"],
    "duplicate": ["get_related_incidents"],
}

LOGS_AGENT_TOOLS = {
    "how many logs": ["count_logs"],
    "how many error": ["error_counts_by_service"],
    "which service has the most error": ["error_counts_by_service"],
    "search": ["search_logs"],
    "log": ["search_logs"],
    "error": ["search_logs"],
    "message": ["search_logs"],
}

METRICS_AGENT_TOOLS = {
    "cpu": ["get_metrics"],
    "memory": ["get_metrics"],
    "latency": ["get_metrics"],
    "error rate": ["get_metrics"],
    "requests": ["get_metrics"],
    "p95": ["get_metrics"],
    "performance": ["get_metrics"],
    "problem": ["list_problems"],
    "monitoring": ["list_problems"],
}

def get_expected_tool_for_agent(question, agent_name):
    """Determine expected tool based on agent and question."""
    question_lower = question.lower()

    if agent_name == "incidents_agent":
        tools = INCIDENTS_AGENT_TOOLS
    elif agent_name == "logs_agent":
        tools = LOGS_AGENT_TOOLS
    elif agent_name == "metrics_agent":
        tools = METRICS_AGENT_TOOLS
    else:
        return None

    # Find matching keywords
    for keyword, tool_list in tools.items():
        if keyword in question_lower:
            return tool_list[0]  # Return first matching tool

    # Default fallback
    if agent_name == "incidents_agent":
        return "get_incident"
    elif agent_name == "logs_agent":
        return "search_logs"
    elif agent_name == "metrics_agent":
        return "get_metrics"

    return None

def fix_evalset(evalset_path):
    """Update an evalset with proper multi-agent tools."""
    with open(evalset_path, 'r') as f:
        data = json.load(f)

    updated_count = 0

    for case in data.get("eval_cases", []):
        metadata = case.get("_metadata", {})
        expected_agents = metadata.get("expected_agents", [])

        # Get the question
        conversation = case.get("conversation", [])
        if conversation:
            invocation = conversation[0]
            user_content = invocation.get("user_content", {})
            parts = user_content.get("parts", [])
            if parts:
                question = parts[0].get("text", "")
            else:
                question = ""
        else:
            question = ""

        # Build new expected_tools list: [transfer_to_agent, then sub-agent tools]
        new_expected_tools = [["transfer_to_agent"]]

        for agent in expected_agents:
            tool = get_expected_tool_for_agent(question, agent)
            if tool:
                new_expected_tools.append([tool])

        old_tools = metadata.get("expected_tools", [])
        metadata["expected_tools"] = new_expected_tools

        if old_tools != new_expected_tools:
            updated_count += 1
            eval_id = case.get("eval_id", "unknown")
            print(f"  {eval_id}: {question[:60]}...")
            print(f"    Old: {old_tools}")
            print(f"    New: {new_expected_tools}")

    # Write back
    with open(evalset_path, 'w') as f:
        json.dump(data, f, indent=2)

    return updated_count

def main():
    """Fix all evalsets in the eval_sets directory."""
    eval_sets_dir = Path(__file__).parent / "eval-adk" / "eval_sets"

    evalset_files = sorted(eval_sets_dir.glob("*.evalset.json"))

    total_updated = 0
    for evalset_file in evalset_files:
        print(f"\n[*] Fixing {evalset_file.name}...")
        count = fix_evalset(evalset_file)
        total_updated += count
        print(f"  [OK] Updated {count} cases")

    print(f"\n[DONE] All done! Updated {total_updated} total cases across {len(evalset_files)} evalsets")

if __name__ == "__main__":
    main()
