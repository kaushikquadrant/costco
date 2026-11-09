"""OpenTelemetry tracing for the eval runs, sent to Cloud Trace (Day 4).

Switched on from .env (off by default):
    TRACING=on              send traces to Cloud Trace
    TRACE_CONTENT=true      keep prompts and answers in the spans (fine here: synthetic data)

What it adds on top of ADK's built-in spans (agent runs, model calls, tool calls):
  * one parent span per eval case, "eval_case <id>", tagged with the case id, eval set,
    run id, suite (TestQuick, TestStress...), sabotage mode and both model names,
    so Cloud Trace can be searched by case instead of by timestamp;
  * an index from ADK invocation id to trace id, so every row of the results CSV
    gets a `trace_id` column that links the eval verdict to its waterfall;
  * a local copy of every span (timings, agent, tool, model, tokens incl. cached, error type; no prompt text) in
    runs/spans/spans_<run_id>.jsonl, read by span_summary.py and later loaded into BigQuery.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

TRACING = os.getenv("TRACING", "off").strip().lower() in ("1", "on", "true", "yes")
# One id per pytest process: shared by the results CSV name and every trace in the run.
RUN_ID = os.environ.setdefault("EVAL_RUN_ID", datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"))

SPANS_DIR = __import__("pathlib").Path(__file__).resolve().parent / "runs" / "spans"
SPANS_FILE = SPANS_DIR / f"spans_{RUN_ID}.jsonl"   # every finished span of this run, one JSON per line

suite = ""                                # set by conftest before each test
_invocation_trace: dict[str, str] = {}    # ADK invocation id -> trace id (32 hex chars)
_provider = None


def trace_id_for(invocation_id: str) -> str:
    return _invocation_trace.get(invocation_id or "", "")


def trace_url(trace_id: str) -> str:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    return f"https://console.cloud.google.com/traces/explorer;traceId={trace_id}?project={project}" if trace_id else ""


def setup(service_name: str = "overwatch-mini") -> None:
    """Install the Cloud Trace exporter once. Does nothing unless TRACING=on."""
    global _provider
    if not TRACING or _provider is not None:
        return
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] = os.getenv("TRACE_CONTENT", "true")

    import google.auth
    from opentelemetry import trace
    from opentelemetry.sdk.trace import SpanProcessor
    from google.adk.telemetry.google_cloud import _CLOUD_PLATFORM_SCOPE, get_gcp_exporters, get_gcp_resource
    from google.adk.telemetry.setup import OTelHooks, maybe_set_otel_providers

    class _InvocationIndex(SpanProcessor):
        """Remembers which trace each ADK invocation belongs to."""

        def on_end(self, span) -> None:
            inv = (span.attributes or {}).get("gcp.vertex.agent.invocation_id")
            if inv:
                _invocation_trace.setdefault(str(inv), format(span.context.trace_id, "032x"))

    import json
    import threading

    keep = ("eval.", "gen_ai.agent.name", "gen_ai.request.model", "gen_ai.usage.", "gen_ai.operation.name",
            "gen_ai.tool.name", "gcp.vertex.agent.invocation_id", "error.type")

    class _LocalSpanFile(SpanProcessor):
        """Writes a compact copy of every span to runs/spans/ (no prompt text): for analysis and BigQuery."""

        def __init__(self) -> None:
            self._lock = threading.Lock()
            SPANS_DIR.mkdir(parents=True, exist_ok=True)

        def on_end(self, span) -> None:
            attrs = {k: v for k, v in (span.attributes or {}).items() if k.startswith(keep)}
            row = {
                "run_id": RUN_ID,
                "trace_id": format(span.context.trace_id, "032x"),
                "span_id": format(span.context.span_id, "016x"),
                "parent_span_id": format(span.parent.span_id, "016x") if span.parent else "",
                "name": span.name,
                "start_ns": span.start_time,
                "end_ns": span.end_time,
                "status": span.status.status_code.name,
                # Why a span failed: the error type ADK recorded (e.g. a timeout, a 429, a tool error)
                # plus the first exception's type and a short message.
                "error_type": (span.attributes or {}).get("error.type") or span.status.description or "",
                "exception": next((f"{(e.attributes or {}).get('exception.type', '')}: "
                                   f"{str((e.attributes or {}).get('exception.message', ''))[:200]}"
                                   for e in span.events if e.name == "exception"), ""),
                "attributes": {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in attrs.items()},
            }
            with self._lock, open(SPANS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")

    credentials, adc_project = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or adc_project
    hooks = get_gcp_exporters(enable_cloud_tracing=True, google_auth=(credentials, project))
    if not hooks.span_processors:
        raise RuntimeError("TRACING=on but no Cloud Trace exporter could be built (is GOOGLE_CLOUD_PROJECT set?).")
    maybe_set_otel_providers(
        otel_hooks_to_setup=[hooks, OTelHooks(span_processors=[_InvocationIndex(), _LocalSpanFile()])],
        otel_resource=get_gcp_resource(project),
    )
    _provider = trace.get_tracer_provider()
    print(f"[tracing] on: project={project} service={os.environ['OTEL_SERVICE_NAME']} run={RUN_ID}")
    print(f"[tracing] local span copy: {SPANS_FILE}")


def instrument_eval_cases(agent_model: str, judge_model: str) -> None:
    """Wrap each eval case's agent run in an "eval_case <id>" parent span."""
    if not TRACING:
        return
    from opentelemetry import trace
    from google.adk.evaluation.local_eval_service import LocalEvalService

    tracer = trace.get_tracer("overwatch-mini.evals")
    original = LocalEvalService._perform_inference_single_eval_item

    async def traced(self, app_name, eval_set_id, eval_case, root_agent, *args, **kwargs):
        attrs = {
            "eval.case_id": eval_case.eval_id,
            "eval.set_id": eval_set_id,
            "eval.run_id": RUN_ID,
            "eval.suite": suite,
            "eval.sabotage": os.getenv("SABOTAGE", ""),
            "eval.agent_model": agent_model,
            "eval.judge_model": judge_model,
        }
        with tracer.start_as_current_span(f"eval_case {eval_case.eval_id}", attributes=attrs) as span:
            result = await original(self, app_name, eval_set_id, eval_case, root_agent, *args, **kwargs)
            status = str(getattr(result, "status", ""))
            span.set_attribute("eval.inference_status", status)
            if "FAILURE" in status.upper():
                span.set_status(trace.Status(trace.StatusCode.ERROR, getattr(result, "error_message", None) or status))
            return result

    LocalEvalService._perform_inference_single_eval_item = traced


def flush() -> None:
    """Send buffered spans before the process exits."""
    if _provider is not None and hasattr(_provider, "force_flush"):
        _provider.force_flush(30_000)
        print(f"[tracing] flushed spans for run {RUN_ID}; Cloud Trace: filter on eval.run_id = {RUN_ID}")
