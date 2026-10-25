$ErrorActionPreference = 'Stop'
$report = Join-Path $env:RUNNER_TEMP 'argon-windows-host.json'
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' |
    Select-Object DeviceID, Size, FreeSpace)
$cpu = Get-CimInstance Win32_ComputerSystem
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs = & $vswhere -latest -products '*' -property installationPath
if ($LASTEXITCODE -ne 0) { throw 'Visual Studio discovery failed' }
$compilers = @(Get-ChildItem "$vs/VC/Tools/MSVC" -Directory | Select-Object -ExpandProperty Name)
$info = docker info --format '{{json .}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is unavailable' }
$docker = $info | ConvertFrom-Json
if ($docker.OSType -ne 'windows') { throw 'A Windows container daemon is required' }
docker run --rm --isolation=process mcr.microsoft.com/windows/servercore:ltsc2022 cmd /c ver
if ($LASTEXITCODE -ne 0) { throw 'Windows Server Core container smoke failed' }
@{
    runner_image = $env:ImageVersion
    os = [Environment]::OSVersion.VersionString
    logical_processors = $cpu.NumberOfLogicalProcessors
    memory_bytes = $cpu.TotalPhysicalMemory
    disks = $disks
    visual_studio = $vs
    msvc_versions = $compilers
    docker_os = $docker.OSType
    docker_root = $docker.DockerRootDir
    container_smoke = 'passed'
} | ConvertTo-Json -Depth 5 | Tee-Object -FilePath $report
