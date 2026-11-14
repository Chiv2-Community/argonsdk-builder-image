from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell required')
class WindowsDockerTests(unittest.TestCase):
    def test_prerequisite_installer_reports_and_checks_exit_codes(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/install-windows-cooker-runtime.ps1'
        for code in (0, 3010, 1638, 1603):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / 'argon-ue-prerequisites.log').write_text('installer diagnostic fixture')
                command = ("$ErrorActionPreference='Stop'; $env:TEMP='" + directory + "'; "
                           "function Start-Process { [pscustomobject]@{ExitCode=" + str(code) + "} }; "
                           "& '" + str(script) + "'")
                result = subprocess.run(['pwsh', '-NoProfile', '-Command', command],
                                        capture_output=True, text=True)
                self.assertIn(f'installer exit code: {code}', result.stdout)
                self.assertEqual(result.returncode == 0, code in (0, 3010, 1638), result.stderr)
                if code == 1603:
                    self.assertIn('installer diagnostic fixture', result.stdout)

    def run_probe(self, status='Running', daemon='windows', failures=0):
        script = Path(__file__).resolve().parents[1] / 'scripts/start-windows-docker.ps1'
        code = """
$ErrorActionPreference = 'Stop'
$global:calls = 0
$global:starts = 0
function Get-Service {
    $service = [pscustomobject]@{Status='STATUS'}
    $service | Add-Member ScriptMethod WaitForStatus { param($state, $timeout) }
    return $service
}
function Start-Service { $global:starts++ }
function Start-Sleep {}
function docker {
    $global:calls++
    if ($global:calls -le FAILURES) { $global:LASTEXITCODE=1; return }
    $global:LASTEXITCODE=0
    '{"OSType":"DAEMON","ServerVersion":"fixture"}'
}
& 'SCRIPT'
"starts=$global:starts calls=$global:calls"
""".replace('STATUS', status).replace('DAEMON', daemon).replace('FAILURES', str(failures)).replace('SCRIPT', str(script))
        return subprocess.run(['pwsh', '-NoProfile', '-Command', code], capture_output=True, text=True)

    def test_running_service_is_not_restarted(self):
        result = self.run_probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('starts=0 calls=1', result.stdout)

    def test_stopped_service_is_started_and_pipe_readiness_retried(self):
        result = self.run_probe(status='Stopped', failures=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('starts=1 calls=3', result.stdout)

    def test_linux_daemon_is_rejected(self):
        result = self.run_probe(daemon='linux')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Windows container daemon', result.stderr)

    def test_unavailable_daemon_fails_after_bounded_retries(self):
        result = self.run_probe(failures=99)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('did not become ready', result.stderr)
