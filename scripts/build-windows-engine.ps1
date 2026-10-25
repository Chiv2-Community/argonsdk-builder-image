param([Parameter(Mandatory=$true)][string]$Engine)
$ErrorActionPreference = 'Stop'
$Engine = (Resolve-Path $Engine).Path
$builder = Split-Path $PSScriptRoot -Parent
$lock = Get-Content "$builder/build-lock.json" -Raw | ConvertFrom-Json
$head = git -C $Engine rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head -ne $lock.engine.commit) { throw 'UE source pin mismatch' }
$status = git -C $Engine status --porcelain
if ($LASTEXITCODE -ne 0 -or $status) { throw 'Engine source must start clean' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs2019 = & $vswhere -products '*' -version '[16.0,17.0)' -latest -property installationPath
$compilerDirectory = 'VC/Tools/MSVC/14.24.28314'
$sdkInclude = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/Include/10.0.19041.0/um/Windows.h'
if (!$vs2019 -or !(Test-Path (Join-Path $vs2019 "$compilerDirectory/bin/Hostx64/x64/cl.exe")) -or !(Test-Path $sdkInclude)) {
    $installer = Join-Path $env:RUNNER_TEMP 'vs2019-buildtools.exe'
    Invoke-WebRequest 'https://aka.ms/vs/16/release/vs_buildtools.exe' -OutFile $installer
    $signature = Get-AuthenticodeSignature $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw 'Visual Studio installer signature verification failed'
    }
    Get-FileHash $installer -Algorithm SHA256
    $install = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
        '--quiet', '--wait', '--norestart', '--nocache',
        '--installPath', 'C:\VS2019',
        '--add', 'Microsoft.VisualStudio.Component.VC.14.24.16.4.x86.x64',
        '--add', 'Microsoft.VisualStudio.Component.Windows10SDK.19041'
    )
    if ($install.ExitCode -notin @(0, 3010)) { throw "VS2019 installation failed: $($install.ExitCode)" }
}
$vs2019 = & $vswhere -products '*' -version '[16.0,17.0)' -latest -property installationPath
if (!$vs2019 -or !(Test-Path (Join-Path $vs2019 "$compilerDirectory/bin/Hostx64/x64/cl.exe")) -or !(Test-Path $sdkInclude)) {
    throw 'Required VS2019 16.4 compiler or Windows SDK 19041 is missing'
}
# Later user config files override Engine/Saved in this UE revision.
foreach ($base in @($env:APPDATA, [Environment]::GetFolderPath('MyDocuments'))) {
    if ($base -and (Test-Path (Join-Path $base 'Unreal Engine/UnrealBuildTool/BuildConfiguration.xml'))) {
        throw 'User UBT configuration would override the locked toolchain'
    }
}
$configDir = Join-Path $Engine 'Engine/Saved/UnrealBuildTool'
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
Copy-Item "$PSScriptRoot/windows-build-configuration.xml" "$configDir/BuildConfiguration.xml"
Get-Content "$configDir/BuildConfiguration.xml"
Push-Location $Engine
try {
    # Preserve the committed source identity before recorded transport changes.
    $archive = Join-Path $env:RUNNER_TEMP 'ue-source.tar'
    git archive --format=tar "--output=$archive" $lock.engine.commit
    if ($LASTEXITCODE -ne 0) { throw 'Source archive failed' }
    python "$builder/scripts/engine_tools.py" https-transport --engine $Engine
    if ($LASTEXITCODE -ne 0) { throw 'HTTPS transport setup failed' }
    # Root Setup.bat also adds --prompt; invoke dependencies directly.
    & ./Engine/Binaries/DotNET/GitDependencies.exe --force --threads=4 --max-retries=2 `
        --exclude=Linux --exclude=Mac --exclude=Android --exclude=IOS --exclude=TVOS `
        --exclude=Win32 --exclude=HoloLens
    if ($LASTEXITCODE -ne 0) { throw 'Windows dependency download failed' }
    & "$PSScriptRoot/check-windows-dependencies.ps1" -Engine $Engine
    & ./GenerateProjectFiles.bat -2019
    if ($LASTEXITCODE -ne 0) { throw 'Windows project generation failed' }
    foreach ($target in @('UE4Editor', 'ShaderCompileWorker', 'UnrealPak')) {
        & ./Engine/Build/BatchFiles/Build.bat $target Win64 Development -2019 `
            -NoDebugInfo -NoPDB -MaxParallelActions=2
        if ($LASTEXITCODE -ne 0) { throw "Engine target failed: $target" }
        Get-PSDrive -PSProvider FileSystem | Select-Object Name, Used, Free
    }
    python "$builder/scripts/engine_tools.py" receipt --engine $Engine `
        --lock "$builder/build-lock.json" --platform Win64 --archive $archive
    if ($LASTEXITCODE -ne 0) { throw 'Engine receipt generation failed' }
} finally {
    Pop-Location
}
