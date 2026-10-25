"""Lock the legacy UBT XML settings; -2019 alone does not select v142."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = {'ue': 'https://www.unrealengine.com/BuildConfiguration'}


class WindowsToolchainTests(unittest.TestCase):
    def test_legacy_ubt_config_pins_compiler_and_sdk(self):
        config = ET.parse(ROOT / 'scripts/windows-build-configuration.xml')
        for key, expected in {
            'Compiler': 'VisualStudio2019',
            'CompilerVersion': '14.24.28315',
            'WindowsSdkVersion': '10.0.19041.0',
        }.items():
            self.assertEqual(config.findtext(f'ue:WindowsPlatform/ue:{key}', namespaces=NS), expected)
        self.assertEqual(config.findtext('ue:BuildConfiguration/ue:MaxParallelActions', namespaces=NS), '2')

    def test_installer_and_build_use_locked_configuration(self):
        script = (ROOT / 'scripts/build-windows-engine.ps1').read_text()
        self.assertIn('Microsoft.VisualStudio.Component.VC.14.24.x86.x64', script)
        self.assertIn('VC/Tools/MSVC/14.24.28314', script)
        self.assertIn('Windows Kits/10/Include/10.0.19041.0/um/Windows.h', script)
        self.assertIn('windows-build-configuration.xml', script)
        self.assertNotIn('-WindowsSdkVersion=', script)
        self.assertIn('$version.ProductBuildPart', script)
        self.assertIn('$config.Configuration.WindowsPlatform.CompilerVersion = $compilerVersion', script)
        self.assertLess(script.index('Copy-Item'), script.index('& ./GenerateProjectFiles.bat'))
