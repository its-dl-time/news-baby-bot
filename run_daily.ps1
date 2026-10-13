#Requires -Version 5.1
# Runner: opencode run skill -> markdown report -> Email and/or Telegram
# Examples:
#   .\run_daily.ps1
#   .\run_daily.ps1 -TargetDate 2026-10-10
#   .\run_daily.ps1 -From 2026-10-01 -To 2026-10-10
#   .\run_daily.ps1 -TargetDate 2026-10-10 -Channels telegram
param(
  [string]$TargetDate = "",
  [string]$From = "",
  [string]$To = "",
  [ValidateSet("email", "telegram", "both")][string]$Channels = "both"
)
$ErrorActionPreference = "Stop"
$BriefDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PromptFile = Join-Path $BriefDir "daily_prompt.txt"
$ReportsDir = Join-Path $BriefDir "reports"
$LogDir = Join-Path $BriefDir "logs"
New-Item -ItemType Directory -Force -Path $ReportsDir, $LogDir | Out-Null

# Resolve date window: single date > range > today
$today = Get-Date -Format "yyyy-MM-dd"
if ($TargetDate -ne "") { $From = $TargetDate; $To = $TargetDate }
if ($From -eq "" -and $To -eq "") { $From = $today; $To = $today }
if ($To -eq "") { $To = $From }
$Stamp = if ($From -eq $To) { $From } else { "${From}_to_${To}" }
$ReportMd = Join-Path $ReportsDir "briefing-$Stamp.md"
$LogFile = Join-Path $LogDir "run-$Stamp.log"

function Write-Log($msg) {
  $line = "[$(Get-Date -Format o)] $msg"
  $line | Tee-Object -FilePath $LogFile -Append
}

# Date suffix for queries: EN + VI
function DateSuffix([string]$d) {
  $dt = [datetime]::ParseExact($d, "yyyy-MM-dd", $null)
  $en = $dt.ToString("MMMM d yyyy", [cultureinfo]::GetCultureInfo("en-US"))
  $vi = $dt.ToString("dd/MM/yyyy")
  return "$en / ngày $vi"
}
$windowTxt = if ($From -eq $To) { DateSuffix $From } else { "$(DateSuffix $From) đến $(DateSuffix $To)" }

Write-Log "Starting briefing window $From..$To channels=$Channels"
$prompt = Get-Content -Raw -Path $PromptFile
$promptWithDate = "$prompt`n`nContext: target date window = $From to $To ($windowTxt). Today is $today ICT (UTC+7). HARD RULE: only include news published inside [$From, $To]. Append '$windowTxt' to every search query. Drop anything outside the window."

try {
  $out = & opencode run --auto "$promptWithDate" 2>&1
  $out | Out-File -FilePath $LogFile -Append -Encoding utf8
  if ($LASTEXITCODE -ne 0) { throw "opencode run exit code $LASTEXITCODE" }
  $out | Out-File -FilePath $ReportMd -Encoding utf8
  Write-Log "Report saved: $ReportMd ($((Get-Item $ReportMd).Length) bytes)"
} catch {
  Write-Log "FAILED opencode run: $_"
  throw
}

if ($Channels -in @("email", "both")) {
  try {
    & python (Join-Path $BriefDir "send_email.py") --report "$ReportMd"
    Write-Log "Email sent."
  } catch { Write-Log "FAILED email (non-fatal if telegram ok): $_"; if ($Channels -eq "email") { throw } }
}
if ($Channels -in @("telegram", "both")) {
  try {
    & python (Join-Path $BriefDir "send_telegram.py") --report "$ReportMd" --mode summary+file
    Write-Log "Telegram sent."
  } catch { Write-Log "FAILED telegram: $_"; if ($Channels -eq "telegram") { throw } }
}
