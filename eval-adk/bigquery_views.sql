-- Views behind the Looker Studio dashboard (Day 5). Applied by: python eval-adk/load_bigquery.py --views
-- @DS is replaced with `<project>.<dataset>`. Statements are separated by a line holding only ";".

-- Prices per 1M tokens, filled in by hand (look up current Vertex AI prices). NULL = cost not shown.
CREATE TABLE IF NOT EXISTS @DS.model_prices (
  model STRING, input_per_1m_usd FLOAT64, output_per_1m_usd FLOAT64, noted_on DATE)
;
-- One row per run: what setup it used, so the dashboard never mixes models or golden sets.
CREATE OR REPLACE VIEW @DS.v_runs AS
SELECT
  r.run_id,
  ANY_VALUE(r.run_started_at) AS run_started_at,
  ANY_VALUE(r.suite) AS suite,
  COUNT(DISTINCT r.eval_id) AS cases,
  -- Flash-Lite from run 20261030_231011 on; traced runs record the model themselves.
  COALESCE(ANY_VALUE(t.agent_model),
           IF(r.run_id >= '20261030_231011', 'gemini-3.5-flash-lite', 'gemini-2.5-flash')) AS agent_model,
  IF(r.run_id >= '20261030_231011', 'gemini-3.5-flash', 'gemini-2.5-flash') AS judge_model,
  IF(LOGICAL_AND(r.eval_set_id IN ('overwatch_core', 'overwatch_stress')), 'core-v1', 'legacy') AS golden_version,
  STARTS_WITH(ANY_VALUE(r.suite), 'sabotage') AS is_sabotage,
  REGEXP_EXTRACT(ANY_VALUE(r.suite), r'^sabotage_(.+)$') AS sabotage_mode,
  COUNTIF(r.trace_id IS NOT NULL) > 0 AS traced
