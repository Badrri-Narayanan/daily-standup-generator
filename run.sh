#!/usr/bin/env bash
# Start the standup generator and open it in the browser. Ctrl+C stops it.
# Usage: ./run.sh            (PORT=9000 ./run.sh to prefer another port)
set -euo pipefail

cd "$(dirname "$0")"
VENV=.venv
PY="$VENV/bin/python"
STAMP="$VENV/.standup-installed"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

# (Re)install only when the venv is missing or pyproject.toml changed since the last install.
if [[ ! -x "$PY" ]]; then
  echo "Creating virtualenv…"
  uv venv --quiet --python 3.12 "$VENV"
fi
if [[ ! -f "$STAMP" || pyproject.toml -nt "$STAMP" ]] || ! "$PY" -c "import standup_generator" 2>/dev/null; then
  echo "Installing dependencies…"
  uv pip install --quiet --python "$PY" -e .
  touch "$STAMP"
fi

PORT=$("$PY" - "${PORT:-8765}" <<'EOF'
import socket, sys
start = int(sys.argv[1])
for port in range(start, start + 50):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        break
else:
    sys.exit(f"no free port between {start} and {start + 49}")
EOF
)
URL="http://127.0.0.1:$PORT/"

open_browser() {
  for _ in $(seq 1 150); do
    if curl -fs -o /dev/null "${URL}api/window"; then
      case "$(uname -s)" in
        Darwin) open "$URL" ;;
        Linux) xdg-open "$URL" >/dev/null 2>&1 ;;
        MINGW* | MSYS* | CYGWIN*) cmd.exe /c start "" "$URL" ;;
        *) echo "Open $URL in your browser" ;;
      esac
      return
    fi
    sleep 0.2
  done
  echo "Server did not answer within 30s; try $URL" >&2
}

open_browser &
OPENER=$!
cleanup() { kill "$OPENER" 2>/dev/null || true; }
trap cleanup EXIT

echo "Press Ctrl+C to quit."
# Not exec'd: the shell stays to run cleanup after the server exits.
# Ctrl+C reaches the server directly (same process group), which shuts down gracefully.
"$VENV/bin/standup" serve --port "$PORT" || status=$?
status=${status:-0}
# 130 = interrupted by Ctrl+C, the normal way to quit.
[[ $status -eq 130 ]] && status=0
echo "Stopped."
exit "$status"
