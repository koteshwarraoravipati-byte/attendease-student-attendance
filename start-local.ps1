$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $project 'backend'
$frontend = Join-Path $project 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$npm = 'C:\Program Files\nodejs\npm.cmd'
$cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend virtual environment not found. Create it first with: python -m venv backend\.venv"
}
if (-not (Test-Path -LiteralPath $npm)) {
    throw "Node.js/npm was not found at $npm"
}

$apiListener = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if (-not $apiListener) {
    $apiCommand = "cd /d `"$backend`" && `"$python`" -m flask --app app run --host 127.0.0.1 --port 5000 --no-reload"
    Start-Process -FilePath $cmd -WorkingDirectory $env:SystemRoot -ArgumentList @('/d', '/c', $apiCommand) -WindowStyle Hidden | Out-Null
}

$webListener = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if (-not $webListener) {
    $webCommand = "cd /d `"$frontend`" && `"$npm`" run dev -- --host 127.0.0.1 --port 5173"
    Start-Process -FilePath $cmd -WorkingDirectory $env:SystemRoot -ArgumentList @('/d', '/c', $webCommand) -WindowStyle Hidden | Out-Null
}

Start-Sleep -Seconds 2
Write-Output 'AttendEase services started in the background.'
Write-Output 'Frontend: http://localhost:5173'
Write-Output 'API health: http://localhost:5000/api/health'
