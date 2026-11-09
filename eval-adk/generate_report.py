#!/usr/bin/env python
"""
Generate HTML evaluation report from summary JSON.

Usage:
    python generate_report.py                           # Generate from latest summary
    python generate_report.py lookup_results_summary.json  # Generate from specific summary
"""

import json
from pathlib import Path
from datetime import datetime
import sys


def generate_html_report(summary_file):
    """Generate HTML report from summary JSON"""

    if not Path(summary_file).exists():
        print(f"Error: File not found: {summary_file}")
        return None

    with open(summary_file, 'r') as f:
        summary = json.load(f)

    overview = summary['overview']
    by_criterion = summary['by_criterion']
    by_category = summary.get('by_category', {})
    failures = summary['failures']

    # Color coding
    def get_pass_color(pass_rate):
        if pass_rate >= 0.9:
            return '#27ae60'  # Green
        elif pass_rate >= 0.8:
            return '#f39c12'  # Orange
        else:
            return '#e74c3c'  # Red

    # Generate criterion rows
    criterion_rows = ""
    for criterion, stats in by_criterion.items():
        color = get_pass_color(stats['pass_rate'])
        criterion_rows += f"""
        <tr>
            <td><strong>{criterion}</strong></td>
            <td>{stats['passed']}/{stats['total']}</td>
            <td><span style="color: {color}; font-weight: bold;">{stats['pass_rate']*100:.1f}%</span></td>
        </tr>
        """

    # Generate category rows
    category_rows = ""
    for category, stats in sorted(by_category.items()):
        color = get_pass_color(stats['pass_rate'])
        category_rows += f"""
        <tr>
            <td><strong>{category}</strong></td>
            <td>{stats['passed']}/{stats['total']}</td>
            <td><span style="color: {color}; font-weight: bold;">{stats['pass_rate']*100:.1f}%</span></td>
        </tr>
        """

    # Generate failure rows
    failure_rows = ""
    for failure in failures[:20]:  # Show first 20 failures
        failure_rows += f"""
        <tr>
            <td><strong>{failure['eval_id']}</strong></td>
            <td>{failure['question']}</td>
            <td>{', '.join(failure['failed_criteria'])}</td>
        </tr>
        """

    if len(failures) > 20:
        failure_rows += f"""
        <tr>
            <td colspan="3" style="text-align: center; color: #7f8c8d;">
                ... and {len(failures) - 20} more failures
            </td>
        </tr>
        """

    # Determine overall status color
    overall_pass_rate = overview['pass_rate']
    overall_color = get_pass_color(overall_pass_rate)

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ADK Evaluation Report</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #ecf0f1;
            color: #2c3e50;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}

        header {{
            background: #2c3e50;
            color: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}

        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}

        header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}

        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .metric-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            border-left: 5px solid #3498db;
        }}

        .metric-card.success {{
            border-left-color: #27ae60;
        }}

        .metric-card.warning {{
            border-left-color: #f39c12;
        }}

        .metric-card.danger {{
            border-left-color: #e74c3c;
        }}

        .metric-label {{
            font-size: 0.9em;
            color: #7f8c8d;
            text-transform: uppercase;
            margin-bottom: 10px;
        }}

        .metric-value {{
            font-size: 2.5em;
            font-weight: bold;
            color: #2c3e50;
        }}

        .metric-percent {{
            font-size: 1.5em;
            margin-top: 10px;
        }}

        section {{
            background: white;
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        section h2 {{
            font-size: 1.8em;
            margin-bottom: 20px;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
        }}

        th {{
            background: #34495e;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: bold;
        }}

        td {{
            padding: 12px;
            border-bottom: 1px solid #ecf0f1;
        }}

        tr:hover {{
            background: #f8f9fa;
        }}

        .status-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
        }}

        .status-pass {{
            background: #d4edda;
            color: #155724;
        }}

        .status-fail {{
            background: #f8d7da;
            color: #721c24;
        }}

        footer {{
            text-align: center;
            padding: 20px;
            color: #7f8c8d;
            font-size: 0.9em;
        }}

        .progress-bar {{
            width: 100%;
            height: 20px;
            background: #ecf0f1;
            border-radius: 10px;
            overflow: hidden;
            margin-top: 10px;
        }}

        .progress-fill {{
            height: 100%;
            background: #27ae60;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 0.8em;
            font-weight: bold;
        }}

        .no-data {{
            color: #95a5a6;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>ADK Evaluation Report</h1>
            <p>Overwatch Mini Agent Evaluation Results</p>
            <p>Generated: {summary['metadata']['timestamp']}</p>
        </header>

        <div class="metrics">
            <div class="metric-card" style="border-left-color: {overall_color};">
                <div class="metric-label">Pass Rate</div>
                <div class="metric-value" style="color: {overall_color};">{overview['pass_rate_percent']}</div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {overall_pass_rate*100}%; background: {overall_color};">
                        {overall_pass_rate*100:.0f}%
                    </div>
                </div>
            </div>

            <div class="metric-card success">
                <div class="metric-label">Passed</div>
                <div class="metric-value">{overview['passed']}</div>
                <div class="metric-percent">of {overview['total_questions']} questions</div>
            </div>

            <div class="metric-card danger">
                <div class="metric-label">Failed</div>
                <div class="metric-value">{overview['failed']}</div>
                <div class="metric-percent">{(overview['failed']/overview['total_questions']*100):.1f}%</div>
            </div>

            <div class="metric-card" style="border-left-color: #9b59b6;">
                <div class="metric-label">Estimated Cost</div>
                <div class="metric-value" style="color: #9b59b6;">${summary['cost_estimate']['estimated_cost_usd']}</div>
                <div class="metric-percent">{summary['cost_estimate']['llm_calls']} LLM calls</div>
            </div>
        </div>

        <section>
            <h2>Evaluation Criteria Breakdown</h2>
            <table>
                <thead>
                    <tr>
                        <th>Criterion</th>
                        <th>Result</th>
                        <th>Pass Rate</th>
                    </tr>
                </thead>
                <tbody>
                    {criterion_rows}
                </tbody>
            </table>
        </section>

        {'<section>' + f'<h2>Category Breakdown</h2>' + '<table>' + '<thead><tr><th>Category</th><th>Result</th><th>Pass Rate</th></tr></thead><tbody>' + category_rows + '</tbody></table></section>' if category_rows else ''}

        <section>
            <h2>Failed Questions</h2>
            {'<table>' + '<thead><tr><th>ID</th><th>Question</th><th>Failed Criteria</th></tr></thead><tbody>' + failure_rows + '</tbody></table>' if failure_rows else '<p class="no-data">No failures - all tests passed!</p>'}
        </section>

        <footer>
            <p>ADK Evaluation Report | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </footer>
    </div>
</body>
</html>
"""

    return html


def main():
    # Find latest summary JSON or use provided one
    if len(sys.argv) > 1:
        summary_file = sys.argv[1]
    else:
        runs_dir = Path("eval-adk/runs")
        if not runs_dir.exists():
            print("Error: eval-adk/runs/ directory not found")
            return

        summary_files = list(runs_dir.glob("*_summary.json"))
        if not summary_files:
            print("Error: No summary JSON files found in eval-adk/runs/")
            print("Run: python analyze_results.py first")
            return

        summary_file = max(summary_files, key=lambda p: p.stat().st_mtime)

    print(f"\nGenerating report from: {summary_file}")
    print("-" * 60)

    html = generate_html_report(summary_file)
    if html is None:
        return

    # Save HTML report
    output_file = Path(summary_file).parent / f"{Path(summary_file).stem}.html"
    with open(output_file, 'w') as f:
        f.write(html)

    print(f"Report generated: {output_file}")
    print(f"Open in browser: file://{output_file.absolute()}")
    print("-" * 60)
    print("Done!\n")


if __name__ == "__main__":
    main()
