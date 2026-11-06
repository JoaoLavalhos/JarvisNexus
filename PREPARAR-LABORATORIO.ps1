$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$parent = 'C:\JarvisNexusLaboratorio'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$target = Join-Path $parent ('Nexus_Experimento_'+$stamp)
if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
if (Test-Path $target) { throw 'O destino ja existe. Nenhum arquivo foi alterado.' }
New-Item -ItemType Directory -Path $target | Out-Null
Write-Host 'Criando COPIA DE LABORATORIO (sem credenciais, logs ou gravacoes):' -ForegroundColor Cyan
Write-Host $target
# /E copies the source; /XD and /XF exclude credentials and runtime state.
& robocopy.exe "$source" "$target" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /XD .venv __pycache__ .git logs agent_workspace gravacoes relatorios /XF api_keys.json nexus_agent_voice.json *.pyc *.log *.jsonl *.wav *.mp3 *.env
$code = $LASTEXITCODE
if ($code -ge 8) { throw "Robocopy falhou com codigo $code. Verifique a copia antes de continuar." }
@'
LABORATORIO NEXUS

Esta pasta e uma COPIA do codigo para experimentos.
Nunca mande o agente modificar o programa original enquanto estiver aberto.
Use modo PLAN inicialmente e revise o plano antes de permitir BUILD.
Nao ha chaves de API nesta copia. Verifique os arquivos antes de publicar.
Execute compilacao, testes, diff e revisao manual ANTES de migrar alteracoes.
Nao conceda acesso irrestrito ao disco.
'@ | Set-Content -LiteralPath (Join-Path $target 'COMO-TESTAR-LABORATORIO.txt') -Encoding UTF8
Write-Host 'Copia concluida. Abra o NEXUS AGENT e selecione esta pasta de trabalho:' -ForegroundColor Green
Write-Host $target
