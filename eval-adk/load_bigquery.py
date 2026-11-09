"""Load archived eval runs into BigQuery (Day 5): the tables behind the Looker Studio dashboard.

One archive folder (eval-adk/runs/<local time>/) = one run. From it this loads:
  eval_results  <- <suite>_results_<run_id>.csv         ADK verdicts: one row per case x metric x repeat
  eval_checks   <- ..._checks.csv                       our checks:   one row per case
  case_traces   <- ..._span_summary.csv                 time/tokens:  one row per case x repeat (traced runs only)
  spans         <- ..._spans.csv                        waterfall:    one row per span (traced runs only)

Every row gets run_id (UTC start of the run, from the file name), run_started_at, suite and loaded_at.
Loading is safe to repeat: a run's old rows are deleted before its new rows go in.

Usage (PowerShell, repo root):
  python eval-adk/load_bigquery.py                    # the newest archive folder
  python eval-adk/load_bigquery.py --all              # every archive folder
  python eval-adk/load_bigquery.py eval-adk/runs/20261030_222010 ...
  python eval-adk/load_bigquery.py --views            # create/update the dashboard views (bigquery_views.sql)
Settings (.env): GOOGLE_CLOUD_PROJECT, BQ_DATASET (default overwatch_evals), BQ_LOCATION (default US)
"""
from __future__ import annotations

import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
load_dotenv(ROOT.parent / ".env")
csv.field_size_limit(10**8)

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
DATASET = os.getenv("BQ_DATASET", "overwatch_evals")
LOCATION = os.getenv("BQ_LOCATION", "US")

# Columns every table gets, in front of the file's own columns.
COMMON = [("run_id", "STRING"), ("run_started_at", "TIMESTAMP"), ("suite", "STRING")]
S, F, I, B = "STRING", "FLOAT", "INTEGER", "BOOLEAN"

TABLES = {
    "eval_results": {
        "file": re.compile(r"^(?P<suite>.+)_results_(?P<run>\d{8}_\d{6}_\d{6})\.csv$"),
        "cluster": ["eval_id"],
        "columns": [("eval_set_id", S), ("eval_id", S), ("metric_name", S), ("threshold", F), ("score", F),
                    ("eval_status", S), ("prompt", S), ("expected_response", S), ("actual_response", S),
                    ("actual_full_response", S), ("expected_tool_calls", S), ("actual_tool_calls", S),
                    ("run_index", I), ("invocation_id", S), ("trace_id", S), ("trace_url", S), ("rubric_scores", S)],
    },
    "eval_checks": {
        "file": re.compile(r"^(?P<suite>.+)_results_(?P<run>\d{8}_\d{6}_\d{6})_checks\.csv$"),
        "cluster": ["eval_id"],
        "columns": [("eval_id", S), ("eval_set_id", S), ("split", S), ("category", S), ("expected_behaviour", S),
                    ("actual_behaviour", S), ("infra_error", B), ("fact_check_passed", B), ("tool_args_passed", B),
                    ("agents_passed", B), ("behaviour_passed", B), ("format_passed", B), ("budgets_passed", B),
                    ("checks_passed", B), ("adk_failed", S), ("passed_all", B), ("problems", S),
                    ("known_limitations", S), ("rubric_failed", S), ("tool_calls", I), ("model_calls", I),
                    ("tokens", I), ("latency_s", F), ("leakage_passed", B), ("tools_allowed_passed", B)],
    },
    "case_traces": {
        "file": re.compile(r"^(?P<suite>.+)_results_(?P<run>\d{8}_\d{6}_\d{6})_span_summary\.csv$"),
        "cluster": ["case_id"],
        "columns": [("case_id", S), ("case_run", I), ("agent_model", S), ("sabotage", S), ("trace_id", S),
                    ("total_s", F), ("model_s", F), ("tool_s", F), ("other_s", F), ("agent_wait_s", F),
                    ("model_calls", I), ("tool_calls", I), ("input_tokens", I), ("output_tokens", I),
                    ("total_tokens", I), ("biggest_call_agent", S), ("biggest_call_input_tokens", I),
                    ("tokens_by_agent", S), ("error_spans", S), ("cached_input_tokens", I), ("error_kinds", S)],
    },
    "spans": {
        "file": re.compile(r"^(?P<suite>.+)_results_(?P<run>\d{8}_\d{6}_\d{6})_spans\.csv$"),
        "cluster": ["case_id"],
        "columns": [("case_id", S), ("case_run", I), ("trace_id", S), ("span_id", S), ("parent_span_id", S),
                    ("name", S), ("kind", S), ("agent", S), ("tool", S), ("model", S), ("start_offset_s", F),
                    ("duration_s", F), ("status", S), ("input_tokens", I), ("output_tokens", I),
                    ("cached_input_tokens", I), ("error_kind", S), ("error_detail", S)],
    },
}


