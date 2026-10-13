#Requires -Version 5.1
# Register / update Windows Task Scheduler job: daily 07:00 ICT (system is already UTC+7)
$ErrorActionPreference = "Stop"
$BriefDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $BriefDir "run_daily.ps1"
$TaskName = "NewsBriefingDaily"

$Action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Script`""
schtasks /Create /TN $TaskName /SC DAILY /ST 07:00 /TR "$Action" /F
if ($LASTEXITCODE -ne 0) { throw "schtasks create failed: $LASTEXITCODE" }
Write-Host "Registered task '$TaskName' daily 07:00. Verify with: schtasks /Query /TN $TaskName /V"
Write-Host "Run now for test with: schtasks /Run /TN $TaskName"
