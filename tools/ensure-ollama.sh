#!/usr/bin/env bash
# ensure-ollama.sh — makes sure Ollama is listening.
#
# Ollama is not an accessory of this project: it is the brain that structures the recipe
# (`extract.py`). If it is down, the pipeline gets as far as the transcription and then fails —
# at the worst possible moment, after having already downloaded the reel and run Whisper.
# Better to find out at the start of a session than halfway through the work.
#
# Idempotent and non-blocking, meant for the SessionStart hook: if the API already answers it
# does nothing; if Ollama is installed but stopped it starts it in the background; if it is not
# installed it just says so, without blocking the session (you can still work on the code and
# the tables). The idle daemon is light: it loads the models only on the first request.
#
# Usage:  bash tools/ensure-ollama.sh        (URL overridable with R2R_OLLAMA_URL)
set -uo pipefail   # no -e: a soft check must not abort on the first failed curl

URL="${R2R_OLLAMA_URL:-http://localhost:11434}"

if curl -sf --max-time 3 "${URL}/api/tags" >/dev/null 2>&1; then
  echo "[ollama] already up on ${URL}"
  exit 0
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "[ollama] not installed: extraction will not work (brew install ollama, or ./install.sh). Skipping."
  exit 0
fi

nohup ollama serve >/tmp/r2r-ollama.log 2>&1 &
for _ in 1 2 3 4 5 6 7 8 9 10; do   # ~5 s of waiting, without blocking the session start
  if curl -sf --max-time 2 "${URL}/api/tags" >/dev/null 2>&1; then
    echo "[ollama] started on ${URL} (log: /tmp/r2r-ollama.log)"
    exit 0
  fi
  sleep 0.5
done
echo "[ollama] start launched but not reachable yet; see /tmp/r2r-ollama.log"
