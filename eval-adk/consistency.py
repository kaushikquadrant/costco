#!/usr/bin/env python
"""How consistent are the results when the same case runs several times?

    python eval-adk\\consistency.py eval-adk\\runs\\<run>\\consistency_x3_results_<id>.csv

The CSV comes from TestConsistency (each case run EVAL_REPEATS times). For every
case and every signal (ADK's metrics, the rubric judge, our six checks and the
agent's behaviour), it counts how many runs passed. A signal is "flaky" when the
runs disagree. The same code and the same question giving different verdicts is
noise from the agent (Gemini answers differently) or from an LLM judge
(verdicts differ on similar answers); one run is never a verdict on its own.

Writes <results>_consistency.json and _consistency.csv next to the CSV.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path

import score_checks

ADK_METRICS = {
    "tool_trajectory_avg_score": "adk_trajectory",
    "final_response_match_v2": "adk_response_match",
    "hallucinations_v1": "adk_hallucination",
    "rubric_based_final_response_quality_v1": "adk_rubric_judge",
}
OUR_CHECKS = [f"{c}_passed" for c in score_checks.CHECKS]
SIGNALS = list(ADK_METRICS.values()) + [c.replace("_passed", "") for c in OUR_CHECKS] + ["passed_all"]


def split_runs(csv_path: Path) -> dict[int, list[dict]]:
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or "run_index" not in rows[0]:
        raise SystemExit("This CSV has no run_index column: run it with TestConsistency.")
    runs: dict[int, list[dict]] = {}
    for r in rows:
        runs.setdefault(int(r["run_index"]), []).append(r)
    return runs


def score_run(rows: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Our checks (via score_checks) and ADK's pass/fail, per case, for one run."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as tmp:
        w = csv.DictWriter(tmp, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    try:
        ours = {r["eval_id"]: r for r in score_checks.score(Path(tmp.name))}
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    adk: dict[str, dict] = {}
    for r in rows:
        name = ADK_METRICS.get(r["metric_name"])
        if not name:
            continue
        ok = r["eval_status"] not in ("FAILED", "NOT_EVALUATED")
        adk.setdefault(r["eval_id"], {})
        adk[r["eval_id"]][name] = adk[r["eval_id"]].get(name, True) and ok
    return ours, adk


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    csv_path = Path(argv[0])
    runs = split_runs(csv_path)
    n = len(runs)
    per_run = {i: score_run(rows) for i, rows in sorted(runs.items())}

    case_ids = sorted({cid for ours, _ in per_run.values() for cid in ours})
    results = []
    for cid in case_ids:
        passes: dict[str, int] = {s: 0 for s in SIGNALS}
        counted: dict[str, int] = {s: 0 for s in SIGNALS}
        behaviours, tokens, latency = Counter(), [], []
        for ours, adk in per_run.values():
            o, a = ours.get(cid), adk.get(cid, {})
            if o is None:
                continue
            for name, ok in a.items():
                passes[name] += int(ok)
                counted[name] += 1
            for c in OUR_CHECKS:
                passes[c.replace("_passed", "")] += int(o[c])
                counted[c.replace("_passed", "")] += 1
            all_ok = o["checks_passed"] and all(a.values())
            passes["passed_all"] += int(all_ok)
            counted["passed_all"] += 1
            behaviours[o["actual_behaviour"]] += 1
            if o["tokens"] is not None:
                tokens.append(o["tokens"])
            if o["latency_s"] is not None:
                latency.append(o["latency_s"])
        flaky = [s for s in SIGNALS if counted[s] and 0 < passes[s] < counted[s]]
        meta = score_checks.load_golden().get(cid, {}).get("meta", {})
        results.append({
            "eval_id": cid,
            "split": meta.get("split"),
            "category": meta.get("category"),
            "runs": counted["passed_all"],
            "passed_all_runs": passes["passed_all"],
            "stable": not flaky,
            "flaky_signals": ",".join(flaky),
            "behaviours": ", ".join(f"{b} x{k}" for b, k in behaviours.most_common()),
            **{f"{s}_passes": passes[s] for s in SIGNALS},
            **{f"{s}_n": counted[s] for s in SIGNALS},
            "tokens_mean": round(statistics.mean(tokens)) if tokens else None,
            "tokens_min": min(tokens) if tokens else None,
            "tokens_max": max(tokens) if tokens else None,
            "latency_mean_s": round(statistics.mean(latency), 1) if latency else None,
            "latency_max_s": round(max(latency), 1) if latency else None,
        })

    stem = csv_path.with_suffix("")
    Path(f"{stem}_consistency.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with open(f"{stem}_consistency.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)

    print(f"\nConsistency over {n} runs per case: {csv_path.name}")
    print(f"{'case':<6}{'all checks':<12}{'stable':<8}{'tokens min-max':<16}{'behaviour':<26}flaky signals")
    for r in results:
        rng = f"{r['tokens_min']:.0f}-{r['tokens_max']:.0f}" if r["tokens_min"] is not None else "-"
        print(f"{r['eval_id']:<6}{str(r['passed_all_runs']) + '/' + str(r['runs']):<12}"
              f"{'yes' if r['stable'] else 'NO':<8}{rng:<16}{r['behaviours'][:24]:<26}{r['flaky_signals'] or '-'}")
    stable = sum(r["stable"] for r in results)
    print(f"\n  stable cases: {stable}/{len(results)}")
    print("  how often each signal gave the same verdict on every run:")
    for s in SIGNALS:
        scored = [r for r in results if r[f"{s}_n"]]
        if not scored:
            continue
        agree = sum(1 for r in scored if r[f"{s}_passes"] in (0, r[f"{s}_n"]))
        print(f"    {s:<20} {agree}/{len(scored)} cases unanimous")
    print(f"\nSaved: {stem.name}_consistency.json and _consistency.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
