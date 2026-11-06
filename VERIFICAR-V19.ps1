$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Execute INSTALAR.ps1 primeiro.' }
$env:PYTHONUTF8='1'
$env:QT_QPA_PLATFORM='offscreen'
$env:NEXUS_LOG_DIR=Join-Path ([System.IO.Path]::GetTempPath()) ('JarvisNexusTests_'+[guid]::NewGuid().ToString('N'))
& $python -m compileall -q main.py ui.py nexus core memory providers actions tests
if ($LASTEXITCODE -ne 0) { throw 'Falha de sintaxe.' }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Falha nos testes.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependencias incompativeis.' }
Write-Host 'Verificacao V19 concluida. Os testes automaticos nao chamam APIs pagas.' -ForegroundColor Green
