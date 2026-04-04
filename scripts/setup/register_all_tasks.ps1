# register_all_tasks.ps1
# Ruppert Task Scheduler — Disaster Recovery / Fresh Machine Setup
#
# Re-registers all Ruppert-* tasks from their exported XML definitions.
# Run from an elevated PowerShell prompt (as Administrator).
#
# Usage:
#   .\register_all_tasks.ps1
#
# The XML files in this directory were exported on 2026-03-31 from the
# DEMO host. Update them by re-running the export script, or by editing
# and re-running config_audit.py / exporting individual tasks with:
#   schtasks /query /xml /tn "<TaskName>" > <TaskName>.xml

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$taskFiles = @(
    "Ruppert-Crypto-10AM.xml",
    "Ruppert-Crypto-12PM.xml",
    "Ruppert-Crypto-2PM.xml",
    "Ruppert-Crypto-4PM.xml",
    "Ruppert-Crypto-6PM.xml",
    "Ruppert-Crypto-8AM.xml",
    "Ruppert-Crypto-8PM.xml",
    "Ruppert-Crypto1D.xml",
    "Ruppert-DailyHealthCheck.xml",
    "Ruppert-DailyIntegrityCheck.xml",
    "Ruppert-DailyProgressReport.xml",
    "Ruppert-Demo-10PM.xml",
    "Ruppert-Demo-3PM.xml",
    "Ruppert-Demo-7AM.xml",
    "Ruppert-PostTrade-Monitor.xml",
    "Ruppert-Research-Weekly.xml",
    "Ruppert-SettlementChecker.xml",
    "Ruppert-WS-Persistent.xml",
    "Ruppert-WS-Watchdog.xml",
    "RuppertDashboard.xml"
)

$passed = 0
$failed = 0

Write-Host "=== Ruppert Task Scheduler — Re-registration ===" -ForegroundColor Cyan
Write-Host "Source directory: $ScriptDir"
Write-Host ""

foreach ($file in $taskFiles) {
    $taskName = [System.IO.Path]::GetFileNameWithoutExtension($file)
    $xmlPath  = Join-Path $ScriptDir $file

    if (-not (Test-Path $xmlPath)) {
        Write-Host "  [SKIP] $taskName — XML file not found: $xmlPath" -ForegroundColor Yellow
        continue
    }

    try {
        # /F forces re-creation even if the task already exists
        $output = schtasks /create /xml $xmlPath /tn $taskName /F 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK]   $taskName" -ForegroundColor Green
            $passed++
        } else {
            Write-Host "  [FAIL] $taskName — $output" -ForegroundColor Red
            $failed++
        }
    } catch {
        Write-Host "  [FAIL] $taskName — $_" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host "=== Result: $passed registered, $failed failed ===" -ForegroundColor Cyan

if ($failed -gt 0) {
    Write-Host "ACTION REQUIRED: Fix failed tasks above before going live." -ForegroundColor Red
    exit 1
}

Write-Host "All tasks registered successfully." -ForegroundColor Green
exit 0
