$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Execute INSTALAR.ps1 antes de iniciar.' }
$env:MARK_GROQ_STT = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONFAULTHANDLER = '1'
Write-Host 'JARVIS NEXUS AGENT V1.9 - GROQ + GEMINI + GPT (OpenCode)' -ForegroundColor Cyan
Write-Host 'Selecione Gemini Live ou Agente GPT. F8 abre EXECUCAO DO AGENTE. ARQUIVO PARA EDITAR escolhe o alvo. Ctrl+Espaco: falar.'
Write-Host "Diagnosticos: $PSScriptRoot\logs\nexus.log | Conversas: $PSScriptRoot\logs\Activity.log" -ForegroundColor Yellow
& $python main.py
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host "O JARVIS encerrou com codigo $code" -ForegroundColor Red
    Write-Host "Consulte: $PSScriptRoot\logs\nexus.log e falha_fatal.log" -ForegroundColor Yellow
}
exit $code
