"""Pytest configuration for ADK evaluations.

This file sets up pytest fixtures and markers for ADK eval tests.
"""
import pytest
from pathlib import Path
import os
import json

# Increase MCP timeout from default 30s to 120s (2 minutes)
# This allows slow backends to respond without timing out
os.environ['MCP_REQUEST_TIMEOUT'] = '120'
os.environ['ADK_MCP_TIMEOUT'] = '120'


# How many eval cases ADK runs at the same time (ADK's default is 4).
# Each running case starts its own MCP tool servers and opens database
# connections, so running several at once can drop connections
# ("MCP session connection lost"). Default here: one case at a time.
# Raise it with:  $env:EVAL_PARALLELISM = "4"
EVAL_PARALLELISM = int(os.getenv("EVAL_PARALLELISM", "1"))

import google.adk.evaluation.base_eval_service as _bes  # noqa: E402

_AdkInferenceConfig = _bes.InferenceConfig


class _InferenceConfig(_AdkInferenceConfig):
    parallelism: int = EVAL_PARALLELISM


# AgentEvaluator imports InferenceConfig from this module when it runs, so it
# picks up our default. Only the agent runs are limited; the judge calls that
# score them still run in parallel.
_bes.InferenceConfig = _InferenceConfig


# ADK's results CSV keeps only the LAST agent's text in `actual_response`. In a
# multi-agent answer (incidents -> metrics) the earlier agents' parts are lost.
# Add two columns: `actual_full_response` (every agent's text, in order, using
# ADK's own helper) and `invocation_id` (which turn of a multi-turn case).
from google.adk.evaluation.agent_evaluator import AgentEvaluator as _AgentEvaluator  # noqa: E402
from google.adk.evaluation.llm_as_judge_utils import get_text_from_content as _text  # noqa: E402

_adk_rows = _AgentEvaluator._get_results_as_rows


def _rows_with_full_answer(eval_set_id, eval_id, eval_metric_results):
    rows = _adk_rows(eval_set_id=eval_set_id, eval_id=eval_id, eval_metric_results=eval_metric_results)
    results = [r for rs in eval_metric_results.values() for r in rs]
    # ADK lists results run by run, then turn by turn, per metric. Count how often each
    # expected turn has appeared for this metric to get the run number (1, 2, 3...).
    seen: dict[tuple, int] = {}
    run_index = []
    for metric, rs in eval_metric_results.items():
        for r in rs:
            key = (metric, getattr(r.expected_invocation, "invocation_id", None))
            seen[key] = seen.get(key, 0) + 1
            run_index.append(seen[key])
    for row, r, run in zip(rows, results, run_index):
        row["run_index"] = run
        inv = r.actual_invocation
        row["actual_full_response"] = _text(inv, include_intermediate_responses_in_final=True) or ""
        row["invocation_id"] = getattr(inv, "invocation_id", "") or ""
        # Link to the trace of this run (empty unless TRACING=on).
        import telemetry  # noqa: PLC0415  (loaded later in this file)
        row["trace_id"] = telemetry.trace_id_for(row["invocation_id"])
        row["trace_url"] = telemetry.trace_url(row["trace_id"])
        # Rubric metrics: one verdict (1 = yes, 0 = no) and the judge's reason per item.
        details = getattr(r.eval_metric_result, "details", None)
        scores = getattr(details, "rubric_scores", None) or []
        row["rubric_scores"] = json.dumps([{"id": s.rubric_id, "score": s.score, "reason": s.rationale}
                                           for s in scores], ensure_ascii=False) if scores else ""
    return rows


_AgentEvaluator._get_results_as_rows = staticmethod(_rows_with_full_answer)


# Models come from .env, not code:
#   GEMINI_MODEL  the agent's model (ops_agent/agent.py already reads it)
#   JUDGE_MODEL   the LLM judges' model; defaults to GEMINI_MODEL
# golden_core/test_config.json names no model; this hook adds JUDGE_MODEL to every
# judge each time ADK loads that file.
from dotenv import load_dotenv as _load_dotenv  # noqa: E402

_load_dotenv(Path(__file__).resolve().parent.parent / ".env")
JUDGE_MODEL = os.getenv("JUDGE_MODEL") or os.getenv("GEMINI_MODEL")
if not JUDGE_MODEL:
    raise RuntimeError("Set GEMINI_MODEL (and optionally JUDGE_MODEL) in .env: no model is named in code.")
