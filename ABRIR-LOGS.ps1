$path=Join-Path $PSScriptRoot 'logs'
if (!(Test-Path $path)) {New-Item -ItemType Directory -Path $path -Force | Out-Null}
Start-Process explorer.exe $path
