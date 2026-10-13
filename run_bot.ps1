#Requires -Version 5.1
# Keep the news bot running (restart on crash). Run this, not bot.py directly.
$ErrorActionPreference = "Continue"
$BriefDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $BriefDir
while ($true) {
  Write-Host "[$(Get-Date -Format o)] starting bot.py"
  python .\bot.py
  Write-Host "[$(Get-Date -Format o)] bot exited code $LASTEXITCODE, restart in 5s"
  Start-Sleep -Seconds 5
}
