$ErrorActionPreference = 'Stop'
$service = Get-Service -Name docker -ErrorAction Stop
if ($service.Status -ne 'Running') {
    Start-Service -Name docker
    $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(60))
}
# Service readiness can precede the named pipe becoming available.
$ready = $false
for ($attempt = 0; $attempt -lt 12; $attempt++) {
    $info = docker info --format '{{json .}}'
    if ($LASTEXITCODE -eq 0) {
        $daemon = $info | ConvertFrom-Json
        if ($daemon.OSType -ne 'windows') { throw 'A Windows container daemon is required' }
        $ready = $true
        break
    }
    Start-Sleep -Seconds 5
}
if (!$ready) { throw 'Docker service started but the daemon did not become ready' }
Write-Output "Windows Docker daemon ready: $($daemon.ServerVersion)"
