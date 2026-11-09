# Run ADK evals, analyze this run's CSV, and archive its reports.
# Usage: .\run_eval_full.ps1 [category]
# Example: .\run_eval_full.ps1 TestLookup

param(
    [string]$Category = "TestLookup"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runDir = Join-Path "eval-adk\runs" $timestamp
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "ADK Evaluation Workflow" -ForegroundColor Cyan
Write-Host "Category: $Category" -ForegroundColor Cyan
Write-Host "Run directory: $runDir" -ForegroundColor Gray
Write-Host "==================================================================" -ForegroundColor Cyan

$evalStartedAt = Get-Date
Write-Host "`n[1/5] Running evaluation..." -ForegroundColor Yellow
& python -m pytest "eval-adk/test_overwatch_evals.py::$Category" -v
$testExitCode = $LASTEXITCODE

$csvFile = Get-ChildItem -Path "eval-adk\runs" -File -Filter "*_results_*.csv" |
    Where-Object { $_.LastWriteTime -ge $evalStartedAt } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $csvFile) {
    Write-Host "No results CSV was generated. Check the pytest output and environment." -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/5] Analyzing $($csvFile.Name)..." -ForegroundColor Yellow
& python "eval-adk\analyze_results.py" $csvFile.FullName
if ($LASTEXITCODE -ne 0) {
    Write-Host "Analysis failed." -ForegroundColor Red
    exit 1
}
$summaryFile = Join-Path $csvFile.DirectoryName ($csvFile.BaseName + "_summary.json")

Write-Host "`n[3/5] Generating report..." -ForegroundColor Yellow
& python "eval-adk\generate_report.py" $summaryFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "Report generation failed." -ForegroundColor Red
    exit 1
}
$htmlFile = Join-Path $csvFile.DirectoryName ($csvFile.BaseName + "_summary.html")

Write-Host "`n[4/5] Updating trends..." -ForegroundColor Yellow
& python "eval-adk\track_trends.py" $summaryFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "Trend update failed." -ForegroundColor Red
    exit 1
}

$checksBase = Join-Path $csvFile.DirectoryName $csvFile.BaseName
if ($csvFile.Name -like "consistency_*") {
    # Several runs per case in one CSV: score each run separately and report what flips.
    Write-Host "`n[5/5] Consistency analysis (each run scored separately, then compared)..." -ForegroundColor Yellow
    & python "eval-adk\consistency.py" $csvFile.FullName
    $outputs = "_consistency.json", "_consistency.csv"
} else {
    Write-Host "`n[5/5] Running custom checks (facts, arguments, behaviour, format, budgets)..." -ForegroundColor Yellow
    & python "eval-adk\score_checks.py" $csvFile.FullName
    $outputs = "_checks.json", "_checks.csv"
}
foreach ($ext in $outputs) {
    if (Test-Path ($checksBase + $ext)) { Copy-Item ($checksBase + $ext) $runDir -Force }
}

# Day 4: where the time and tokens went, from this run's traces (only when TRACING=on).
$runId = [regex]::Match($csvFile.Name, '\d{8}_\d{6}_\d{6}').Value
if ($runId -and (Test-Path "eval-adk\runs\spans\spans_$runId.jsonl")) {
    Write-Host "`n[+] Trace summary (time and tokens per case, from the spans)..." -ForegroundColor Yellow
    & python "eval-adk\span_summary.py" $csvFile.FullName
    foreach ($ext in "_span_summary.csv", "_spans.csv") {
        if (Test-Path ($checksBase + $ext)) { Copy-Item ($checksBase + $ext) $runDir -Force }
    }
}

Copy-Item $csvFile.FullName $runDir -Force
Copy-Item $summaryFile $runDir -Force
Copy-Item $htmlFile $runDir -Force

Write-Host "`nResults archived to: $runDir" -ForegroundColor Green
Write-Host "CSV:     $(Split-Path -Leaf $csvFile.FullName)" -ForegroundColor Gray
Write-Host "Summary: $(Split-Path -Leaf $summaryFile)" -ForegroundColor Gray
Write-Host "Report:  $(Split-Path -Leaf $htmlFile)" -ForegroundColor Gray
Start-Process (Join-Path $runDir (Split-Path -Leaf $htmlFile))

if ($testExitCode -ne 0) {
    Write-Host "`nEvaluation completed with failing criteria. See the report for details." -ForegroundColor Red
    exit $testExitCode
}

Write-Host "`nEvaluation completed successfully." -ForegroundColor Green
