$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'UE4PrereqSetup_x64.exe'
$log = Join-Path $env:TEMP 'argon-ue-prerequisites.log'
$process = Start-Process -FilePath $installer -ArgumentList @('/quiet', '/norestart', '/log', $log) -Wait -PassThru
Write-Output ('UE prerequisite installer exit code: {0}' -f $process.ExitCode)
# 1638 means an equivalent/newer prerequisite bundle is already installed.
if ($process.ExitCode -notin @(0, 3010, 1638)) {
    if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 80 | Write-Output }
    throw ('UE prerequisite installation failed: {0}' -f $process.ExitCode)
}
