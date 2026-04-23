# One-command dev boot (Windows). Brings up docker-compose inside WSL,
# waits for infra healthchecks, then starts backend (WSL) + frontend (Windows)
# via PM2, and opens the browser to the dashboard.

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$null = New-Item -ItemType Directory -Force -Path "$RepoRoot/data/logs"
$null = New-Item -ItemType Directory -Force -Path "$RepoRoot/data/postgres"
$null = New-Item -ItemType Directory -Force -Path "$RepoRoot/data/redis"
$null = New-Item -ItemType Directory -Force -Path "$RepoRoot/data/chroma"

Write-Host "[dev] bringing up infra via docker compose…" -ForegroundColor Cyan
docker compose -f infra/docker-compose.yml up -d

function Wait-Healthy($cmd, $label) {
  Write-Host "[dev] waiting for $label…" -ForegroundColor Cyan
  $deadline = (Get-Date).AddSeconds(60)
  while ((Get-Date) -lt $deadline) {
    try {
      & $cmd | Out-Null
      if ($LASTEXITCODE -eq 0) { return }
    } catch { }
    Start-Sleep -Seconds 1
  }
  throw "$label did not become healthy in 60s"
}

Wait-Healthy { docker exec memeterm-postgres pg_isready -U memeterm -d memeterm } "postgres"
Wait-Healthy { docker exec memeterm-redis redis-cli ping } "redis"
Wait-Healthy { Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8001/api/v1/heartbeat } "chroma"

Write-Host "[dev] starting backend + frontend via PM2…" -ForegroundColor Cyan
pm2 start infra/pm2.config.cjs

Start-Sleep -Seconds 2
Start-Process "http://localhost:3000"
pm2 logs --lines 0
