#!/usr/bin/env bash
# serve.sh — starts the local web interface if it is not already listening.
#
# Why it exists: opening localhost and finding nothing has happened twice, and the cause is
# never obvious — the page does not answer and there is no message explaining why. With this,
# the interface is simply there at every session.
#
# Idempotent and non-blocking, meant for the SessionStart hook: if the port already answers it
# does nothing. The server starts in the background (nohup) and the logs land in /tmp. No build
# step, unlike projects with compiled frontends: `web/` is static HTML/CSS/JS that the API
# serves directly.
#
# Usage:  bash tools/serve.sh                (port overridable with R2R_PORT)
set -uo pipefail   # no -e: the session start must not fail over a curl gone wrong

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# R2R_PORTA is still accepted: it is the name it had before the rename to English, and it may
# already be exported in an open shell or in a local environment file.
PORT="${R2R_PORT:-${R2R_PORTA:-8500}}"

if curl -sf --connect-timeout 2 --max-time 4 "http://127.0.0.1:${PORT}/api/status" >/dev/null 2>&1; then
  echo "[web] already up on http://localhost:${PORT}"
  exit 0
fi

# The port may be taken by something else (several projects live on the development machine:
# 8000 is PersonalFinance's, 8700 the Cybersecurity GUI's). Better to say so than to launch a
# server destined to fail with "address already in use" inside a log.
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[web] port ${PORT} is taken by another process: starting nothing."
  echo "      Use another port with:  uv run r2r serve --port <number>"
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "[web] uv not installed: skipping the start (see ./install.sh)."
  exit 0
fi

cd "${ROOT}" || exit 0
nohup uv run r2r serve --port "${PORT}" >/tmp/r2r-web.log 2>&1 &
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do   # ~6 s: importing FastAPI and the tables is not instant
  if curl -sf --max-time 2 "http://127.0.0.1:${PORT}/api/status" >/dev/null 2>&1; then
    echo "[web] started on http://localhost:${PORT} (log: /tmp/r2r-web.log)"
    exit 0
  fi
  sleep 0.5
done
echo "[web] start launched but not reachable yet; see /tmp/r2r-web.log"
