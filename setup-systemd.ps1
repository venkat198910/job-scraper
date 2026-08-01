param(
  [string]$Distro = "Ubuntu",
  [string]$ServiceName = "jobtrack-web",
  [int]$Port = 3000
)

$ErrorActionPreference = "Stop"

$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wsl) {
  Write-Error "WSL was not found. systemctl services must be installed inside Linux/WSL."
}

$repoPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$linuxRepoPath = wsl -d $Distro -- wslpath -a "$repoPath"
if ($LASTEXITCODE -ne 0 -or -not $linuxRepoPath) {
  Write-Error "Could not convert repo path to WSL path. Check WSL distro name: $Distro"
}

wsl -d $Distro -- bash -lc "cd '$linuxRepoPath' && chmod +x scripts/install-systemd-user-service.sh && SERVICE_NAME='$ServiceName' PORT='$Port' ./scripts/install-systemd-user-service.sh"
