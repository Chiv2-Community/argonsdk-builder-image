param(
    [Parameter(Mandatory=$true)][string]$Engine,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][string]$Descriptor
)
$ErrorActionPreference = 'Stop'
$Engine = (Resolve-Path $Engine).Path
$Descriptor = (Resolve-Path $Descriptor).Path
$builder = Split-Path $PSScriptRoot -Parent
$cli = Join-Path $PSScriptRoot 'builder.py'
if (Test-Path $Workspace) { throw 'Validation requires a fresh workspace' }
# This job owns the ephemeral checkout. Retain Git metadata outside the built
# tree so receipt validation covers the recorded transport-patched archive.
$gitMetadata = Join-Path $env:RUNNER_TEMP 'ue-validation-git-metadata'
if (Test-Path $gitMetadata) { throw 'Git metadata archive already exists' }
Move-Item -LiteralPath (Join-Path $Engine '.git') -Destination $gitMetadata
python "$PSScriptRoot/engine_tools.py" check --engine $Engine --lock "$builder/build-lock.json" --platform Win64
if ($LASTEXITCODE -ne 0) { throw 'Built engine receipt verification failed' }
python $cli --mod-config $Descriptor prepare --workspace $Workspace
if ($LASTEXITCODE -ne 0) { throw 'External source preparation failed' }
$sdk = Join-Path $Workspace 'ArgonSDK'
python $cli build-editor --engine $Engine --sdk $sdk
if ($LASTEXITCODE -ne 0) { throw 'Windows SDK editor build failed' }
python $cli --mod-config $Descriptor cook --engine $Engine --sdk $sdk
if ($LASTEXITCODE -ne 0) { throw 'Windows source cook failed' }
$output = Join-Path $Workspace 'dist'
python $cli --mod-config $Descriptor package --engine $Engine --sdk $sdk --output $output
if ($LASTEXITCODE -ne 0) { throw 'Windows package validation failed' }
$manifest = Get-Content (Join-Path $output 'manifest.json') -Raw | ConvertFrom-Json
if ($manifest.cook.verification -ne 'cook_command_returned_zero') { throw 'Actual source cooking is required' }
# Publish diagnostics only, not licensed binaries, source assets, or the PAK.
@{
    verification = 'native_windows_source_cook_and_package_passed'
    engine_commit = $manifest.engine.commit
    cooked_files = @($manifest.files).Count
    requested_packages = @($manifest.cook.requested_packages).Count
    cook_batches = @($manifest.cook.commands).Count
    packaged_packages = @($manifest.files | Where-Object { $_.path -match '\.(uasset|umap)$' }).Count
    pak_sha256 = $manifest.pak_sha256
    container_validation = 'not_run'
    game_runtime_validation = 'not_run'
} | ConvertTo-Json | Set-Content (Join-Path $env:RUNNER_TEMP 'windows-builder-validation.json')
