param([switch]$Lan)
$ErrorActionPreference = 'Stop'
$listenAddress = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
$logDirectory = Join-Path $PSScriptRoot 'storage\logs'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$logFile = Join-Path $logDirectory (Get-Date -Format 'yyyyMMdd-HHmmss')
$logFile += '.log'
Start-Transcript -Path $logFile -Force | Out-Null
try {
    Write-Host "CKOS log file: $logFile" -ForegroundColor Cyan
    try {
        $existing = Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8000/openapi.json' -TimeoutSec 2
    } catch {
        $existing = $null
    }
    if ($existing) {
        $downloadRoute = '/api/industry/projects/{project_id}/download/docx'
        if ($existing.paths.PSObject.Properties.Name -contains $downloadRoute) {
            if ($Lan) {
                Write-Host 'CKOS is already running. To enable LAN access, stop the existing server with Ctrl+C and run start-lan.cmd.' -ForegroundColor Yellow
                return
            }
            Write-Host 'The current CKOS version is already running at http://127.0.0.1:8000/industry' -ForegroundColor Green
            Write-Host 'No second server was started.' -ForegroundColor Yellow
            return
        }
        Write-Host 'An outdated CKOS process is using port 8000.' -ForegroundColor Red
        Write-Host 'Stop its PowerShell window with Ctrl+C, then run this script again.' -ForegroundColor Yellow
        throw 'Outdated CKOS server detected on port 8000.'
    }
    $pgReady = 'D:\yidui\postgresql\bin\pg_isready.exe'
    $pgControl = 'D:\yidui\postgresql\bin\pg_ctl.exe'
    $pgData = 'D:\yidui\postgresql\data'
    & $pgReady -h 127.0.0.1 -p 5432 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'PostgreSQL is not ready; starting the local database...' -ForegroundColor Cyan
        & $pgControl start -D $pgData -w
        if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed.' }
    }
    Write-Host 'Checking and indexing local reports...' -ForegroundColor Cyan
    & 'D:\yidui\miniconda\envs\ckos\python.exe' -m app.kb
    if ($LASTEXITCODE -ne 0) { throw 'Document indexing failed.' }
    & 'D:\yidui\miniconda\envs\ckos\python.exe' -m app.structured
    if ($LASTEXITCODE -ne 0) { throw 'Structured document processing failed.' }
    Write-Host 'Open http://127.0.0.1:8000/industry after startup. Keep this window open for live logs.' -ForegroundColor Green
    if ($Lan) {
        Write-Host 'LAN mode: trusted local network only. Users share access to reports and paid API actions.' -ForegroundColor Yellow
        Write-Host 'Other devices: http://<this-computer-LAN-IP>:8000/industry (not 0.0.0.0 or 127.0.0.1).' -ForegroundColor Cyan
    }
    & 'D:\yidui\miniconda\envs\ckos\python.exe' -m uvicorn app.main:app --host $listenAddress --port 8000 --log-level info
    if ($LASTEXITCODE -ne 0) { throw "Server exited with code $LASTEXITCODE." }
} catch {
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Full log: $logFile" -ForegroundColor Yellow
    throw
} finally {
    Stop-Transcript | Out-Null
}
