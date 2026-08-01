param(
  [string]$ListenAddress = "0.0.0.0",
  [string]$ConnectAddress = "127.0.0.1",
  [int]$Port = 3000
)

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltinRole]::Administrator
)

if (-not $isAdmin) {
  Write-Error "Run this PowerShell as Administrator to configure Windows portproxy/firewall."
}

netsh interface portproxy delete v4tov4 listenaddress=$ListenAddress listenport=$Port 2>$null | Out-Null
netsh interface portproxy add v4tov4 listenaddress=$ListenAddress listenport=$Port connectaddress=$ConnectAddress connectport=$Port

$ruleName = "JobTrack Web Port $Port"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
}

Write-Host "Port forwarding enabled: $ListenAddress`:$Port -> $ConnectAddress`:$Port"
Write-Host "Start the web UI with .\scripts\run-web.ps1"
