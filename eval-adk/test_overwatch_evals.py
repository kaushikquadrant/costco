"""ADK evaluation tests for Overwatch Mini.

This module runs ADK evaluations against the Overwatch Mini agent.
Each test class covers one evaluation category.

Run all:
  pytest eval-adk/test_overwatch_evals.py -v

Run one category:
  pytest eval-adk/test_overwatch_evals.py::TestLookup -v

Run with markers:
  pytest eval-adk/test_overwatch_evals.py -m category -k lookup -v
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator


EVAL_SETS_DIR = Path(__file__).parent / "eval_sets"
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
RUNS_DIR = Path(__file__).parent / "runs"


async def evaluate_evalset(evalset_name: str, output_name: str) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    await AgentEvaluator.evaluate(
        agent_module="ops_agent",
        eval_dataset_file_path_or_dir=str(EVAL_SETS_DIR / evalset_name),
        output_file=str(RUNS_DIR / output_name.replace(".csv", f"_{RUN_ID}.csv")),
        num_runs=1,
    )


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestLookup:
    """Lookup: Single item queries (get incident by ID)."""

    async def test_lookup_evals(self):
        """Run all lookup evaluation cases."""
        await evaluate_evalset("overwatch_lookup.evalset.json", "lookup_results.csv")


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestAggregation:
    """Aggregation: Count/group queries."""

    async def test_aggregation_evals(self):
        """Run all aggregation evaluation cases."""
        await evaluate_evalset("overwatch_aggregation.evalset.json", "aggregation_results.csv")


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestLogCount:
    """Log Count: Count log lines by level/service/time."""

    async def test_log_count_evals(self):
        """Run all log count evaluation cases."""
        await evaluate_evalset("overwatch_log_count.evalset.json", "log_count_results.csv")


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestLogSearch:
    """Log Search: Search/read log content."""

    async def test_log_search_evals(self):
        """Run all log search evaluation cases."""
        await evaluate_evalset("overwatch_log_search.evalset.json", "log_search_results.csv")


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestMetrics:
    """Metrics: Performance metrics (CPU, latency, error rate, etc)."""

    async def test_metrics_evals(self):
        """Run all metrics evaluation cases."""
        await evaluate_evalset("overwatch_metrics.evalset.json", "metrics_results.csv")


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestProblems:
    """Problems: Monitoring problems (from metrics/Dynatrace)."""

    async def test_problems_evals(self):
        """Run all problems evaluation cases."""
        await evaluate_evalset("overwatch_problems.evalset.json", "problems_results.csv")


@pytest.mark.adk
@pytest.mark.agents
@pytest.mark.asyncio
class TestCrossSource:
    """Cross-Source: Multi-agent questions (incidents + logs + metrics)."""

    async def test_cross_source_evals(self):
        """Run all cross-source evaluation cases (multi-agent)."""
        await evaluate_evalset("overwatch_cross_source.evalset.json", "cross_source_results.csv")


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestNegative:
    """Negative: Correct refusal (no data exists)."""

    async def test_negative_evals(self):
        """Run all negative evaluation cases."""
        await evaluate_evalset("overwatch_negative.evalset.json", "negative_results.csv")


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestOutOfScope:
    """Out-of-Scope: Should refuse (we don't have that data)."""

    async def test_out_of_scope_evals(self):
        """Run all out-of-scope evaluation cases."""
        await evaluate_evalset("overwatch_out_of_scope.evalset.json", "out_of_scope_results.csv")


@pytest.mark.adk
@pytest.mark.category
@pytest.mark.asyncio
class TestSafety:
    """Safety: Prompt injection and data safety."""

    async def test_safety_evals(self):
        """Run all safety evaluation cases."""
        await evaluate_evalset("overwatch_safety.evalset.json", "safety_results.csv")


# ============================================================================
# Full Suite Tests (run all at once)
# ============================================================================

@pytest.mark.adk
@pytest.mark.asyncio
class TestFullSuite:
    """Full Suite: All 64 evaluation cases (all categories)."""

    async def test_all_categories(self):
        """Run ALL evaluation cases from all categories."""
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        output_file = str(RUNS_DIR / f"full_suite_results_{RUN_ID}.csv")
        evalset_paths = sorted(EVAL_SETS_DIR.glob("*.evalset.json"))
        assert evalset_paths, f"No evalset files found in {EVAL_SETS_DIR}"

        for evalset_path in evalset_paths:
            await AgentEvaluator.evaluate(
                agent_module="ops_agent",
                eval_dataset_file_path_or_dir=str(evalset_path),
                output_file=output_file,
                num_runs=1,
            )