def cast(value: str, kind: str):
    """CSV text -> the BigQuery type. Empty text becomes NULL."""
    if value is None or value.strip() == "":
        return None
    if kind == B:
        return value.strip().lower() in ("true", "1", "yes")
    if kind == I:
        return int(float(value))  # pandas wrote some counts as 2.0
    if kind == F:
        return float(value)
    return value


def schema_for(table: str) -> list[bigquery.SchemaField]:
    cols = COMMON + TABLES[table]["columns"] + [("loaded_at", "TIMESTAMP")]
    return [bigquery.SchemaField(name, kind, mode="NULLABLE") for name, kind in cols]


def ensure_tables(client: bigquery.Client) -> None:
    """Create the dataset and the four tables if they are missing (partitioned by run date)."""
    ds = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    ds.location = LOCATION
    client.create_dataset(ds, exists_ok=True)
    for name, spec in TABLES.items():
        t = bigquery.Table(f"{PROJECT}.{DATASET}.{name}", schema=schema_for(name))
        t.time_partitioning = bigquery.TimePartitioning(field="run_started_at")
        t.clustering_fields = spec["cluster"]
        existing = client.create_table(t, exists_ok=True)
        have = {f.name for f in existing.schema}
        missing = [f for f in schema_for(name) if f.name not in have]
        if missing:  # a newer loader added columns: extend the table, older rows read NULL
            existing.schema = list(existing.schema) + missing
            client.update_table(existing, ["schema"])
            print(f"  {name}: added columns {', '.join(f.name for f in missing)}")


def rows_from(path: Path, table: str, run_id: str, suite: str, loaded_at: str) -> list[dict]:
    started = datetime.strptime(run_id, "%Y%m%d_%H%M%S_%f").replace(tzinfo=timezone.utc).isoformat()
    columns = TABLES[table]["columns"]
    out = []
    with open(path, encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            row = {"run_id": run_id, "run_started_at": started, "suite": suite, "loaded_at": loaded_at}
            row.update({name: cast(raw.get(name), kind) for name, kind in columns})  # missing columns -> NULL
            out.append(row)
    return out


def load_folder(client: bigquery.Client, folder: Path) -> None:
    loaded_at = datetime.now(timezone.utc).isoformat()
    found = False
    for table, spec in TABLES.items():
        for path in sorted(folder.glob("*.csv")):
            m = spec["file"].match(path.name)
            if not m:
                continue
            found = True
            run_id, suite = m.group("run"), m.group("suite")
            rows = rows_from(path, table, run_id, suite, loaded_at)
            target = f"{PROJECT}.{DATASET}.{table}"
            # Delete-then-insert keeps reloads from doubling a run.
            client.query(f"DELETE FROM `{target}` WHERE run_id = @run",
                         job_config=bigquery.QueryJobConfig(
                             query_parameters=[bigquery.ScalarQueryParameter("run", "STRING", run_id)])).result()
            if rows:
                # No schema here: the table's own schema is used and columns are matched by name.
                job = client.load_table_from_json(rows, target, job_config=bigquery.LoadJobConfig(
                    write_disposition="WRITE_APPEND"))
                job.result()
            print(f"  {table:<13} {len(rows):>5} rows  <- {path.name}")
    if not found:
        print("  (no result files in this folder)")


def apply_views(client: bigquery.Client) -> None:
    """Create or update the dashboard views from bigquery_views.sql."""
    sql = (ROOT / "bigquery_views.sql").read_text(encoding="utf-8").replace("@DS", f"`{PROJECT}.{DATASET}`")
    for statement in re.split(r"^\s*;\s*$", sql, flags=re.M):
        body = "\n".join(l for l in statement.splitlines() if not l.strip().startswith("--")).strip()
        if body:
            client.query(body).result()
            print("  applied:", re.search(r"(TABLE IF NOT EXISTS|VIEW)\s+\S+\.(\w+)`?", body).group(2))


def main() -> None:
    if not PROJECT:
        sys.exit("Set GOOGLE_CLOUD_PROJECT in .env")
    args = sys.argv[1:]
    if args == ["--views"]:
        client = bigquery.Client(project=PROJECT, location=LOCATION)
        ensure_tables(client)
        print(f"Applying views to {PROJECT}.{DATASET}")
        apply_views(client)
        return
    archives = sorted(p for p in RUNS.iterdir() if p.is_dir() and re.fullmatch(r"\d{8}_\d{6}", p.name))
    if args == ["--all"]:
        folders = archives
    elif args:
        folders = [Path(a) for a in args]
    else:
        folders = archives[-1:]
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    ensure_tables(client)
    print(f"Loading {len(folders)} run folder(s) into {PROJECT}.{DATASET} ({LOCATION})")
    for folder in folders:
        print(f"{folder.name}:")
        load_folder(client, folder)
    print(f"\nDone. Query it: https://console.cloud.google.com/bigquery?project={PROJECT}&ws=!1m4!1m3!3m2!1s{PROJECT}!2s{DATASET}")


if __name__ == "__main__":
    main()
