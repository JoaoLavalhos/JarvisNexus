$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git nao instalado: instale Git for Windows antes de executar.'
}
$dest = Join-Path $PSScriptRoot 'backup-fonte-opencode'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$work = Join-Path $dest "opencode-oficial-$stamp"
Write-Host 'Baixando codigo-fonte oficial do OpenCode...' -ForegroundColor Cyan
& git clone --depth 1 https://github.com/anomalyco/opencode.git "$work"
if ($LASTEXITCODE -ne 0) { throw 'Falha ao clonar repositorio oficial.' }
$sha = (& git -C "$work" rev-parse HEAD).Trim()
$remote = (& git -C "$work" remote get-url origin).Trim()
$version = & git -C "$work" describe --always --tags 2>$null
$notes = @"
Projeto: anomalyco/opencode
Origem: $remote
Commit completo: $sha
Ref/tags: $version
Data local: $(Get-Date -Format o)
Observacao: arquivo de codigo-fonte publico; nao inclui credenciais, planos, acesso a modelos nem executavel compilado.
Licenca: consulte LICENSE na raiz do codigo clonado.
"@
$notes | Set-Content -LiteralPath (Join-Path $dest "MANIFESTO-$stamp.txt") -Encoding UTF8
# Arquivo Git do commit: preserva os arquivos versionados, inclusive ocultos; .git fica na pasta clonada.
$zip = Join-Path $dest "opencode-fonte-$stamp-$($sha.Substring(0,12)).zip"
& git -C "$work" archive --format=zip -o "$zip" HEAD
if ($LASTEXITCODE -ne 0) { throw "Falha ao exportar o commit para ZIP." }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash
"SHA256: $hash" | Add-Content -LiteralPath (Join-Path $dest "MANIFESTO-$stamp.txt") -Encoding UTF8
Write-Host "Codigo salvo em: $work" -ForegroundColor Green
Write-Host "ZIP offline: $zip" -ForegroundColor Green
Write-Host "Commit: $sha" -ForegroundColor Green
Write-Host "SHA256: $hash" -ForegroundColor Green
