from pathlib import Path

from migration_assistant.plan import read_source


def test_read_source_finds_sample_app():
    files = read_source(Path("sample_app"))
    assert {"secrets.py", "storage.py"} <= set(files)
    assert "SecretClient" in files["secrets.py"]
