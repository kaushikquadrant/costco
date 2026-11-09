# Archived legacy evaluation data

This folder preserves JSONL golden datasets and historical reports from the
retired custom evaluation workflow. They are retained as reference material
and are not read by the Google ADK pytest runner.

The active evaluation source of truth is `eval-adk/eval_sets/`. New golden
case authoring and scoring should use ADK evalset JSON and the sibling
`test_config.json`.

Running `data_gen/generate.py` or `data_gen/make_golden_v2.py` writes
regenerated legacy JSONL snapshots under `generated/`. These are still
reference artifacts, not ADK inputs.
