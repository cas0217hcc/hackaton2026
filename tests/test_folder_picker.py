import os
import subprocess

import pytest

from migration_assistant.folder_picker import FolderPickerError, pick_folder


def fake(stdout="", returncode=0, seen=None):
    def run(cmd, **kw):
        if seen is not None:
            seen.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")
    return run


def test_returns_normalised_path():
    assert pick_folder(runner=fake("C:/src/app\n")) == os.path.normpath("C:/src/app")


def test_cancel_returns_empty():
    assert pick_folder(runner=fake("\n")) == ""


def test_initial_dir_passed_only_when_it_exists(tmp_path):
    seen = []
    pick_folder(str(tmp_path), runner=fake(seen=seen))
    pick_folder(str(tmp_path / "missing"), runner=fake(seen=seen))
    assert seen[0][-1] == str(tmp_path) and seen[1][-1] == ""


def test_failure_raises():
    with pytest.raises(FolderPickerError):
        pick_folder(runner=fake(returncode=1))
