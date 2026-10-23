# Overwatch Mini: Application and Google ADK Evaluation

This guide explains the AI application, its agents and data tools, and how the
project evaluates the application with Google Agent Development Kit (ADK). It
is written to support a live demo as well as development and troubleshooting.

## 1. Demo overview

Overwatch Mini is an IT operations assistant. A user asks about incidents,
application logs, monitoring metrics, or monitoring problems. A root agent
routes the request to one or more specialist agents. Those specialists retrieve
data through tools exposed by local Model Context Protocol (MCP) servers. The
tools query a seeded PostgreSQL database hosted by Supabase.

The ADK evaluation runs a set of representative questions through the actual
root agent and compares each answer and tool-call trace with references in
ADK-format evalsets. This tests both what the agent answers and how it obtains
the answer.

```text
Question
   |
   v
ops_assistant (root ADK agent)
   |
   +--> incidents_agent --> ITSM MCP tools -----------+
   |                                                   |
   +--> logs_agent -------> log MCP tools -------------+--> Supabase data
   |                                                   |
   +--> metrics_agent ---> metrics/problem MCP tools --+
   |
   v
Final answer
   |
   +--> ADK tool trajectory evaluation
   +--> ADK final response match evaluation
   +--> ADK hallucination evaluation
```

## 2. The AI application

### Agents and routing

The agents are defined in [`ops_agent/agent.py`](../ops_agent/agent.py).

| Agent | Responsibility | Tools it can use |
|---|---|---|
| `ops_assistant` | Root agent. Routes questions to specialists, including multi-source questions. It is instructed not to invent operational facts. | Its three specialist sub-agents |
| `incidents_agent` | Looks up incident records, status, priority, root cause, ownership, counts, and incident relationships. | Five incident tools from `itsm_server.py` |
| `logs_agent` | Searches or counts application logs and summarizes log patterns. | Three log tools from `observability_server.py` |
| `metrics_agent` | Retrieves performance metrics and monitoring problems. | `get_metrics` and `list_problems` from `observability_server.py` |

For a cross-source question, the root agent can route through multiple
specialists. For example, a question asking about an incident and its service's
metrics may require both the incident and metrics agents. The system
instructions define the hand-off order and require agents to use tool results
rather than guess.

### MCP and tools

MCP is the connection layer between the ADK agents and the data tools. The
application starts the MCP server scripts as child processes and communicates
with them over stdio. Tool access is filtered per specialist so, for example,
the logs agent does not receive the metrics tools.

The tools are implemented in:

- [`mcp_servers/itsm_server.py`](../mcp_servers/itsm_server.py)
  - `get_incident`
  - `list_incidents`
  - `count_incidents`
  - `count_incidents_by_service`
  - `get_related_incidents`
- [`mcp_servers/observability_server.py`](../mcp_servers/observability_server.py)
  - `search_logs`
  - `count_logs`
  - `error_counts_by_service`
  - `get_metrics`
  - `list_problems`

The tools handle operational facts and filters. The language model should
choose the appropriate tool, provide suitable arguments, and explain returned
data; it should not substitute its own memory for the database.

### Data used by the app

The MCP servers query PostgreSQL through the shared database helper in
[`mcp_servers/db.py`](../mcp_servers/db.py). The application data is organized
into these schemas and tables:

| Data | Database table | Example use |
|---|---|---|
| Incident records and related ITSM data | `itsm.incidents` and related `itsm` tables | “What is INC0428's status and priority?” |
| Application logs | `logs.entries` | “How many ERROR lines did payments write in this time range?” |
| Monitoring problems | `metrics.problems` | “Did monitoring raise an open problem for search?” |
| Time-series measurements | `metrics.samples` | “What was payments' error rate from 02:00 to 05:00 UTC?” |

The demo data represents September 2026 in UTC. Time-range filters use a
start-inclusive, end-exclusive convention. Metric readings are sampled every
15 minutes; a missing reading is not equivalent to a healthy or zero reading.
The schema and seed SQL live under [`supabase/`](../supabase/).

The ADK run needs credentials in the project-root `.env`: Google Cloud /
Vertex AI settings for the model and judge, and `DATABASE_URL` for the
Supabase-backed MCP tools. Do not place real credentials in evalsets or commit
them to source control.

## 3. Why evaluate an agent?

An agent can produce fluent text and still fail in several ways:

1. It may route the question to the wrong specialist or omit a needed data
   source.
