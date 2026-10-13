param([ValidateRange(1,65535)][int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
& .\.venv\Scripts\python.exe .\backend\check_dependencies.py fastapi uvicorn multipart PIL
if ($LASTEXITCODE -ne 0) {
    & .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
$env:NEO_ENABLE_RESEARCH_MODEL = '0'
& .\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
