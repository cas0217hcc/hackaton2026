import json
import re
import subprocess
from typing import Callable


class ClaudeError(Exception):
    pass


def ask_json(prompt: str, timeout: int = 180, runner: Callable = subprocess.run) -> dict:
    """Run `claude -p` headless and parse a JSON object from its answer."""
    full = prompt + "\n\nAnswer with a single JSON object only, no prose."
    try:
        proc = runner(["claude", "-p", full], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"claude timed out after {timeout}s") from None
    except FileNotFoundError:
        raise ClaudeError("claude CLI not found on PATH") from None
    if proc.returncode != 0:
        raise ClaudeError(f"claude failed: {proc.stderr.strip()}")
    text = proc.stdout.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1]):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ClaudeError("claude did not return valid JSON")
