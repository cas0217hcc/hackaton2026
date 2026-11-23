"""Read settings from a .env file (KEY=value lines), so they need not be typed before every start.

Variables already set in the environment win, so `MOCK_MODE=0 ./start.sh` still overrides the file.
"""
import os
import re
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"  # the repo root, wherever the server is started from
_LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*")


def parse_env(text: str) -> dict[str, str]:
    """KEY=value pairs. Blank lines and # comments are skipped; values may be wrapped in single or double quotes."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE.fullmatch(line)
        if not m:
            continue
        key, value = m.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.sub(r"\s+#.*$", "", value)  # KEY=value  # comment
        out[key] = value
    return out


def load_env(path: Path = ENV_FILE, environ: dict | None = None) -> dict[str, str]:
    """Copy the file's variables into the environment unless already set. Returns what was applied."""
    environ = os.environ if environ is None else environ
    try:
        values = parse_env(path.read_text(encoding="utf-8-sig"))
    except OSError:  # no file (the usual case) or unreadable: nothing to do
        return {}
    applied = {k: v for k, v in values.items() if k not in environ}
    environ.update(applied)
    return applied
