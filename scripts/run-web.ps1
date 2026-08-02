$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$frontendCandidates = @(
  (Join-Path (Split-Path -Parent $backendDir) "jobs-scraper-web"),
  (Join-Path $backendDir "jobs-scraper-web"),
  (Join-Path (Split-Path -Parent $backendDir) "jobs-scrapper-web"),
  (Join-Path $backendDir "jobs-scrapper-web")
)

$frontendDir = $frontendCandidates | Where-Object { Test-Path (Join-Path $_ "package.json") } | Select-Object -First 1
if (-not $frontendDir) {
  Write-Error "Could not find jobs-scraper-web. Keep it next to job-scraper or pass into setup with --frontend-dir."
}

Set-Location $frontendDir
$hostName = if ($env:JOBTRACK_WEB_HOST) { $env:JOBTRACK_WEB_HOST } else { "0.0.0.0" }
$port = if ($env:PORT) { $env:PORT } else { "3000" }
npm run dev -- --hostname $hostName --port $port
