# ADK Evaluation Categories

The active Google ADK suite is organized into ten evalsets under `eval_sets/`.
Category files are an organizational choice; ADK evaluates each valid evalset
using the shared `eval_sets/test_config.json`.

| Evalset | Cases | Coverage |
|---|---:|---|
| `overwatch_lookup.evalset.json` | 8 | Individual incident lookups |
| `overwatch_aggregation.evalset.json` | 10 | Counts, filters, and incident aggregation |
| `overwatch_log_count.evalset.json` | 6 | Log counts by service, level, or time |
| `overwatch_log_search.evalset.json` | 5 | Log search and interpretation |
| `overwatch_metrics.evalset.json` | 7 | Service performance metrics |
| `overwatch_problems.evalset.json` | 3 | Monitoring problems |
| `overwatch_cross_source.evalset.json` | 8 | Questions requiring multiple data sources |
| `overwatch_negative.evalset.json` | 6 | Missing data and negative results |
| `overwatch_out_of_scope.evalset.json` | 5 | Requests that available tools cannot answer |
| `overwatch_safety.evalset.json` | 6 | Prompt injection and data-safety behavior |
| **Total** | **64** | |

Run a single category or all categories from the repository root:

```powershell
.\run_eval_full.ps1 TestLookup
.\run_eval_full.ps1 TestFullSuite
```

See [`README.md`](README.md) for installation, credentials, scoring, reports,
and troubleshooting. Legacy JSONL datasets and results are retained under
`data_gen/legacy_eval_archive/`; they are not part of these ADK evalsets.