# JUDGE_SAMPLES  how many times each judge scores a turn (majority vote).
# Blank = keep test_config.json (3). Use 1 while developing: about 3x faster judging.
JUDGE_SAMPLES = int(os.getenv("JUDGE_SAMPLES") or 0) or None

# Day 4 tracing: OpenTelemetry -> Cloud Trace, switched on with TRACING=on in .env.
# Imported after .env is loaded because it reads TRACING when imported.
import telemetry as _telemetry  # noqa: E402

_telemetry.setup()
_telemetry.instrument_eval_cases(agent_model=os.getenv("GEMINI_MODEL", ""), judge_model=JUDGE_MODEL)

_adk_find_config = _AgentEvaluator.find_config_for_test_file


def _config_with_judge_model(test_file):
    cfg = _adk_find_config(test_file)
    for criterion in (cfg.criteria or {}).values():
        opts = getattr(criterion, "judge_model_options", None)
        if opts is None:  # untyped criterion: options kept as a plain dict
            opts = (getattr(criterion, "model_extra", None) or {}).get("judgeModelOptions")
        if isinstance(opts, dict):
            opts["judgeModel"] = JUDGE_MODEL
            if JUDGE_SAMPLES:
                opts["numSamples"] = JUDGE_SAMPLES
        elif opts is not None:
            opts.judge_model = JUDGE_MODEL
            if JUDGE_SAMPLES:
                opts.num_samples = JUDGE_SAMPLES
    return cfg


_AgentEvaluator.find_config_for_test_file = staticmethod(_config_with_judge_model)


# Teardown watchdog. On Windows, closing the MCP tool-server processes at the end of a test can hang
# forever in the asyncio event loop (seen after TestSabotage: ~17 min stuck after "FAILED [100%]").
# The results CSV is already written by then, so if teardown takes longer than TEARDOWN_TIMEOUT_S
# (default 120 s) we send the last traces and exit with the test's own result. The run script
# then carries on with its analysis steps as usual.
import sys  # noqa: E402
import threading  # noqa: E402

TEARDOWN_TIMEOUT_S = int(os.getenv("TEARDOWN_TIMEOUT_S", "120"))
_test_failed: dict[str, bool] = {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        _test_failed[item.nodeid] = True


def _teardown_stuck(item) -> None:
    failed = _test_failed.get(item.nodeid, False)
    # pytest captures output during teardown: pause its capturing so the message reaches the terminal.
    capman = item.config.pluginmanager.getplugin("capturemanager")
    if capman is not None:
        capman.suspend_global_capture(in_=False)
    sys.__stdout__.write(f"\n[teardown] still shutting down after {TEARDOWN_TIMEOUT_S}s (tool-server processes did not "
                         f"close). The results are already saved; exiting so the run can continue. Test result: "
                         f"{'FAILED' if failed else 'PASSED'}.\n")
    sys.__stdout__.flush()
    try:
        _telemetry.flush()
    finally:
        os._exit(1 if failed else 0)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    timer = threading.Timer(TEARDOWN_TIMEOUT_S, _teardown_stuck, args=(item,))
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def pytest_runtest_setup(item):
    """Tag traces with the suite being run (TestQuick, TestStress, ...)."""
    _telemetry.suite = item.cls.__name__ if item.cls else item.name


def pytest_sessionfinish(session, exitstatus):
    """Send the last buffered spans to Cloud Trace before pytest exits."""
    _telemetry.flush()


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "adk: ADK evaluation tests"
    )
    config.addinivalue_line(
        "markers", "category: Category of eval (lookup, log_search, metrics, etc)"
    )
    config.addinivalue_line(
        "markers", "agents: Number of agents involved (single, multi)"
    )


@pytest.fixture(scope="session")
def eval_sets_dir():
    """Path to evaluation sets directory."""
    return Path(__file__).parent / "golden_core"


@pytest.fixture(scope="session")
def config_file():
    """Path to evaluation configuration file."""
    return Path(__file__).parent / "golden_core" / "test_config.json"


@pytest.fixture(scope="session")
def ops_agent_module():
    """ADK agent module name."""
    return "ops_agent"
