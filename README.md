# Azure to Leaseweb Migration Assistant

Hackathon demo. Reads an Azure resource group, assesses Leaseweb fit, dry-runs Direct migrations,
and proposes infra plus code changes for Rebuild resources.

## Run

Needs `az` (logged in) and `claude` (logged in) on PATH.

    pip install -r requirements.txt
    python3 -m uvicorn migration_assistant.app:app
    # open http://127.0.0.1:8000, use sample_app/ as a source folder (up to 5 folders)

## Test

    python3 -m pytest
