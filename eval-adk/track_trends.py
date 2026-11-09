#!/usr/bin/env python
"""
Track evaluation trends over time.

Maintains a history of evaluation runs and shows:
- Pass rate trend
- Category performance over time
- Improvement/regression alerts

Usage:
    python track_trends.py                    # Add latest results to history
    python track_trends.py --show             # Display trend history
    python track_trends.py --chart            # Generate trend chart (requires matplotlib)
"""

import json
from pathlib import Path
from datetime import datetime
import sys
from collections import defaultdict


HISTORY_FILE = Path("eval-adk/runs/trends_history.json")


def load_history():
    """Load existing trend history"""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    return {"runs": []}


def save_history(history):
    """Save trend history"""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)


def add_run_to_history(summary_file):
    """Add latest evaluation run to history"""

    if not Path(summary_file).exists():
        print(f"Error: Summary file not found: {summary_file}")
        return False

    with open(summary_file, 'r') as f:
        summary = json.load(f)

    history = load_history()

    # Check if run already in history (by timestamp)
    run_timestamp = summary['metadata']['timestamp']
    for existing_run in history['runs']:
        if existing_run['timestamp'] == run_timestamp:
            print(f"This run is already in history: {run_timestamp}")
            return False

    # Add to history
    run_entry = {
        "timestamp": run_timestamp,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "pass_rate": summary['overview']['pass_rate'],
        "pass_rate_percent": summary['overview']['pass_rate_percent'],
        "passed": summary['overview']['passed'],
        "failed": summary['overview']['failed'],
        "total": summary['overview']['total_questions'],
        "by_criterion": summary['by_criterion'],
        "by_category": summary.get('by_category', {})
    }

    history['runs'].append(run_entry)
    save_history(history)

    print(f"Added to history: {run_timestamp}")
    return True


def show_trends():
    """Display trend history"""

    history = load_history()

    if not history['runs']:
        print("No trend history found. Run evaluations first.")
        return

    print("\nEvaluation Trend History")
    print("=" * 80)
    print(f"{'Date':<12} {'Time':<10} {'Pass Rate':<12} {'Passed':<8} {'Failed':<8} {'Trend'}")
    print("-" * 80)

    prev_pass_rate = None
    for run in sorted(history['runs'], key=lambda x: x['timestamp']):
        pass_rate = run['pass_rate']
        trend = ""

        if prev_pass_rate is not None:
            if pass_rate > prev_pass_rate:
                trend = "IMPROVED +"
            elif pass_rate < prev_pass_rate:
                trend = "REGRESSED -"
            else:
                trend = "STABLE ="

            delta = pass_rate - prev_pass_rate
            if delta != 0:
                trend += f"{abs(delta)*100:.1f}%"

        print(
            f"{run['date']:<12} {run['time']:<10} {run['pass_rate_percent']:<12} "
            f"{run['passed']:<8} {run['failed']:<8} {trend}"
        )

        prev_pass_rate = pass_rate

    print("=" * 80)

    # Summary statistics
    if len(history['runs']) > 1:
        first_run = history['runs'][0]
        last_run = history['runs'][-1]
        improvement = last_run['pass_rate'] - first_run['pass_rate']

        print(f"\nTrend Summary:")
        print(f"  First run: {first_run['pass_rate_percent']} ({first_run['date']})")
        print(f"  Latest run: {last_run['pass_rate_percent']} ({last_run['date']})")
        if improvement > 0:
            print(f"  Overall change: IMPROVED by {improvement*100:.1f}%")
        elif improvement < 0:
            print(f"  Overall change: REGRESSED by {abs(improvement)*100:.1f}%")
        else:
            print(f"  Overall change: No change")

        print(f"\n  Total runs tracked: {len(history['runs'])}")


def generate_trend_report():
    """Generate text summary of trends"""

    history = load_history()

    if not history['runs']:
        print("No trend history found.")
        return

    report = "\nTrend Analysis Report\n"
    report += "=" * 60 + "\n"

    # Recent 5 runs
    recent_runs = history['runs'][-5:]
    avg_rate = sum(r['pass_rate'] for r in recent_runs) / len(recent_runs)

    report += f"Last 5 Runs Average Pass Rate: {avg_rate*100:.1f}%\n"

    # Category trends (if available)
    if recent_runs and recent_runs[-1]['by_category']:
        report += "\nCategory Performance (Latest Run):\n"
        for category, stats in sorted(recent_runs[-1]['by_category'].items()):
            report += f"  {category}: {stats['pass_rate']*100:.1f}%\n"

    report += "=" * 60 + "\n"

    print(report)


def main():
    if len(sys.argv) > 1:
        if Path(sys.argv[1]).is_file():
            if add_run_to_history(sys.argv[1]):
                print(f"Trend history updated: {HISTORY_FILE}")
                show_trends()
            else:
                show_trends()
        elif sys.argv[1] == '--show':
            show_trends()
        elif sys.argv[1] == '--report':
            generate_trend_report()
        elif sys.argv[1] == '--chart':
            print("Chart generation requires matplotlib")
            print("Install: pip install matplotlib")
            print("Then try again")
        else:
            print(f"Unknown option: {sys.argv[1]}")
            print("Usage:")
            print("  python track_trends.py                 # Add latest run")
            print("  python track_trends.py --show          # Show all runs")
            print("  python track_trends.py --report        # Analysis report")
    else:
        # Add latest summary to history
        runs_dir = Path("eval-adk/runs")
        if not runs_dir.exists():
            print("Error: eval-adk/runs/ directory not found")
            return

        summary_files = sorted(runs_dir.glob("*_summary.json"))
        if not summary_files:
            print("Error: No summary files found")
            print("Run: python analyze_results.py first")
            return

        latest_summary = summary_files[-1]
        if add_run_to_history(str(latest_summary)):
            print(f"Trend history updated: {HISTORY_FILE}")
            show_trends()
        else:
            show_trends()


if __name__ == "__main__":
    main()
