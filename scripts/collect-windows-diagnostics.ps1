param(
    [Parameter(Mandatory=$true)][string]$Engine,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$RuntimeTemp
)
$ErrorActionPreference = 'Stop'
if (Test-Path $Output) { throw 'Diagnostics destination must be new' }
New-Item -ItemType Directory -Path $Output | Out-Null
# Whitelist individual diagnostics; never copy engine, SDK or cooked payloads.
$files = @{
    'engine-receipt.json' = Join-Path $Engine '.builder-engine.json'
    'engine-transport.json' = Join-Path $Engine '.builder-transport.json'
    'BuildConfiguration.xml' = Join-Path $Engine 'Engine/Saved/UnrealBuildTool/BuildConfiguration.xml'
    'windows-builder-validation.json' = Join-Path $RuntimeTemp 'windows-builder-validation.json'
    'windows-runtime-smoke.log' = Join-Path $RuntimeTemp 'windows-runtime-smoke.log'
}
foreach ($name in $files.Keys) {
    if (Test-Path -LiteralPath $files[$name] -PathType Leaf) {
        Copy-Item -LiteralPath $files[$name] -Destination (Join-Path $Output $name) -Force
    }
}
$groups = @(
    @{Name='ubt'; Path=(Join-Path $Engine 'Engine/Programs/UnrealBuildTool'); Filter='Log*.txt'},
    @{Name='editor'; Path=(Join-Path $Workspace 'ArgonSDK/Saved/Logs'); Filter='*.log'},
    @{Name='installer'; Path=$RuntimeTemp; Filter='dd_setup_*_errors.log'}
)
foreach ($group in $groups) {
    if (Test-Path -LiteralPath $group.Path -PathType Container) {
        $dest = Join-Path $Output $group.Name
        New-Item -ItemType Directory -Path $dest | Out-Null
        Get-ChildItem -LiteralPath $group.Path -Filter $group.Filter -File -Force |
            Copy-Item -Destination $dest -Force
    }
}
Get-ChildItem -LiteralPath $Output -Recurse -File -Force | ForEach-Object {
    $_.Attributes = $_.Attributes -band (-bnot ([IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System))
}
