# Overwatch Mini

Overwatch Mini is an AI assistant for IT operations. A root Google ADK agent
routes questions to incident, log, and metrics specialists. The specialists
use tools exposed by two local Model Context Protocol (MCP) servers to query
Supabase PostgreSQL.

```text
User
 |
 v
ops_assistant
 |-- incidents_agent -- ITSM MCP tools --------\
 |-- logs_agent ------ observability MCP tools --+--> Supabase PostgreSQL
 '-- metrics_agent --- observability MCP tools --/    itsm, logs, metrics
```

- `ops_agent/agent.py` defines the root and specialist agents.
- `mcp_servers/` contains the ITSM and observability MCP servers. SQL is
  implemented in the tools; the model does not write SQL.
- `docs/` contains the chat page, served by the FastAPI backend in `server.py`.
- `supabase/` and `data_gen/` define and seed the synthetic September 2026 data.

## Set up a local environment

Requirements: Python 3.11 or newer, Git, access to the project's Supabase
database, and Google Cloud Vertex AI access for the model and ADK judge.

```powershell
git clone https://github.com/KavithaPadala1/costco_demo_overwatch.git
cd costco_demo_overwatch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

Populate `.env` with the approved `DATABASE_URL`, Google Cloud project, and
location. Keep real credentials out of source control and do not send `.env`
through chat or email; use your team's approved secret-sharing process. The
example file is configured for Vertex AI. Authenticate with an account that
has access to the project:

```powershell
gcloud auth application-default login
```

The ADK evals connect to Supabase directly through MCP; starting the web
backend is not required to run them. If using the shared database, **do not
run `data_gen/load_db.py`** because it replaces the database tables.

## Run Google ADK evaluations

All active evaluation cases and scoring configuration are under
[`eval-adk/`](eval-adk/). Read the
[ADK evaluation guide](eval-adk/README.md) for details on the app architecture,
evalset structure, scoring criteria, and troubleshooting.

From the project root in PowerShell:

```powershell
# Short run: 8 incident lookup cases
.\run_eval_full.ps1 TestLookup

# Full run: all 10 categories (64 cases)
.\run_eval_full.ps1 TestFullSuite
```

The script runs pytest, analyzes the CSV from that run, generates an HTML
report, updates trend history, archives the run artifacts, and opens the
report. Results are saved under `eval-adk/runs/<timestamp>/` as CSV, JSON
summary, and HTML. The report is a static local file, not a hosted dashboard.

Available category test classes are `TestLookup`, `TestAggregation`,
`TestLogCount`, `TestLogSearch`, `TestMetrics`, `TestProblems`,
`TestCrossSource`, `TestNegative`, `TestOutOfScope`, and `TestSafety`.
For example:

```powershell
.\run_eval_full.ps1 TestAggregation
```

To run pytest without report generation:

```powershell
python -m pytest eval-adk\test_overwatch_evals.py::TestLookup -v
python -m pytest eval-adk\test_overwatch_evals.py::TestFullSuite -v
```

Direct pytest runs write result CSVs to `eval-adk/runs/`, but do not create
the HTML report or timestamped archive folder. Check the pytest exit code and
report before treating a run as successful. A full run should include all ten
eval categories and 64 cases; if it stops on an MCP or model error, the report
may represent only a partial run.

## Understand the evaluation

Each ADK eval case contains a user prompt and reference answer, with expected
tool calls where applicable. The criteria in
[`eval-adk/eval_sets/test_config.json`](eval-adk/eval_sets/test_config.json)
check tool trajectory, semantic answer match, and grounding. Informational
efficiency metrics are not included in pass/fail rates. Tool trajectory
currently ignores tool arguments, and LLM-judge metrics are estimates rather
than proof of factual correctness. The evalset questions and their known
limitations are described in the [ADK evaluation guide](eval-adk/README.md).

The old custom evaluation runner is no longer used. Its JSONL data and
historical reports have been preserved under
[`data_gen/legacy_eval_archive/`](data_gen/legacy_eval_archive/); they are
reference-only and are not loaded by the ADK test runner.

## Project files

| Path | Purpose |
|---|---|
| `ops_agent/agent.py` | Agent hierarchy, instructions, and MCP tool assignment |
| `mcp_servers/` | ITSM and observability MCP tools plus database access |
| `eval-adk/eval_sets/` | Google ADK JSON evalsets and scoring configuration |
| `eval-adk/test_overwatch_evals.py` | Category and full-suite ADK tests |
| `eval-adk/analyze_results.py` | CSV-to-JSON evaluation analysis |
| `eval-adk/generate_report.py` | Static HTML report generation |
| `run_eval_full.ps1` | End-to-end evaluation and report workflow |
| `supabase/`, `data_gen/` | Database schema, seed data, and data generation |
| `docs/`, `server.py` | Chat UI and local/hosted API backend |

## Troubleshooting

- **MCP/database connection errors:** verify `DATABASE_URL` and that Supabase
  is reachable. Use the Supabase session-pooler connection string where
  required by your network.
- **Vertex AI permission or model errors:** confirm the selected Google Cloud
  project, Vertex AI access, and Application Default Credentials.
- **Missing Python modules:** activate `.venv` and run
  `python -m pip install -r requirements.txt`.
- **Pytest fails but a report exists:** inspect failed criteria, actual tool
  calls, and the first exception in the pytest output. A report can be created
  even when evaluation criteria fail.
- **Fewer than 64 cases in a full-suite report:** treat it as partial, not as a
  complete full-suite result; investigate the category that stopped the run.

## Run the chat application

To use the local chat UI, start the API from the project root:

```powershell
uvicorn server:app --port 8080
```

Then open `http://localhost:8080`. The ADK development UI can also be started
with `adk web`; select `ops_agent` to inspect agent and tool activity.
