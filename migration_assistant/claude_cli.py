import json
import re
import subprocess
from typing import Callable


class ClaudeError(Exception):
    """Any problem getting an answer from an AI provider (name kept for the Claude Code backend)."""


JSON_ONLY = "\n\nAnswer with a single JSON object only, no prose."


def parse_json(text: str) -> dict:
    """Find a JSON object in a model answer: plain, fenced, or surrounded by prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ClaudeError("the AI did not return valid JSON")


MODEL_RE = re.compile(r"(opus|sonnet|haiku|claude-[A-Za-z0-9][\w.\-\[\]]*)")


def ask_json(prompt: str, timeout: int = 180, runner: Callable = subprocess.run, model: str = "") -> dict:
    """Run `claude -p` headless and parse a JSON object from its answer.

    The prompt goes on stdin: a command-line argument over ~128 KB fails, and big source folders exceed it.
    """
    if model and not MODEL_RE.fullmatch(model):
        raise ClaudeError("Claude Code model must be opus, sonnet, haiku or a claude-... model id.")
    cmd = ["claude", "-p"] + (["--model", model] if model else [])
    try:
        proc = runner(cmd, input=prompt + JSON_ONLY, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"claude timed out after {timeout}s") from None
    except FileNotFoundError:
        raise ClaudeError("claude CLI not found on PATH") from None
    if proc.returncode != 0:
        raise ClaudeError(f"claude failed: {proc.stderr.strip()}")
    return parse_json(proc.stdout)
