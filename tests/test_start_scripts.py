import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_the_linux_script_exists_is_executable_and_parses():
    script = ROOT / "start.sh"
    assert script.exists() and os.access(script, os.X_OK)
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0


def test_the_linux_script_explains_its_options():
    out = subprocess.run(["bash", str(ROOT / "start.sh"), "--help"], capture_output=True, text=True)
    assert out.returncode == 0
    for option in ("--port", "--host", "--reload"):
        assert option in out.stdout


def test_the_linux_script_rejects_an_unknown_option_without_starting_anything():
    out = subprocess.run(["bash", str(ROOT / "start.sh"), "--nope"], capture_output=True, text=True, timeout=20)
    assert out.returncode != 0 and "--nope" in out.stderr


def test_the_windows_scripts_exist_with_the_same_options():
    ps1 = (ROOT / "start.ps1").read_text()
    for name in ("Port", "BindHost", "Reload"):
        assert f"${name}" in ps1
    bat = (ROOT / "start.bat").read_text()
    assert "start.ps1" in bat and "ExecutionPolicy" in bat


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell is not installed here")
def test_the_powershell_script_parses():
    cmd = "$e=$null; [System.Management.Automation.Language.Parser]::ParseFile('start.ps1',[ref]$null,[ref]$e)|Out-Null; if($e){$e;exit 1}"
    assert subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], cwd=ROOT).returncode == 0
