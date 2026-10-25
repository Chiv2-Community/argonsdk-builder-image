param([Parameter(Mandatory=$true)][string]$Engine)
$ErrorActionPreference = 'Stop'
$manifest = Get-Item -LiteralPath (Join-Path $Engine '.ue4dependencies') -Force
if ($manifest.PSIsContainer -or $manifest.Length -eq 0) {
    throw 'Dependency completion manifest must be a nonempty file'
}
