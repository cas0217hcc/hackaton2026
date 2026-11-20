#!/usr/bin/env bash
# Start the Azure to Leaseweb Migration Assistant (Linux and macOS).
# Creates a .venv on first run, installs requirements.txt when it changed, then starts the server.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
RELOAD=()

usage() {
  cat <<'USAGE'
Usage: ./start.sh [--host HOST] [--port PORT] [--reload]

  --host HOST   address to listen on (default 127.0.0.1, or $HOST)
  --port PORT   port to listen on (default 8000, or $PORT)
  --reload      restart the server when the code changes (for development)
  -h, --help    show this help

AI_PROVIDER, AI_MODEL and ANTHROPIC_API_KEY are passed through to the app.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:?--host needs a value}"; shift 2 ;;
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    --reload) RELOAD=(--reload); shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$PORT" in ''|*[!0-9]*) echo "Port must be a number, got '$PORT'." >&2; exit 2 ;; esac

# Python 3.10 or newer
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is required but was not found." >&2
  exit 1
fi

# Virtual environment
if [ ! -x .venv/bin/python ]; then
  echo "Creating the virtual environment in .venv ..."
  "$PY" -m venv .venv || { echo "Could not create .venv. On Debian or Ubuntu try: sudo apt install python3-venv" >&2; exit 1; }
fi

# Install requirements only when requirements.txt changed
if command -v sha256sum >/dev/null 2>&1; then want="$(sha256sum requirements.txt | cut -d' ' -f1)"; else want="$(shasum -a 256 requirements.txt | cut -d' ' -f1)"; fi
have="$(cat .venv/.requirements.sha256 2>/dev/null || true)"
if [ "$want" != "$have" ]; then
  echo "Installing requirements ..."
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
  echo "$want" > .venv/.requirements.sha256
fi

# Friendly notes (none of these stop the server)
command -v az >/dev/null 2>&1 || echo "Note: 'az' was not found. Discover needs the Azure CLI (az login)." >&2
if ! command -v claude >/dev/null 2>&1 && ! command -v opencode >/dev/null 2>&1 && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Note: no AI provider found (claude, opencode or ANTHROPIC_API_KEY). Choose one with the AI button in the app." >&2
fi
case "$HOST" in 127.0.0.1|localhost|::1) ;; *) echo "Warning: listening on $HOST. The app has no login, so only do this on a network you trust." >&2 ;; esac

echo "Starting on http://$HOST:$PORT  (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn migration_assistant.app:app --host "$HOST" --port "$PORT" ${RELOAD[@]+"${RELOAD[@]}"}
