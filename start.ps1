<#
.SYNOPSIS
  Start the Azure to Leaseweb Migration Assistant (Windows).
.DESCRIPTION
  Creates a .venv on first run, installs requirements.txt when it changed, then starts the server.
.PARAMETER Port
  Port to listen on (default 8000, or the PORT environment variable).
.PARAMETER BindHost
  Address to listen on (default 127.0.0.1, or the HOST environment variable).
.PARAMETER Reload
  Restart the server when the code changes (for development).
.EXAMPLE
  .\start.ps1 -Port 9000
.NOTES
  If scripts are blocked on your machine, run start.bat instead, or:
  powershell -ExecutionPolicy Bypass -File .\start.ps1
  AI_PROVIDER, AI_MODEL and ANTHROPIC_API_KEY are passed through to the app.
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$BindHost = '127.0.0.1',
    [switch]$Reload
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not $PSBoundParameters.ContainsKey('Port') -and $env:PORT) {
    if ($env:PORT -notmatch '^\d+$') { throw "PORT must be a number, got '$($env:PORT)'." }
    $Port = [int]$env:PORT
}
if (-not $PSBoundParameters.ContainsKey('BindHost') -and $env:HOST) { $BindHost = $env:HOST }

# Python 3.10 or newer: the py launcher first, then python, then python3
function Find-Python {
    $candidates = @(@('py', '-3'), @('python'), @('python3'))
    foreach ($c in $candidates) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @($c | Select-Object -Skip 1)
        & $c[0] @extra -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Error 'Python 3.10 or newer is required but was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".'
    exit 1
}

# Virtual environment
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creating the virtual environment in .venv ...'
    $extra = @($py | Select-Object -Skip 1)
    & $py[0] @extra -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Error 'Could not create .venv.'; exit 1 }
}

# Install requirements only when requirements.txt changed
$marker = Join-Path $PSScriptRoot '.venv\.requirements.sha256'
$want = (Get-FileHash -LiteralPath 'requirements.txt' -Algorithm SHA256).Hash
$have = if (Test-Path -LiteralPath $marker) { (Get-Content -LiteralPath $marker -Raw).Trim() } else { '' }
if ($want -ne $have) {
    Write-Host 'Installing requirements ...'
    & $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Error 'Installing the requirements failed.'; exit 1 }
    Set-Content -LiteralPath $marker -Value $want -NoNewline
}

# Friendly notes (none of these stop the server)
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Write-Warning "'az' was not found. Discover needs the Azure CLI (az login)." }
if (-not (Get-Command claude -ErrorAction SilentlyContinue) -and -not (Get-Command opencode -ErrorAction SilentlyContinue) -and -not $env:ANTHROPIC_API_KEY) {
    Write-Warning 'No AI provider found (claude, opencode or ANTHROPIC_API_KEY). Choose one with the AI button in the app.'
}
if ($BindHost -notin @('127.0.0.1', 'localhost', '::1')) {
    Write-Warning "Listening on $BindHost. The app has no login, so only do this on a network you trust. Open it by IP, or list its host name in ALLOWED_HOSTS."
}

Write-Host "Starting on http://${BindHost}:$Port  (Ctrl+C to stop)"
$serverArgs = @('-m', 'uvicorn', 'migration_assistant.app:app', '--host', $BindHost, '--port', "$Port")
if ($Reload) { $serverArgs += '--reload' }
& $venvPython @serverArgs
exit $LASTEXITCODE
