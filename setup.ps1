param(
  [switch]$InstallSystemd,
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$SetupArgs
)

$ErrorActionPreference = "Stop"

if ($InstallSystemd -and ($SetupArgs -notcontains "--install-systemd")) {
  $SetupArgs += "--install-systemd"
}

function Invoke-LocalSetup {
  param([string[]]$SetupArgs)

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
      py -3 scripts/local_setup.py @SetupArgs
      exit $LASTEXITCODE
    }
    Write-Host "[setup] Existing Python launcher is older than 3.11."
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
      python scripts/local_setup.py @SetupArgs
      exit $LASTEXITCODE
    }
    Write-Host "[setup] Existing python is older than 3.11."
  }

  return
}

Invoke-LocalSetup -SetupArgs $SetupArgs

Write-Host "[setup] Python 3 was not found. Trying automatic install..."

$winget = Get-Command winget -ErrorAction SilentlyContinue
if ($winget) {
  winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements
} else {
  $choco = Get-Command choco -ErrorAction SilentlyContinue
  if ($choco) {
    choco install python --version=3.11.9 -y
  } else {
    Write-Error "Python 3.11+ is missing and neither winget nor choco is available. Install Python 3.11+ and rerun .\setup.ps1"
  }
}

Invoke-LocalSetup -SetupArgs $SetupArgs

Write-Error "Python install completed, but python/py is not available in this shell yet. Open a new PowerShell window and rerun .\setup.ps1"