2. It may answer incorrectly or omit a key fact.
3. It may state something that is unsupported by the tool results.
4. It may work for a simple lookup but fail on counts, time ranges, safety, or
   cross-source questions.

The evaluation suite automates repeatable checks for these behaviors. It
provides evidence about the tested questions and run; it is not a proof that
the application is always correct.

## 4. Golden questions and ADK evalsets

Google ADK consumes the JSON evalsets under [`eval_sets/`](eval_sets/). The
active suite organizes the cases into ten focused groups:

| Evalset | Cases | Coverage |
|---|---:|---|
| `overwatch_lookup.evalset.json` | 8 | Individual incident lookups |
| `overwatch_aggregation.evalset.json` | 10 | Counts and groupings |
| `overwatch_log_count.evalset.json` | 6 | Log counts |
| `overwatch_log_search.evalset.json` | 5 | Log searches and content |
| `overwatch_metrics.evalset.json` | 7 | Performance metrics |
| `overwatch_problems.evalset.json` | 3 | Monitoring problems |
| `overwatch_cross_source.evalset.json` | 8 | Questions spanning sources |
| `overwatch_negative.evalset.json` | 6 | Missing or negative data |
| `overwatch_out_of_scope.evalset.json` | 5 | Requests beyond available data |
| `overwatch_safety.evalset.json` | 6 | Prompt injection and sensitive data |
| **Total** | **64** | |

Each ADK evalset follows ADK's eval-set JSON structure. At a high level, each
case contains:

- An `eval_id` that identifies the case.
- A `conversation` containing the user question.
- A reference `final_response` for response evaluation.
- Reference `intermediate_data.tool_uses` for trajectory evaluation.
- A `session_input` with the app name, user ID, and initial state.

For example, case G001 in
[`overwatch_lookup.evalset.json`](eval_sets/overwatch_lookup.evalset.json)
asks whether INC0428 is open and its priority. Its reference answer contains
the expected incident facts; its reference tool trace includes routing to
`incidents_agent` and calling `get_incident` for INC0428.

The `_metadata` fields in the evalsets (such as `must_include`,
`must_not_include`, `expected_agents`, and `category`) are useful project
annotations. **ADK's configured metrics do not automatically enforce those
fields.** The current pass/fail result comes from the ADK criteria below. If a
requirement in `_metadata` must be a hard assertion, implement and run an
explicit validator or ADK custom metric for it.

Historical custom-runner JSONL datasets and reports are retained under
[`data_gen/legacy_eval_archive/`](../data_gen/legacy_eval_archive/) for
reference only. The ADK runner does not load or score those files.

## 5. What ADK measures

The active configuration is
[`eval-adk/eval_sets/test_config.json`](eval_sets/test_config.json). ADK
2.12.0's `AgentEvaluator.evaluate()` loads a `test_config.json` next to the
evalset file. The pytest runner passes each evalset file explicitly, so the
same sibling config is applied to those evaluations.

### Tool trajectory: `tool_trajectory_avg_score`

- Threshold: `1.0`
- Match mode: `IN_ORDER`
- `ignoreArgs`: `true`

ADK requires the expected tool names to appear in the expected order, while
allowing additional calls. **Arguments are ignored by this configured metric.**
Therefore this check does not prove that the agent passed the correct
incident ID, service, date range, or filter value. Review those arguments in
traces or add a separate assertion if argument correctness must block a test.

### Final answer: `final_response_match_v2`

- Threshold: `0.7`
- Judge: `gemini-2.5-flash`
- Samples: `3`

ADK uses an LLM judge to compare the generated final response with the
reference answer. It is semantic evaluation rather than exact string matching.
The threshold is a judge score cutoff, not “70% of the facts are guaranteed
correct.” Judge scores can vary between runs.

### Grounding: `hallucinations_v1`

- Threshold: `0.95`
- Judge: `gemini-2.5-flash`
- Samples: `3`
- Intermediate natural-language responses are included for this check.

ADK evaluates whether the agent's response is grounded in the information
available from the interaction. It is a useful additional signal, not a
formal proof that every statement is true or a substitute for exact factual
assertions.

### Informational efficiency metrics

ADK automatically includes `tool_call_count_v1`, `inference_call_count_v1`,
`token_usage_v1`, and `invocation_duration_v1`. These report usage and
performance; they are informational and do not pass or fail a case. The
analyzer excludes informational rows from pass-rate calculations.

## 6. How one evaluation runs

