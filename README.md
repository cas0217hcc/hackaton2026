# Azure to Leaseweb Migration Assistant

Hackathon demo. Reads an Azure resource group, assesses Leaseweb fit, dry-runs Direct migrations,
and proposes infra plus code changes for Rebuild resources.

## Run

Needs `az` (logged in) on PATH, plus at least one AI provider (below).

    pip install -r requirements.txt
    python3 -m uvicorn migration_assistant.app:app
    # open http://127.0.0.1:8000, use sample_app/ as a source folder (up to 5 folders)

## Test

    python3 -m pytest

## AI provider

Pick what writes the assessments and plans with the **AI** button in the header (Save, then Test connection).

| Provider | Needs | Notes |
|---|---|---|
| Claude Code (CLI), the default | `claude` on PATH and logged in | Prompt goes on stdin, so large source folders work |
| Anthropic API | an API key | Paste it in the panel, or set `ANTHROPIC_API_KEY`. Kept in server memory only. Model defaults to `claude-opus-5-5` |
| opencode | `opencode` on PATH with a provider configured | Optional model as `provider/model`. Runs in an empty scratch folder |

To start with a different provider, set `AI_PROVIDER` (`claude-cli`, `anthropic-api`, `opencode`) and optionally `AI_MODEL` before starting the server.
