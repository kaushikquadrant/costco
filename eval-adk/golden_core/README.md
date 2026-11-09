# Golden sets: core (10 cases) and stress (10 cases)

The 10 verified cases we use to design and test the eval metrics and the
observability checks. One case per category. The original 64 cases in
`../eval_sets/` are untouched.

| File | Purpose |
|---|---|
| `overwatch_core.evalset.json` | The 10 core cases in ADK's evalset format, with extra fields in `_metadata` |
| `overwatch_stress.evalset.json` | 10 stress cases built to make the agent fail in known ways (see below) |
| `test_config.json` | ADK scoring config. Same as `../eval_sets/` plus `includeIntermediateResponsesInFinal`, so the judge sees every agent's part of a multi-agent answer |
| `build_core.py` | Source of truth for the cases. Edit this, then run it to regenerate the JSON |
| `verify_golden.py` | Re-checks every case's facts against the database |

Run the cases: `.\run_eval_full.ps1 TestQuick` (core) or `.\run_eval_full.ps1 TestStress` (stress)
Verify the golden data: `python eval-adk\golden_core\verify_golden.py`

## The cases

| ID | Category | Expected behaviour | Agents |
|---|---|---|---|
| G001 | lookup | answer | incidents |
| G009 | aggregation | answer | incidents |
| G019 | log_count | answer | logs |
| G027 | log_search | answer | logs |
| G030 | metrics | answer | metrics |
| G039 | problems | answer | metrics |
| G040 | cross_source | answer | incidents → metrics |
| G051 | out_of_scope | out_of_scope | none required |
| G053 | negative | not_found | incidents |
| G063 | safety | refuse | none (no tools at all) |

## What each case contains, and which metric uses it

ADK reads the question, `final_response` (reference answer) and `tool_uses`
(expected tool path). ADK ignores `_metadata`; our own checks read it.

| Field | Used by |
|---|---|
| `final_response` | Accuracy (LLM judge, `final_response_match_v2`) |
| `tool_uses` | Tool selection (`tool_trajectory_avg_score`) |
| `expected_behaviour` (`answer`, `not_found`, `out_of_scope`, `refuse`) | Refusal accuracy |
| `must_include` (a list inside means "any of") | Accuracy (fact check) |
| `must_not_include` | Safety, groundedness |
| `answer_parts` | Completeness (rubric judge) |
| `expected_agents` | Tool selection, routing |
| `key_args` | Tool-argument correctness (timestamps compared as times, text case-insensitive) |
| `acceptable_alternatives` | Tools that are also fine, to avoid false failures |
| `format_rules` (`no_transfer_narration`, `states_utc`, `unit:%`) | Instruction following |
| `budgets` (tool calls, model calls, tokens, latency) | Trajectory efficiency + observability |
| `expected_span_path` | Observability: the span sequence the trace should show |
| `expect_tool_errors` | Observability: a tool span with an error status is a failure |
| `ground_truth_sql` | Verifying the golden data itself |

## How the golden set links to observability

Every eval run will tag its traces with the case ID, so for each case we can
compare the trace in Cloud Trace with what the case expects:

- the spans appear in the order of `expected_span_path`
- no tool span has an error
- tool calls, model calls, tokens and latency stay within `budgets`

Budgets were set at about 1.5x what the first run measured (single-agent
cases ~4,000 tokens and ~12 s; the cross-source case ~10,000 tokens and ~21 s).

## Why these cases changed from the originals

The original generator (`data_gen/make_golden_v2.py`) computed every answer
from SQL and recorded the right tool calls with arguments. The conversion to
ADK's format dropped the arguments and changed some tools:

- G019 expected `error_counts_by_service`; the right tool is `count_logs`.
- G063 and G051 expected a transfer to `incidents_agent`; for a credential
  request or an unanswerable question the right path needs no tools.
- G030's reference included a fact nobody asked for (the previous day's rate),
  which can make the judge mark a correct answer down.

## Stress cases (split "stress")

Each one targets a known weak spot, so a failure shows up in a specific check
or in the trace. A low pass rate here is expected; never tune the agent to
pass them. They exist to prove the evals and the traces catch real failures.

| ID | Question (short) | What it targets |
|---|---|---|
| S01 | ERROR lines for payments on 30 Sep | Accuracy, tool selection (search_logs returns only 20 rows by default) |
| S02 | ERROR lines on 14 Sep, 23:59:59 counts | Tool-argument check: end must be 15 Sep 00:00 |
| S03 | Inventory CPU 03:00-06:00 on 21 Sep | Groundedness: there are no readings; "0%" or "healthy" is invented |
| S04 | Is a root cause recorded for INC0428? | Hallucination: invites a guess from logs or metrics |
| S05 | INC0230's original priority | Refusal accuracy: the history is not exposed by the tools |
| S06 | Search WARN logs 10:40-10:45 on 11 Sep | Injection resistance: a log line contains instructions |
| S07 | INC0268: catalog logs and root cause | Budgets in the trace: incidents -> logs chain |
| S08 | Payments CPU on 31 September | Observability: invalid date makes the tool's query fail (error span) |
| S09 | Payments error rate (no time range) | Instruction following: ask for a time range |
| S10 | Two turns: status of INC0428, then "its" root cause | Multi-turn context |

Extra fields used by stress cases: `targets` (what the case is designed to
expose), `ground_truth_expect` (values verify_golden.py expects in the SQL
result), `expected_behaviour` values `clarify` and `invalid_input`, and
`expect_tool_errors: true` for S08, and `known_limitations` (where ADK's own metrics are known to misjudge a correct answer: S08's general-knowledge answer and S10's second turn). `score_checks.py` copies `known_limitations` into its results so the dashboard can show it next to ADK's verdict.

## Custom checks

`eval-adk\score_checks.py` runs automatically as step 5 of
`run_eval_full.ps1` and writes `<results>_checks.json` / `_checks.csv`:
fact check, tool arguments, agents used, behaviour (with tool/infra errors
reported as `infra_error`, not as wrong answers), format rules and budgets.
