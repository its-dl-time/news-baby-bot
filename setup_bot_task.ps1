#Requires -Version 5.1
# Auto-start bot at logon: schtasks / logon trigger
$ErrorActionPreference = "Stop"
$BriefDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "NewsBotPolling"
$Action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$BriefDir\run_bot.ps1`""
schtasks /Create /TN $TaskName /SC ONLOGON /TR "$Action" /F
if ($LASTEXITCODE -ne 0) { throw "schtasks failed: $LASTEXITCODE" }
Write-Host "Registered $TaskName (ONLOGON). Start now: schtasks /Run /TN $TaskName"
