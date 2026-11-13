param(
    [Parameter(Mandatory=$true)][string]$Engine,
    [Parameter(Mandatory=$true)][string]$Sdk,
    [Parameter(Mandatory=$true)][string]$Context,
    [Parameter(Mandatory=$true)][string]$BaseImage,
    [Parameter(Mandatory=$true)][string]$Tag
)
$ErrorActionPreference = 'Stop'
if ($BaseImage -notmatch '^mcr\.microsoft\.com/windows/servercore@sha256:[0-9a-f]{64}$') { throw 'A resolved Server Core digest is required' }
if (Test-Path $Context) { throw 'Image context must be new' }
$builder = Split-Path $PSScriptRoot -Parent
function Copy-Tree([string]$Source, [string]$Target, [string[]]$Excluded = @()) {
    $arguments = @($Source, $Target, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS')
    if ($Excluded.Count) { $arguments += @('/XD') + $Excluded }
    & robocopy @arguments
    if ($LASTEXITCODE -gt 7) { throw "Image staging failed: $Source" }
}
New-Item -ItemType Directory $Context | Out-Null
Copy-Tree $Engine "$Context/engine" @('.git', 'Intermediate', 'Saved', 'DerivedDataCache')
Copy-Tree $Sdk "$Context/sdk" @('Intermediate', 'Saved', 'DerivedDataCache')
$pythonRoot = python -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Python lookup failed' }
Copy-Tree $pythonRoot "$Context/python" @('__pycache__', 'site-packages')
$gitRoot = Split-Path (Split-Path (Get-Command git).Source -Parent) -Parent
Copy-Tree $gitRoot "$Context/git"
New-Item -ItemType Directory "$Context/builder" | Out-Null
Copy-Item "$builder/build-lock.json" "$Context/builder/"
Copy-Tree "$builder/scripts" "$Context/builder/scripts" @('__pycache__')
Copy-Item "$builder/Dockerfile.windows-cooker-probe" "$Context/Dockerfile"
docker build --isolation=process --build-arg "WINDOWS_BASE_IMAGE=$BaseImage" --tag $Tag $Context
if ($LASTEXITCODE -ne 0) { throw 'Windows cooker image build failed' }
