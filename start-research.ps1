param([ValidateRange(1,65535)][int]$Port = 8005)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv-research\Scripts\python.exe')) {
    python -m venv .venv-research
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
$researchPython = Join-Path $PSScriptRoot '.venv-research\Scripts\python.exe'
& $researchPython .\backend\check_dependencies.py torch torchvision numpy fastapi uvicorn multipart PIL
if ($LASTEXITCODE -ne 0) {
    & $researchPython -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed' }
    & $researchPython -m pip install -r backend\requirements.txt -r ml\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
$env:NEO_ENABLE_RESEARCH_MODEL = '1'
& $researchPython -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
