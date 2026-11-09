"""Where did the time and tokens go? Per-case breakdown from the traced spans (Day 4).

Reads the local span copy written during a traced run (runs/spans/spans_<run_id>.jsonl,
see telemetry.py) for the run behind a results CSV, and writes next to that CSV:
  <name>_span_summary.csv   one row per case: time split (model / tools / other), tokens, calls
  <name>_spans.csv          one row per span, flattened: the table the dashboard waterfall uses

Usage:  python eval-adk/span_summary.py eval-adk/runs/quick_results_<run_id>.csv
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SPANS_DIR = Path(__file__).resolve().parent / "runs" / "spans"


def kind_of(name: str) -> str:
    for prefix, kind in (("eval_case", "eval_case"), ("invocation", "invocation"), ("invoke_agent", "agent"),
                         ("call_llm", "llm_step"), ("generate_content", "model_call"), ("execute_tool", "tool")):
        if name.startswith(prefix):
            return kind
    return "other"


def error_kind(span: dict) -> str:
    """Sort a failed span into the reliability buckets the dashboard counts."""
    text = f"{span.get('error_type', '')} {span.get('exception', '')}".lower()
    if "429" in text or "resource_exhausted" in text or "rate limit" in text or "quota" in text:
        return "rate_limit"
    if "timeout" in text or "timed out" in text or "deadline" in text:
        return "timeout"
    if span["name"].startswith("execute_tool"):
        return "tool_error"
    if span["name"].startswith(("generate_content", "call_llm")):
        return "model_error"
    return "other_error"


def load_spans(run_id: str) -> list[dict]:
    path = SPANS_DIR / f"spans_{run_id}.jsonl"
    if not path.exists():
        sys.exit(f"No span file for run {run_id}: {path}\nWas TRACING=on in .env for that run?")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarise(spans: list[dict]):
    by_id = {s["span_id"]: s for s in spans}
    children = defaultdict(list)
    for s in spans:
        children[s["parent_span_id"]].append(s)
    for kids in children.values():
        kids.sort(key=lambda s: s["start_ns"])

    def agent_of(s):
        while s:
            if kind_of(s["name"]) == "agent":
                return s["attributes"].get("gen_ai.agent.name") or s["name"].split(" ", 1)[-1]
            s = by_id.get(s["parent_span_id"])
        return ""

    def descendants(root):
        stack = [root]
        while stack:
            s = stack.pop()
            yield s
            stack.extend(children.get(s["span_id"], []))

    roots = sorted((s for s in spans if kind_of(s["name"]) == "eval_case"), key=lambda s: s["start_ns"])
    runs_seen = defaultdict(int)
    case_rows, span_rows = [], []
    for root in roots:
        a = root["attributes"]
        case = a.get("eval.case_id") or root["name"].split(" ", 1)[-1]
        runs_seen[case] += 1
        t0 = root["start_ns"]
        sec = lambda ns: ns / 1e9  # noqa: E731
        total = sec(root["end_ns"] - t0)
        model_s = tool_s = wait_s = 0.0
        n_model = n_tool = tok_in = tok_out = tok_cached = 0
        error_kinds = []
        tok_by_agent = defaultdict(int)
        biggest = (0, "")
        errors = []
        for s in descendants(root):
            k, at, dur = kind_of(s["name"]), s["attributes"], sec(s["end_ns"] - s["start_ns"])
            agent = agent_of(s)
            i_tok = int(at.get("gen_ai.usage.input_tokens", 0) or 0)
            o_tok = int(at.get("gen_ai.usage.output_tokens", 0) or 0)
            c_tok = int(at.get("gen_ai.usage.cache_read.input_tokens", 0) or 0)
            if k == "model_call":
                model_s += dur
                n_model += 1
                tok_in += i_tok
                tok_out += o_tok
                tok_cached += c_tok
                tok_by_agent[agent] += i_tok + o_tok
                biggest = max(biggest, (i_tok, agent))
            elif k == "tool" and "transfer_to_agent" not in s["name"]:
                tool_s += dur
                n_tool += 1
            elif k == "agent":
                kids = children.get(s["span_id"], [])
                if kids:  # time inside the agent before its first step started (e.g. MCP startup)
                    wait_s += sec(kids[0]["start_ns"] - s["start_ns"])
            if s["status"] == "ERROR":
                errors.append(s["name"])
                error_kinds.append(error_kind(s))
            span_rows.append({
                "run_id": s["run_id"], "case_id": case, "case_run": runs_seen[case], "trace_id": s["trace_id"],
                "span_id": s["span_id"], "parent_span_id": s["parent_span_id"], "name": s["name"], "kind": k,
                "agent": agent, "tool": at.get("gen_ai.tool.name", ""), "model": at.get("gen_ai.request.model", ""),
                "start_offset_s": round(sec(s["start_ns"] - t0), 3), "duration_s": round(dur, 3),
                "status": s["status"], "input_tokens": i_tok, "output_tokens": o_tok,
                "cached_input_tokens": c_tok,
                "error_kind": error_kind(s) if s["status"] == "ERROR" else "",
                "error_detail": (s.get("error_type", "") + " " + s.get("exception", "")).strip()[:300],
            })
        case_rows.append({
            "run_id": root["run_id"], "case_id": case, "case_run": runs_seen[case], "suite": a.get("eval.suite", ""),
            "agent_model": a.get("eval.agent_model", ""), "sabotage": a.get("eval.sabotage", ""),
            "trace_id": root["trace_id"], "total_s": round(total, 2), "model_s": round(model_s, 2),
            "tool_s": round(tool_s, 2), "other_s": round(max(total - model_s - tool_s, 0), 2),
            "agent_wait_s": round(wait_s, 2), "model_calls": n_model, "tool_calls": n_tool,
            "input_tokens": tok_in, "output_tokens": tok_out, "total_tokens": tok_in + tok_out,
            "biggest_call_agent": biggest[1], "biggest_call_input_tokens": biggest[0],
            "cached_input_tokens": tok_cached,
            "tokens_by_agent": json.dumps(dict(tok_by_agent)), "error_spans": "; ".join(errors),
            "error_kinds": "; ".join(sorted(set(error_kinds))),
        })
    return case_rows, span_rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    results = Path(sys.argv[1])
    m = re.search(r"(\d{8}_\d{6}_\d{6})", results.name)
    if not m:
        sys.exit(f"Cannot find a run id in {results.name}")
    case_rows, span_rows = summarise(load_spans(m.group(1)))
    if not case_rows:
        sys.exit("No eval_case spans in that run (was it run through pytest with TRACING=on?)")

    base = results.with_suffix("")
    write_csv(Path(f"{base}_span_summary.csv"), case_rows)
    write_csv(Path(f"{base}_spans.csv"), span_rows)

    print(f"\nTrace summary for {results.name}  (seconds; tokens = input+output)")
    print(f"{'case':<6}{'total':>7}{'model':>7}{'tools':>7}{'other':>7}{'wait':>6}{'calls':>6}{'tok in':>8}{'tok out':>8}  biggest call")
    for r in case_rows:
        tag = r["case_id"] + (f"#{r['case_run']}" if r["case_run"] > 1 else "")
        print(f"{tag:<6}{r['total_s']:>7.1f}{r['model_s']:>7.1f}{r['tool_s']:>7.1f}{r['other_s']:>7.1f}"
              f"{r['agent_wait_s']:>6.1f}{r['model_calls']:>6}{r['input_tokens']:>8}{r['output_tokens']:>8}"
              f"  {r['biggest_call_agent']} ({r['biggest_call_input_tokens']} in)"
              + (f"  ERRORS ({r['error_kinds']}): {r['error_spans']}" if r["error_spans"] else ""))
    tot = {k: sum(r[k] for r in case_rows) for k in ("total_s", "model_s", "tool_s", "other_s", "input_tokens", "output_tokens")}
    if tot["total_s"]:
        print(f"\nAll cases: {tot['total_s']:.0f}s = model {100 * tot['model_s'] / tot['total_s']:.0f}%, "
              f"tools {100 * tot['tool_s'] / tot['total_s']:.0f}%, other {100 * tot['other_s'] / tot['total_s']:.0f}%;  "
              f"tokens in:out = {tot['input_tokens']}:{tot['output_tokens']}"
              + (f" ({tot['input_tokens'] / max(tot['output_tokens'], 1):.0f}x)" if tot["output_tokens"] else ""))
    agents = defaultdict(int)
    for r in case_rows:
        for k, v in json.loads(r["tokens_by_agent"]).items():
            agents[k] += v
    if agents:
        print("Tokens by agent: " + ", ".join(f"{k} {v}" for k, v in sorted(agents.items(), key=lambda kv: -kv[1])))
    print(f"\nSaved: {Path(f'{base}_span_summary.csv').name} and {Path(f'{base}_spans.csv').name}")


if __name__ == "__main__":
    main()
