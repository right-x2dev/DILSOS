# Create the public GitHub repository and push all commits (run from the repo root in PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\publish_github.ps1 [-Name DILSOS]
# Requires: GitHub CLI (winget install --id GitHub.cli -e) and a one-time `gh auth login` by the owner.
param([string]$Name = "DILSOS")
$ErrorActionPreference = "Stop"

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
gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Not logged in — starting browser login (choose GitHub.com, HTTPS)..." -ForegroundColor Yellow
  gh auth login --hostname github.com --git-protocol https --web
}
gh auth setup-git
$desc = "DILSOS - Dynamic Integrated Logistics Scheduling & Optimization System: coupled warehouse-dock-VRPTW scheduling, CP-SAT/OR-Tools/ALNS, KEEP/PARTIAL/FULL rescheduling (FastAPI, React, MySQL)"
$remote = git remote 2>$null
if ($remote -notcontains "origin") {
  gh repo create $Name --public --source . --remote origin --description $desc --push
} else {
  git push -u origin main
}
gh repo view --web
