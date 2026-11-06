$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
# V19 nao copia chaves de outra instalacao sem autorizacao.
Write-Host '=== JARVIS NEXUS AGENT V1.9 - INSTALACAO INDEPENDENTE ===' -ForegroundColor Cyan
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    & py -3.12 --version
    if ($LASTEXITCODE -ne 0) { throw 'Instale Python 3.12: winget install --id Python.Python.3.12 --exact' }
    & py -3.12 -m venv '.venv'
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente virtual Python 3.12.' }
}
& $python -m pip install -r requirements.txt -c constraints-V18-validado.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha na instalacao de dependencias. Confira a mensagem acima.' }
& $python -m compileall -q main.py ui.py nexus core memory providers actions
if ($LASTEXITCODE -ne 0) { throw 'Erro de sintaxe na aplicacao.' }
Write-Host 'Dependencias instaladas. Para iniciar: .\INICIAR-NEXUS.ps1' -ForegroundColor Green
Write-Host 'O Playwright nao baixa navegadores extras nesta etapa. Use .venv\Scripts\python.exe -m playwright install chromium firefox se quiser automacao de navegador.'
