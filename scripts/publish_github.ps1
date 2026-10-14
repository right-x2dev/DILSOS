# Create the public GitHub repository and push all commits (run from the repo root in PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\publish_github.ps1 [-Name DILSOS]
# Requires: GitHub CLI (winget install --id GitHub.cli -e) and a one-time `gh auth login` by the owner.
param([string]$Name = "DILSOS")
# Native tools (gh/git) write normal status messages to stderr; in Windows PowerShell 5.1 that must not be
# treated as a terminating error, so failures are checked via $LASTEXITCODE instead of ErrorActionPreference=Stop.
$ErrorActionPreference = "Continue"

$gitDesktop = Join-Path $env:LOCALAPPDATA "GitHubDesktop"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  $g = Get-ChildItem $gitDesktop -Recurse -Filter git.exe -ErrorAction SilentlyContinue | Where-Object { $_.FullName -like "*\cmd\git.exe" } | Select-Object -First 1
  if ($g) { $env:Path += ";" + $g.DirectoryName }
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  foreach ($p in @("$env:ProgramFiles\GitHub CLI", "$env:LOCALAPPDATA\Programs\GitHub CLI")) { if (Test-Path "$p\gh.exe") { $env:Path += ";$p" } }
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  Write-Host "GitHub CLI not found. Install it first:  winget install --id GitHub.cli -e" -ForegroundColor Yellow
  exit 1
}
cmd /c "gh auth status >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
  Write-Host "Not logged in - starting browser login (copy the one-time code, then authorize in the browser)..." -ForegroundColor Yellow
  gh auth login --hostname github.com --git-protocol https --web
  cmd /c "gh auth status >nul 2>&1"
  if ($LASTEXITCODE -ne 0) { Write-Host "Login did not complete. Re-run this script." -ForegroundColor Red; exit 1 }
}
gh auth setup-git
$desc = "DILSOS - Dynamic Integrated Logistics Scheduling & Optimization System: coupled warehouse-dock-VRPTW scheduling, CP-SAT/OR-Tools/ALNS, KEEP/PARTIAL/FULL rescheduling (FastAPI, React, MySQL)"
$remote = @(git remote)
if ($remote -notcontains "origin") {
  gh repo create $Name --public --source . --remote origin --description $desc --push
} else {
  git push -u origin main
}
if ($LASTEXITCODE -ne 0) { Write-Host "Push failed - see the message above." -ForegroundColor Red; exit 1 }
Write-Host "Published." -ForegroundColor Green
gh repo view --web
