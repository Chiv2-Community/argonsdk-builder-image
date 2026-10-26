param([Parameter(Mandatory=$true)][string]$Engine)
$ErrorActionPreference = 'Stop'
$probe = Join-Path $env:RUNNER_TEMP 'ue-runtime-probe'
if (Test-Path $probe) { throw 'Runtime smoke requires a fresh project' }
New-Item -ItemType Directory -Path (Join-Path $probe 'Content') | Out-Null
$project = Join-Path $probe 'Probe.uproject'
'{"FileVersion":3,"EngineAssociation":"","Plugins":[]}' | Set-Content $project
$editor = Join-Path $Engine 'Engine/Binaries/Win64/UE4Editor-Cmd.exe'
# Exercise one explicit engine package, not an implicit project-wide cook.
& $editor $project -run=Cook -TargetPlatform=WindowsNoEditor -cooksinglepackage '-Map=/Engine/EngineMaterials/DefaultMaterial' -unattended -NullRHI -nop4 -nosplash -stdout -FullStdOutLogOutput 2>&1 |
    Tee-Object -FilePath (Join-Path $env:RUNNER_TEMP 'windows-runtime-smoke.log')
if ($LASTEXITCODE -ne 0) {
    $code = $LASTEXITCODE -band 0xFFFFFFFFL
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    $vs = & $vswhere -products '*' -version '[16.0,17.0)' -latest -property installationPath
    $dumpbin = Join-Path $vs 'VC/Tools/MSVC/14.24.28314/bin/Hostx64/x64/dumpbin.exe'
    if (Test-Path $dumpbin) {
        & $dumpbin /dependents $editor 2>&1 |
            Tee-Object -Append -FilePath (Join-Path $env:RUNNER_TEMP 'windows-runtime-smoke.log')
    }
    throw ('Windows runtime smoke failed: 0x{0:X8}' -f $code)
}
