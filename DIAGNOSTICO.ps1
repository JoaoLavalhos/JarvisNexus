$ErrorActionPreference = 'Stop'
$base=$PSScriptRoot
Write-Host '=== NEXUS DIAGNOSTICOS V1.4 ===' -ForegroundColor Cyan
$python=Join-Path $base '.venv\Scripts\python.exe'
if (Test-Path $python) {
  & $python --version
  & $python -m pip show PyQt6 edge-tts keyring sounddevice | Select-String 'Name:|Version:'
} else {Write-Host 'Falta .venv; execute INSTALAR.ps1'}
& opencode.cmd --version
Get-ChildItem (Join-Path $base 'logs') -File -ErrorAction SilentlyContinue | Select-Object Name,Length,LastWriteTime
Write-Host 'Leia os logs antes de enviar: podem conter nomes e caminhos de arquivos pessoais.'
