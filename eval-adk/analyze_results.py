#!/usr/bin/env python
"""
Analyze ADK evaluation results and generate summary JSON.

Usage:
    python analyze_results.py                  # Analyze latest results
    python analyze_results.py lookup_results.csv  # Analyze specific file
    python analyze_results.py lookup_results.csv --latest  # Only latest run
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys
import argparse


def analyze_csv(csv_file, latest_run_only=False):
    """Convert CSV results to structured summary

    Args:
        csv_file: Path to CSV results file
        latest_run_only: If True, analyze only the latest run; if False, analyze all runs
    """

    if not Path(csv_file).exists():
        print(f"Error: File not found: {csv_file}")
        return None

    df = pd.read_csv(csv_file)

    # Detect multiple runs by looking at eval_id frequency
    eval_id_counts = df['eval_id'].value_counts()
    max_count = eval_id_counts.max()
    num_runs = max_count // df['metric_name'].nunique() if df['metric_name'].nunique() > 0 else 1

    if latest_run_only and num_runs > 1:
        # Get latest run: keep only rows with highest row indices for each eval_id+metric combination
        df = df.sort_values('eval_id').drop_duplicates(
            subset=['eval_id', 'metric_name'], keep='last'
        ).sort_index()
        print(f"📊 Analyzing latest run only (run {num_runs} of {num_runs})")
    elif num_runs > 1:
        print(f"⚠️  WARNING: Detected {num_runs} runs in this file. Results below mix all runs.")
        print(f"   Use --latest flag to analyze only the most recent run.")

    # Get unique evaluation IDs (one per question)
    unique_evals = df['eval_id'].unique()
    total_questions = len(unique_evals)

    # Count passed evaluations (if ANY criterion fails, question fails)
    passed_questions = set()
    failed_questions = {}

    for eval_id in unique_evals:
        eval_df = df[df['eval_id'] == eval_id]

        # Check if all criteria passed for this eval
        failed_criteria = eval_df[eval_df['eval_status'] == 'FAILED']

        if len(failed_criteria) == 0:
            passed_questions.add(eval_id)
        else:
            failed_questions[eval_id] = {
                'question': eval_df['prompt'].iloc[0] if 'prompt' in eval_df.columns else 'N/A',
                'expected': eval_df['expected_response'].iloc[0] if 'expected_response' in eval_df.columns else 'N/A',
                'actual': eval_df['actual_response'].iloc[0] if 'actual_response' in eval_df.columns else 'N/A',
                'failed_criteria': failed_criteria['metric_name'].tolist()
            }

    passed_count = len(passed_questions)
    failed_count = total_questions - passed_count

    # Informational efficiency metrics are reported by ADK, but are not
    # pass/fail criteria and should not be included in pass-rate summaries.
    criterion_stats = {}
    scored_df = df[df['eval_status'] != 'INFORMATIONAL']
    for criterion in scored_df['metric_name'].unique():
        criterion_df = scored_df[scored_df['metric_name'] == criterion]
        # Count unique eval_id that PASSED this criterion
        passed_evals = criterion_df[criterion_df['eval_status'] == 'PASSED']['eval_id'].unique()
        criterion_total = len(criterion_df['eval_id'].unique())
        criterion_passed = len(passed_evals)

        criterion_stats[criterion] = {
            "passed": int(criterion_passed),
            "failed": int(criterion_total - criterion_passed),
            "pass_rate": round(criterion_passed / criterion_total if criterion_total > 0 else 0, 4),
            "total": int(criterion_total)
        }

    # Breakdown by category
    category_stats = {}
    if 'eval_set_id' in df.columns:
        for category in df['eval_set_id'].unique():
            category_df = df[df['eval_set_id'] == category]
            category_evals = category_df['eval_id'].unique()
            category_passed = 0

            for eval_id in category_evals:
                eval_df = category_df[category_df['eval_id'] == eval_id]
                if len(eval_df[eval_df['eval_status'] == 'FAILED']) == 0:
                    category_passed += 1

            category_total = len(category_evals)
            category_stats[category] = {
                "passed": int(category_passed),
                "failed": int(category_total - category_passed),
                "pass_rate": round(category_passed / category_total if category_total > 0 else 0, 4),
                "total": int(category_total)
            }

    # Metrics
    cost_per_llm_call = 0.025  # Average cost
    llm_calls = len(df[df['metric_name'].isin(['final_response_match_v2', 'hallucinations_v1'])])
    estimated_cost = (llm_calls / 64 * 2.50) if llm_calls > 0 else 0  # Rough estimate

    # Build summary
    summary = {
        "metadata": {
            "run_date": datetime.now().isoformat(),
            "csv_file": str(csv_file),
            "total_rows": len(df),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        },

        "overview": {
            "total_questions": int(total_questions),
            "passed": int(passed_count),
            "failed": int(failed_count),
            "pass_rate": round(passed_count / total_questions if total_questions > 0 else 0, 4),
            "pass_rate_percent": f"{(passed_count / total_questions * 100 if total_questions > 0 else 0):.1f}%"
        },

        "by_criterion": criterion_stats,
        "by_category": category_stats,

        "failures": [
            {
                "eval_id": eval_id,
                "question": data['question'][:100] + "..." if len(data['question']) > 100 else data['question'],
                "failed_criteria": data['failed_criteria'],
                "details": data
            }
            for eval_id, data in sorted(failed_questions.items())
        ],

        "cost_estimate": {
            "llm_calls": int(llm_calls),
            "estimated_cost_usd": round(estimated_cost, 2)
        }
    }

    return summary

def save_to_db(summary, run_id, run_type="unknown"):
    """Write eval results to Supabase so Grafana can display them."""
    import os
    from datetime import datetime, timezone
    import psycopg

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set - skipping database write")
        return

    run_at = datetime.now(timezone.utc)
    overview = summary['overview']
    cost = summary['cost_estimate']

    with psycopg.connect(url) as con:
        con.execute("""
            INSERT INTO evalresults.runs
                (run_id, run_type, run_at, total_cases, passed, failed, pass_rate, llm_calls, estimated_cost_usd)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO NOTHING """,
            (run_id, run_type, run_at, overview['total_questions'], overview['passed'], overview['failed'],
                overview['pass_rate'], cost['llm_calls'], cost['estimated_cost_usd']))

        for criterion, stats in summary['by_criterion'].items():
            con.execute("""
                INSERT INTO evalresults.criteria
                    (run_id, criterion, passed, failed, pass_rate, total)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                (run_id, criterion, stats['passed'], stats['failed'], stats['pass_rate'], stats['total']))

        for category, stats in summary['by_category'].items():
            con.execute("""
                INSERT INTO evalresults.categories
                    (run_id, category, passed, failed, pass_rate, total)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                (run_id, category, stats['passed'], stats['failed'], stats['pass_rate'], stats['total']))

        for failure in summary['failures']:
            con.execute("""
                INSERT INTO evalresults.failures
                    (run_id, eval_id, question, failed_criteria)
                    VALUES (%s, %s, %s, %s)
                    """,
                (run_id, failure['eval_id'], failure['question'], failure['failed_criteria']))
    
        con.commit()

    print(f"Results saved to database (run_id: {run_id})")



def main():
    parser = argparse.ArgumentParser(
        description="Analyze ADK evaluation results"
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        help="CSV results file to analyze (default: latest in eval-adk/runs/)"
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Analyze only the latest run if multiple runs exist in CSV"
    )
    parser.add_argument(
        "--run-type",
        default="unknown",
        help="Eval category name e.g. TestLookup or TestFullSuite"
    )
    args = parser.parse_args()

    # Find CSV file
    if args.csv_file:
        csv_file = args.csv_file
    else:
        runs_dir = Path("eval-adk/runs")
        if not runs_dir.exists():
            print("Error: eval-adk/runs/ directory not found")
            return

        csv_files = list(runs_dir.glob("*_results.csv"))
        if not csv_files:
            print("Error: No CSV results found in eval-adk/runs/")
            return

        csv_file = max(csv_files, key=lambda p: p.stat().st_mtime)

    print(f"\nAnalyzing: {csv_file}")
    print("-" * 60)

    summary = analyze_csv(csv_file, latest_run_only=args.latest)
    if summary is None:
        return

    # Print summary to console
    print(f"\nRun Date: {summary['metadata']['timestamp']}")
    print(f"\nOverall Results:")
    print(f"  Total Questions: {summary['overview']['total_questions']}")
    print(f"  Passed: {summary['overview']['passed']}")
    print(f"  Failed: {summary['overview']['failed']}")
    print(f"  Pass Rate: {summary['overview']['pass_rate_percent']}")

    print(f"\nBy Criterion:")
    for criterion, stats in summary['by_criterion'].items():
        print(f"  {criterion}:")
        print(f"    Passed: {stats['passed']}/{stats['total']}")
        print(f"    Pass Rate: {stats['pass_rate']*100:.1f}%")

    if summary['by_category']:
        print(f"\nBy Category:")
        for category, stats in summary['by_category'].items():
            print(f"  {category}:")
            print(f"    Passed: {stats['passed']}/{stats['total']} ({stats['pass_rate']*100:.1f}%)")

    if summary['failures']:
        print(f"\nFailed Questions ({len(summary['failures'])} total):")
        for failure in summary['failures'][:5]:  # Show first 5
            print(f"  - {failure['eval_id']}: {failure['question']}")
            print(f"    Failed criteria: {', '.join(failure['failed_criteria'])}")

        if len(summary['failures']) > 5:
            print(f"  ... and {len(summary['failures']) - 5} more")

    print(f"\nCost Estimate: ${summary['cost_estimate']['estimated_cost_usd']}")
    print("-" * 60)

    # Save summary JSON
    output_file = Path(csv_file).parent / f"{Path(csv_file).stem}_summary.json"
    with open(output_file, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\nSummary saved to: {output_file}")
    run_id = Path(csv_file).stem
    save_to_db(summary, run_id, run_type=args.run_type)
    print("Done!\n")


if __name__ == "__main__":
    main()
