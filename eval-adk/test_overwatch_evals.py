"""ADK evaluation tests for Overwatch Mini (sandbox).

The active golden data is the 10-case core set in eval-adk/golden_core/.
The original 64 cases are archived in eval-adk/archive/eval_sets_original/.

Run (PowerShell, from the repo root):
  .\run_eval_full.ps1 TestQuick            # 10 core cases, with report
  .\run_eval_full.ps1 TestStress           # 10 stress cases (failures expected)
  .\run_eval_full.ps1 TestConsistency      # 10 chosen cases x 3 runs: how often results flip
  $env:SABOTAGE = "wrong_window"; .\run_eval_full.ps1 TestSabotage
                                            # 20 cases against a deliberately broken agent
  python -m pytest eval-adk/test_overwatch_evals.py::TestQuick -v
"""
from datetime import datetime, timezone
import os
from pathlib import Path

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator


# Same id as the traces of this run (set by telemetry.py, imported from conftest.py).
RUN_ID = os.environ.get("EVAL_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
RUNS_DIR = Path(__file__).parent / "runs"

# The 10 verified core cases (one per category). See eval-adk/golden_core/README.md.
CORE_EVALSET = Path(__file__).parent / "golden_core" / "overwatch_core.evalset.json"
# 10 cases built to make the agent fail in known ways (see golden_core/README.md).
STRESS_EVALSET = Path(__file__).parent / "golden_core" / "overwatch_stress.evalset.json"


@pytest.mark.adk
@pytest.mark.asyncio
@pytest.mark.timeout(1800)  # LLM judges take ~1-2 min per case
class TestQuick:
    """Quick: the 10 core golden cases (about 5-20 minutes, depending on JUDGE_SAMPLES)."""

    async def test_quick_evals(self):
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        await AgentEvaluator.evaluate(
            agent_module="ops_agent",
            eval_dataset_file_path_or_dir=str(CORE_EVALSET),
            output_file=str(RUNS_DIR / f"quick_results_{RUN_ID}.csv"),
            num_runs=1,
        )


@pytest.mark.adk
@pytest.mark.asyncio
@pytest.mark.timeout(1800)  # LLM judges take ~1-2 min per case
class TestStress:
    """Stress: 10 cases designed to fail specific checks. Failures are expected."""

    async def test_stress_evals(self):
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        await AgentEvaluator.evaluate(
            agent_module="ops_agent",
            eval_dataset_file_path_or_dir=str(STRESS_EVALSET),
            output_file=str(RUNS_DIR / f"stress_results_{RUN_ID}.csv"),
            num_runs=1,
        )


@pytest.mark.adk
@pytest.mark.asyncio
@pytest.mark.timeout(3600)  # pytest.ini allows 600 s per test; this run takes longer
class TestSabotage:
    """Fault injection: all 20 golden cases against a deliberately broken copy of the
    agent (eval-adk/sabotaged_agent). Choose the fault with the SABOTAGE environment
    variable. Many failures are the goal: they prove the evals catch real faults."""

    async def test_sabotage_evals(self):
        import os
        mode = os.getenv("SABOTAGE", "guess_from_memory")
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        output_file = str(RUNS_DIR / f"sabotage_{mode}_results_{RUN_ID}.csv")
        failed_sets = []
        for evalset in (CORE_EVALSET, STRESS_EVALSET):
            try:
                await AgentEvaluator.evaluate(
                    agent_module="sabotaged_agent",
                    eval_dataset_file_path_or_dir=str(evalset),
                    output_file=output_file,
                    num_runs=1,
                )
            except AssertionError:
                failed_sets.append(evalset.name)
        assert not failed_sets, f"Sabotage '{mode}' was caught in: {', '.join(failed_sets)}"


# Default consistency set: 5 core + 5 stress cases, a mix of cases expected to be stable
# (G001, G030, G053, S03, S09) and cases seen to flip before (G039, G040, S05, S07, S10).
# EVAL_CASES="all" runs all 20; EVAL_CASES="G001,S05" runs just those.
CONSISTENCY_CASES = ["G001", "G030", "G039", "G040", "G053", "S03", "S05", "S07", "S09", "S10"]


def consistency_evalsets(cases_env: str) -> list[Path]:
    """The golden evalsets, filtered to the chosen cases, written next to a copy of
    test_config.json (ADK reads the config from the evalset's folder)."""
    import json
    import shutil

    if cases_env.strip().lower() == "all":
        return [CORE_EVALSET, STRESS_EVALSET]
    wanted = {c.strip().upper() for c in cases_env.split(",") if c.strip()} or set(CONSISTENCY_CASES)
    out_dir = RUNS_DIR / "_consistency_evalsets"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    shutil.copy(CORE_EVALSET.parent / "test_config.json", out_dir / "test_config.json")
    files, found = [], set()
    for src in (CORE_EVALSET, STRESS_EVALSET):
        doc = json.loads(src.read_text(encoding="utf-8"))
        keep = [c for c in doc["eval_cases"] if c["eval_id"] in wanted]
        if keep:
            found.update(c["eval_id"] for c in keep)
            dst = out_dir / src.name
            dst.write_text(json.dumps({**doc, "eval_cases": keep}, ensure_ascii=False, indent=1), encoding="utf-8")
            files.append(dst)
    assert wanted == found, f"Unknown case IDs: {sorted(wanted - found)}"
    return files


@pytest.mark.adk
@pytest.mark.asyncio
@pytest.mark.timeout(3600)  # pytest.ini allows 600 s per test; this run takes longer
class TestConsistency:
    """Consistency: the CONSISTENCY_CASES (default 10), each run EVAL_REPEATS times (default 3)
    against the real agent. eval-adk/consistency.py then reports how often results flip."""

    async def test_consistency_evals(self):
        import os
        repeats = int(os.getenv("EVAL_REPEATS", "3"))
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        output_file = str(RUNS_DIR / f"consistency_x{repeats}_results_{RUN_ID}.csv")
        failed_sets = []
        for evalset in consistency_evalsets(os.getenv("EVAL_CASES", "")):
            try:
                await AgentEvaluator.evaluate(
                    agent_module="ops_agent",
                    eval_dataset_file_path_or_dir=str(evalset),
                    output_file=output_file,
                    num_runs=repeats,
                )
            except AssertionError:
                failed_sets.append(evalset.name)
        assert not failed_sets, f"Failed criteria in: {', '.join(failed_sets)}. See consistency report."