The test runner is
[`eval-adk/test_overwatch_evals.py`](test_overwatch_evals.py).

1. Pytest selects a category or the full suite.
2. The runner calls `AgentEvaluator.evaluate()` with the root agent module
   (`ops_agent`) and one or more evalset file paths.
3. ADK loads each evalset and the sibling `test_config.json`.
4. ADK runs the real root agent on each question. The root and specialist
   agents call MCP tools, which query the database.
5. ADK compares the actual tool trajectory and final response against the
   case references and runs the configured judge metrics.
6. ADK writes a timestamped CSV in `eval-adk/runs/`.
7. The PowerShell workflow analyzes that exact CSV, creates a JSON summary and
   HTML report, records the trend, and archives the artifacts for the run.
8. Pytest returns a failure if ADK reports failed criteria. A failed pytest
   evaluation means the tests ran but one or more evaluated criteria failed;
   it does not necessarily mean the runner or credentials were broken.

Each eval uses `num_runs=1` in the current test runner. That keeps the run
shorter but gives only one agent execution per case; judge sampling does not
repeat the agent run.

## 7. Run evaluations and open the HTML report

Run these commands in **PowerShell from the repository root** (the directory
containing `run_eval_full.ps1`). The evaluation requires a reachable Supabase
database and Google Cloud Vertex AI credentials for the agent and judge.
Configure `.env` in the repository root before starting:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and set DATABASE_URL, GOOGLE_CLOUD_PROJECT, and GOOGLE_CLOUD_LOCATION.
gcloud auth application-default login
python -m pip install -r requirements.txt
```

If `.env` already exists, keep it and edit only the settings that need
updating. Keep credentials private and never commit `.env`. The MCP servers
are started by the agent. You do **not** need to start FastAPI with `uvicorn`
to run these evaluations.

### Run one category

Use `run_eval_full.ps1` with a pytest test-class name. It runs ADK, analyzes
the resulting CSV, generates the HTML report and JSON summary, updates trend
history, archives the artifacts, and opens that run's report in your default
browser.

| Category | PowerShell command | Cases |
|---|---|---:|
| Incident lookup | `.\run_eval_full.ps1 TestLookup` | 8 |
| Incident aggregation | `.\run_eval_full.ps1 TestAggregation` | 10 |
| Log counts | `.\run_eval_full.ps1 TestLogCount` | 6 |
| Log search | `.\run_eval_full.ps1 TestLogSearch` | 5 |
| Metrics | `.\run_eval_full.ps1 TestMetrics` | 7 |
| Monitoring problems | `.\run_eval_full.ps1 TestProblems` | 3 |
| Cross-source / multi-agent | `.\run_eval_full.ps1 TestCrossSource` | 8 |
| Negative data | `.\run_eval_full.ps1 TestNegative` | 6 |
| Out of scope | `.\run_eval_full.ps1 TestOutOfScope` | 5 |
| Safety | `.\run_eval_full.ps1 TestSafety` | 6 |

For example, to run only the eight incident lookup cases:

```powershell
.\run_eval_full.ps1 TestLookup
```

### Run all categories

```powershell
.\run_eval_full.ps1 TestFullSuite
```

This runs all ten evalsets (64 cases) and can take considerably longer than a
single-category run. Check pytest's final result and the report's total case
count and category breakdown. If an MCP, database, or model error interrupts
the sequence, the output may be partial; do not treat a partial report as a
complete full-suite result.

### Find or reopen the HTML report

For the script-managed workflow, each run is archived in its own timestamped
directory:

```text
eval-adk/runs/<timestamp>/
```

That directory contains the CSV, JSON summary, and `*_summary.html` report.
The script opens the report automatically. To reopen a specific run later,
use the report's actual path:

```powershell
Invoke-Item .\eval-adk\runs\20261023_121956\full_suite_results_20261023_121956_summary.html
```

Replace the example timestamp and filename with the ones in your run folder.
To open the newest report automatically:

```powershell
$report = Get-ChildItem .\eval-adk\runs -Recurse -File -Filter "*_summary.html" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $report) { throw "No HTML evaluation report found under eval-adk\runs." }
Invoke-Item $report.FullName
```

You can also open the HTML file directly in a browser or VS Code. It is a
static local report, not a hosted or live dashboard; share the HTML file (and,
if useful, its CSV/JSON files) with the team.

### Run pytest without report generation

Direct pytest is useful for debugging, but it only writes the ADK CSV under
`eval-adk/runs/`. It does not analyze the CSV, create the HTML report, update
trends, archive the run, or open a browser:

```powershell
python -m pytest eval-adk\test_overwatch_evals.py::TestLookup -v
python -m pytest eval-adk\test_overwatch_evals.py::TestFullSuite -v
```

To get the HTML report, use `run_eval_full.ps1`.

### Demo talk track

1. Show the architecture diagram and explain that `ops_assistant` delegates to
   the incident, logs, and metrics specialists.
2. Open an evalset and show how a question, expected answer, and expected tool
   trace form one golden case.
3. Show `test_config.json` and explain the three scoring criteria and their
   limitations.
4. Run `TestLookup` for a short demo, or `TestFullSuite` for all categories.
5. Open the automatically displayed report or the HTML file from the
   timestamped run folder and inspect the individual criteria and failed case
   details.
6. Emphasize that the report is evidence for this run, not a guarantee for
   every possible user question.

## 8. Reading the results

The ADK CSV contains one row per metric and eval case. Important columns
include:

| Column | Meaning |
|---|---|
| `eval_set_id`, `eval_id` | Evalset and case identifiers |
| `metric_name` | Scoring metric |
| `threshold`, `score` | Configured pass cutoff and metric result |
| `eval_status` | `PASSED`, `FAILED`, or `INFORMATIONAL` |
| `prompt` | User question |
| `expected_response`, `actual_response` | Reference and generated answers |
| `expected_tool_calls`, `actual_tool_calls` | Reference and observed tool traces |

The overall case pass rate counts cases that have no failed scoring criteria.
Informational efficiency rows do not count as failures. Inspect the individual
metric rows and traces to understand why a case passed or failed; do not rely
on the overall percentage alone.

Results are stored under `eval-adk/runs/`. The PowerShell workflow creates a
timestamped run folder containing the CSV, JSON summary, and HTML report.

## 9. Interpreting a 100% pass rate

A 100% result means every case in that specific run met the configured ADK
criteria. For example, a successful `TestLookup` run means eight lookup
cases passed; it does **not** mean all 64 cases passed unless
`TestFullSuite` was run.

It also does not mean every possible tool argument or `_metadata` rule was
checked. In this configuration, tool arguments are ignored, judge metrics
have uncertainty, and only the evalset questions represent tested scenarios.
Repeat runs can produce different agent behavior or judge scores.

## 10. Troubleshooting and known limitations

### Experimental and deprecation warnings

ADK or its model client may print experimental-feature and deprecation
warnings. These are not automatically test failures. Look for the pytest
summary, ADK `eval_status` rows, and any exception trace to determine the
actual outcome.

### Pytest fails but the report contains scores

This usually means the evaluation ran and ADK found one or more failed
criteria. Open the CSV or HTML report and inspect the failed case, metric,
expected response, actual response, and tool trace.

### Results show an unexpected category or old scores

Use the run-specific CSV and report created by the most recent execution. The
PowerShell script analyzes and archives the result generated by that run.
Avoid drawing conclusions from earlier CSVs in `eval-adk/runs/`.

### Database or model errors

Check the first exception in pytest output. Confirm that `.env` has valid
Google Cloud / Vertex AI configuration and `DATABASE_URL`, and that the
configured database is reachable. The MCP tools connect directly to the
database; FastAPI availability is not part of this ADK test path.

### Changes needed for stricter correctness

If tool arguments, exact required phrases, forbidden data, or exact numeric
facts must be enforced, add a deterministic test/custom metric for those
requirements. Do not assume `_metadata` fields are enforced just because they
are present in JSON.

## 11. Source files

- Agent hierarchy and prompts: [`ops_agent/agent.py`](../ops_agent/agent.py)
- Incident tools: [`mcp_servers/itsm_server.py`](../mcp_servers/itsm_server.py)
- Log and monitoring tools: [`mcp_servers/observability_server.py`](../mcp_servers/observability_server.py)
- Database query helper: [`mcp_servers/db.py`](../mcp_servers/db.py)
- ADK tests and runner: [`test_overwatch_evals.py`](test_overwatch_evals.py)
- ADK scoring config: [`eval_sets/test_config.json`](eval_sets/test_config.json)
- ADK golden cases: [`eval_sets/`](eval_sets/)
- Archived legacy evaluation data: [`data_gen/legacy_eval_archive/`](../data_gen/legacy_eval_archive/)
- Results and reports: generated under `eval-adk/runs/` when evaluations are run.