FROM @DS.eval_results r
LEFT JOIN @DS.case_traces t ON t.run_id = r.run_id
GROUP BY r.run_id
;
-- One row per query per run (per repeat for consistency runs): every per-query metric in one place.
CREATE OR REPLACE VIEW @DS.v_case_results AS
WITH adk AS (
  SELECT run_id, eval_id, IFNULL(run_index, 1) AS run_index,
    ANY_VALUE(eval_set_id) AS eval_set_id,
    ANY_VALUE(prompt) AS prompt,
    ANY_VALUE(expected_response) AS expected_answer,
    ANY_VALUE(actual_full_response) AS answer,
    ANY_VALUE(trace_url) AS trace_url,
    AVG(IF(metric_name = 'final_response_match_v2', score, NULL)) AS correctness_score,
    LOGICAL_AND(IF(metric_name = 'final_response_match_v2', eval_status = 'PASSED', NULL)) AS correctness_passed,
    AVG(IF(metric_name = 'hallucinations_v1', score, NULL)) AS groundedness_score,
    LOGICAL_AND(IF(metric_name = 'hallucinations_v1', eval_status = 'PASSED', NULL)) AS groundedness_passed,
    AVG(IF(metric_name = 'rubric_based_final_response_quality_v1', score, NULL)) AS rubric_score,
    LOGICAL_AND(IF(metric_name = 'rubric_based_final_response_quality_v1', eval_status = 'PASSED', NULL)) AS rubric_passed,
    AVG(IF(metric_name = 'tool_trajectory_avg_score', score, NULL)) AS trajectory_score,
    LOGICAL_AND(IF(metric_name = 'tool_trajectory_avg_score', eval_status = 'PASSED', NULL)) AS trajectory_passed,
    STRING_AGG(IF(metric_name = 'rubric_based_final_response_quality_v1', rubric_scores, NULL), ' ') AS rubric_details
  FROM @DS.eval_results
  GROUP BY run_id, eval_id, run_index
)
SELECT
  v.run_started_at, v.suite, v.agent_model, v.judge_model, v.golden_version, v.is_sabotage, v.sabotage_mode,
  a.run_id, a.eval_id, a.run_index, a.eval_set_id,
  c.split, c.category, c.expected_behaviour, c.actual_behaviour,
  a.prompt, a.expected_answer, a.answer,
  -- response quality
  a.correctness_score, a.correctness_passed, c.fact_check_passed,
  a.groundedness_score, a.groundedness_passed,
  a.rubric_score, a.rubric_passed, c.rubric_failed AS rubric_said_no, a.rubric_details,
  c.format_passed AS instruction_following_passed,
  -- agents and tools
  a.trajectory_score, a.trajectory_passed, c.agents_passed, c.tool_args_passed AS tool_arguments_passed,
  c.behaviour_passed, c.budgets_passed,
  -- overall
  -- safety (checked on every query)
  c.leakage_passed, c.tools_allowed_passed,
  c.checks_passed, c.passed_all AS task_success, c.problems, c.known_limitations, c.infra_error,
  -- cost and performance (traced runs have the split; older runs only ADK's latency/tokens)
  -- One latency definition for every run (ADK's agent run time), so trends compare like with like.
  -- The trace's total (which also covers the eval wrapper) is kept separately.
  COALESCE(c.latency_s, t.total_s) AS latency_s, t.total_s AS traced_total_s,
  t.model_s, t.tool_s, t.other_s, t.agent_wait_s,
  COALESCE(t.total_tokens, c.tokens) AS total_tokens, t.input_tokens, t.output_tokens,
  COALESCE(t.model_calls, c.model_calls) AS model_calls, COALESCE(t.tool_calls, c.tool_calls) AS tool_calls,
  t.biggest_call_agent, t.biggest_call_input_tokens, t.tokens_by_agent,
  ROUND((t.input_tokens * p.input_per_1m_usd + t.output_tokens * p.output_per_1m_usd) / 1e6, 6) AS cost_usd,
  t.cached_input_tokens,
  -- had_error: TRUE/FALSE only when it can be known (the query was traced, or the checks saw an infra error);
  -- NULL for untraced queries, so unknown is never reported as "no error".
  t.error_spans, t.error_kinds,
  CASE WHEN IFNULL(c.infra_error, FALSE) THEN TRUE
       WHEN t.trace_id IS NULL THEN NULL
       ELSE t.error_spans IS NOT NULL END AS had_error,
  t.trace_id, a.trace_url
FROM adk a
JOIN @DS.v_runs v USING (run_id)
LEFT JOIN @DS.eval_checks c ON c.run_id = a.run_id AND c.eval_id = a.eval_id
LEFT JOIN @DS.case_traces t ON t.run_id = a.run_id AND t.case_id = a.eval_id AND t.case_run = a.run_index
LEFT JOIN @DS.model_prices p ON p.model = v.agent_model
;
-- One row per run: the rates and distributions (these only make sense across queries).
CREATE OR REPLACE VIEW @DS.v_run_summary AS
SELECT
  run_id, ANY_VALUE(run_started_at) AS run_started_at, ANY_VALUE(suite) AS suite,
  ANY_VALUE(agent_model) AS agent_model, ANY_VALUE(golden_version) AS golden_version,
  ANY_VALUE(is_sabotage) AS is_sabotage, COUNT(*) AS queries,
  -- quality (NULL when a run has no value for it, e.g. runs before the checks existed)
  AVG(CAST(task_success AS INT64)) AS task_success_rate,
  AVG(CAST(checks_passed AS INT64)) AS checks_pass_rate,
  AVG(CAST(correctness_passed AS INT64)) AS correctness_rate,
  AVG(groundedness_score) AS avg_groundedness,
  AVG(CAST(rubric_passed AS INT64)) AS rubric_pass_rate,
  AVG(CAST(tool_arguments_passed AS INT64)) AS tool_argument_accuracy,
  AVG(CAST(trajectory_passed AS INT64)) AS tool_selection_accuracy,
  AVG(CAST(instruction_following_passed AS INT64)) AS instruction_following_rate,
  -- refusals: right when it should decline; over-refusal when it declines a normal question
  SAFE_DIVIDE(COUNTIF(expected_behaviour IN ('refuse', 'out_of_scope') AND actual_behaviour IN ('refuse', 'not_found')),
              COUNTIF(expected_behaviour IN ('refuse', 'out_of_scope'))) AS refusal_accuracy,
  SAFE_DIVIDE(COUNTIF(expected_behaviour = 'answer' AND actual_behaviour = 'refuse'),
              COUNTIF(expected_behaviour = 'answer')) AS over_refusal_rate,
  -- performance and cost
  APPROX_QUANTILES(latency_s, 100)[OFFSET(50)] AS latency_p50_s,
  APPROX_QUANTILES(latency_s, 100)[OFFSET(95)] AS latency_p95_s,
  APPROX_QUANTILES(latency_s, 100)[OFFSET(99)] AS latency_p99_s,
  AVG(total_tokens) AS avg_tokens, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
  AVG(model_calls) AS avg_model_calls, AVG(tool_calls) AS avg_tool_calls,
  SUM(cost_usd) AS cost_usd, SAFE_DIVIDE(SUM(cost_usd), COUNTIF(task_success)) AS cost_per_success_usd,
  -- reliability: SLO = answered within 20 s with no error.
  -- Errors are only knowable for traced queries: these are computed over traced queries and are
  -- NULL for runs without trace data (unknown, not zero).
  AVG(IF(trace_id IS NULL, NULL, CAST(had_error AS INT64))) AS error_rate,
  AVG(IF(trace_id IS NULL, NULL, CAST(latency_s <= 20 AND NOT had_error AS INT64))) AS slo_compliance,
  IF(COUNTIF(trace_id IS NOT NULL) = 0, NULL, COUNTIF(error_kinds LIKE '%rate_limit%')) AS rate_limit_hits,
  IF(COUNTIF(trace_id IS NOT NULL) = 0, NULL, COUNTIF(error_kinds LIKE '%timeout%')) AS timeouts,
  IF(COUNTIF(trace_id IS NOT NULL) = 0, NULL, COUNTIF(error_kinds LIKE '%tool_error%')) AS tool_errors,
  -- safety
  1 - AVG(CAST(leakage_passed AS INT64)) AS leakage_rate,
  1 - AVG(CAST(tools_allowed_passed AS INT64)) AS unauthorized_action_rate,
  -- injection resistance: the safety cases (injection in the question or in the data) handled safely
  AVG(IF(category = 'safety', CAST(behaviour_passed AND leakage_passed AS INT64), NULL)) AS injection_block_rate,
  -- cost efficiency: share of input tokens served from the context cache (0 until a cache is configured)
  SAFE_DIVIDE(SUM(cached_input_tokens), SUM(input_tokens)) AS cache_hit_rate,
  COUNTIF(checks_passed IS NOT NULL) AS queries_with_checks
FROM @DS.v_case_results
GROUP BY run_id
;
-- Spans for the per-question waterfall (Day 6). Same field names as v_case_results (eval_id, run_id,
-- agent_model, suite) so one question/run picker filters both. One row per step, numbered in time order,
-- so a stacked bar (invisible start offset + visible duration) draws a waterfall.
CREATE OR REPLACE VIEW @DS.v_spans AS
WITH s AS (
  SELECT
    sp.run_id, sp.case_id AS eval_id, sp.case_run AS run_index, sp.trace_id, sp.span_id, sp.parent_span_id,
    sp.name, sp.kind, sp.agent, sp.tool, sp.model, sp.status, sp.error_kind, sp.error_detail,
    sp.start_offset_s, sp.duration_s, sp.input_tokens, sp.output_tokens, sp.cached_input_tokens,
    CASE sp.kind
      WHEN 'invocation' THEN 'whole question'
      WHEN 'agent' THEN CONCAT('agent: ', sp.agent)
      WHEN 'model_call' THEN CONCAT('model call (', sp.agent, ')')
      WHEN 'tool' THEN CONCAT('tool: ', IFNULL(sp.tool, REGEXP_EXTRACT(sp.name, r'execute_tool (.+)')))
      ELSE sp.name END AS step_name
  FROM @DS.spans sp
  WHERE sp.kind IN ('invocation', 'agent', 'model_call', 'tool')
)
SELECT
  v.run_started_at, v.suite, v.agent_model, v.golden_version, v.is_sabotage, v.sabotage_mode,
  s.*,
  ROUND(s.start_offset_s + s.duration_s, 3) AS end_offset_s,
  ROW_NUMBER() OVER (PARTITION BY s.run_id, s.eval_id, s.run_index ORDER BY s.start_offset_s, s.duration_s DESC) AS step,
  FORMAT('%02d · %s', ROW_NUMBER() OVER (PARTITION BY s.run_id, s.eval_id, s.run_index
                                         ORDER BY s.start_offset_s, s.duration_s DESC), s.step_name) AS step_label,
  s.status = 'ERROR' AS is_error
FROM s
JOIN @DS.v_runs v USING (run_id)
;
-- One case unpivoted into labelled rows (Detail | Value) for the dashboard's case drill-down.
-- Missing values show as "–".
CREATE OR REPLACE VIEW @DS.v_case_details AS
SELECT
  c.run_id, c.eval_id, c.run_index, c.suite, c.agent_model, c.golden_version,
  d.ord, d.detail,
  IFNULL(NULLIF(TRIM(d.value), ''), '–') AS value
FROM @DS.v_case_results c,
UNNEST([
  STRUCT(1 AS ord, 'Case' AS detail, CONCAT(c.eval_id, ' · ', IFNULL(c.category, '–')) AS value),
  STRUCT(2, 'Question', c.prompt),
  STRUCT(3, 'Expected action', c.expected_behaviour),
  STRUCT(4, "Agent's action", c.actual_behaviour),
  STRUCT(5, 'Reference answer', c.expected_answer),
  STRUCT(6, "Agent's answer", c.answer),
  STRUCT(7, 'Result', CASE WHEN c.task_success THEN '✓ Passed all checks'
                           WHEN NOT c.task_success THEN '✗ Failed' END),
  STRUCT(8, 'Failed checks', c.problems),
  STRUCT(9, "Judge's concerns", c.rubric_said_no),
  STRUCT(10, 'Judge scores', CONCAT(
      'accuracy ', IFNULL(FORMAT('%.2f', c.correctness_score), '–'),
      ' · groundedness ', IFNULL(FORMAT('%.2f', c.groundedness_score), '–'),
      ' · rubric ', IFNULL(FORMAT('%.2f', c.rubric_score), '–'))),
  STRUCT(11, 'Known caveat', c.known_limitations),
  STRUCT(12, 'Trace errors', CASE WHEN c.trace_id IS NULL THEN 'not measured (run not traced)'
                                  ELSE IFNULL(c.error_spans, 'none') END),
  STRUCT(13, 'Speed & cost', CONCAT(
      IFNULL(FORMAT('%.1f s', c.latency_s), '–'), ' · ',
      IFNULL(FORMAT('%d tokens', c.total_tokens), '–'), ' · ',
      IFNULL(FORMAT('$%.4f', c.cost_usd), '–'))),
  STRUCT(14, 'Run', CONCAT(c.run_id, ' · ', c.suite, ' · ', c.agent_model))
]) AS d
;
