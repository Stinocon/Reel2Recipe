#!/usr/bin/env bash
# install.sh — prepares Reel2Recipe on this machine.
#
# It checks every component needed and, where it can, installs it. Where it cannot (because
# that would take privileges or choices that are yours to make), it says exactly what to do.
# It is idempotent: running it again breaks nothing and completes whatever was missing.
#
# What Reel2Recipe needs, and why:
#   uv               the project's Python manager        (mandatory)
#   ffmpeg           extracts the audio from the videos  (for transcribing the speech)
#   ollama + a model the local LLM that structures the recipe (mandatory: it is the brain)
#   local whisper    speech transcription                (optional: without it, captions only)
#
# Everything runs locally. No API key, no paid service.

set -uo pipefail

# ------------------------------------------------------------------ appearance
if [ -t 1 ]; then
  GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; BOLD='\033[1m'; DIM='\033[2m'; OFF='\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; BOLD=''; DIM=''; OFF=''
fi
ok()      { printf "  ${GREEN}✓${OFF} %s\n" "$1"; }
missing() { printf "  ${YELLOW}•${OFF} %s\n" "$1"; }
fail()    { printf "  ${RED}✗${OFF} %s\n" "$1"; }
heading() { printf "\n${BOLD}%s${OFF}\n" "$1"; }
note()    { printf "    ${DIM}%s${OFF}\n" "$1"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DEFAULT_LLM_MODEL="qwen2.5:7b-instruct"
PROBLEMS=0

exists() { command -v "$1" >/dev/null 2>&1; }

# Detects the system package manager, so the suggestions are the right ones.
if [ "$(uname)" = "Darwin" ]; then
  SYSTEM="macos"
elif exists apt-get; then
  SYSTEM="debian"
elif exists dnf; then
  SYSTEM="fedora"
else
  SYSTEM="other"
fi

printf "${BOLD}🥘 Reel2Recipe — installation${OFF}\n"
note "System detected: $SYSTEM"

# ============================================================ 1. uv (obbligatorio)
heading "1. uv (the Python project manager)"
if exists uv; then
  ok "uv present ($(uv --version 2>/dev/null))"
else
  missing "uv not found: installing it…"
  if curl -LsSf https://astral.sh/uv/install.sh | sh; then
    # uv installs into ~/.local/bin or ~/.cargo/bin: make it available in this shell.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    exists uv && ok "uv installed" || { fail "uv installed but not on the PATH: reopen the terminal and run again."; PROBLEMS=$((PROBLEMS+1)); }
  else
    fail "uv installation failed. Instructions: https://docs.astral.sh/uv/"
    PROBLEMS=$((PROBLEMS+1))
  fi
fi

# ============================================================ 2. dipendenze Python
heading "2. Python dependencies"
if exists uv; then
  # `--extra asr` includes Whisper (faster-whisper); on Apple Silicon Macs it also adds Metal
  # acceleration. `--extra api` includes the web interface, `--extra doc` the PDF export
  # (Markdown needs nothing).
  EXTRA="--extra asr --extra api --extra doc"
  if [ "$(uname)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
    EXTRA="$EXTRA --extra asr-mlx"
    note "Apple Silicon Mac: including Metal acceleration for the transcription."
  fi
  printf "    installing (this may take a few minutes)…\n"
  if uv sync $EXTRA >/dev/null 2>&1; then
    ok "dependencies installed (Whisper + web interface + PDF export)"
  else
    fail "uv sync failed. Try by hand:  uv sync $EXTRA"
    PROBLEMS=$((PROBLEMS+1))
  fi
else
  fail "Skipping the Python dependencies: uv is missing."
  PROBLEMS=$((PROBLEMS+1))
fi

# ============================================================ 3. ffmpeg
heading "3. ffmpeg (extracting audio from the videos)"
if exists ffmpeg; then
  ok "ffmpeg present"
else
  case "$SYSTEM" in
    macos)
      if exists brew; then
        missing "ffmpeg not found: installing it with Homebrew…"
        brew install ffmpeg >/dev/null 2>&1 && ok "ffmpeg installed" \
          || { fail "brew install ffmpeg failed. Try by hand."; PROBLEMS=$((PROBLEMS+1)); }
      else
        fail "ffmpeg is missing and Homebrew is not installed."
        note "Install Homebrew (https://brew.sh) and then:  brew install ffmpeg"
        PROBLEMS=$((PROBLEMS+1))
      fi ;;
    debian)
      missing "ffmpeg not found. Install it with:"
      note "sudo apt update && sudo apt install -y ffmpeg"
      PROBLEMS=$((PROBLEMS+1)) ;;
    fedora)
      missing "ffmpeg not found. Install it with:"
      note "sudo dnf install -y ffmpeg"
      PROBLEMS=$((PROBLEMS+1)) ;;
    *)
      fail "ffmpeg is missing: install it from your system's package manager."
      PROBLEMS=$((PROBLEMS+1)) ;;
  esac
  note "Without ffmpeg you can still use the captions, but not the reels' speech."
fi

# ============================================================ 4. Ollama (obbligatorio)
heading "4. Ollama (the local language model)"
if exists ollama; then
  ok "Ollama present"
else
  case "$SYSTEM" in
    macos)
      if exists brew; then
        missing "Ollama not found: installing it with Homebrew…"
        brew install ollama >/dev/null 2>&1 && ok "Ollama installed" \
          || { fail "brew install ollama failed. Download it from https://ollama.com"; PROBLEMS=$((PROBLEMS+1)); }
      else
        fail "Ollama is missing. Download it from https://ollama.com"
        PROBLEMS=$((PROBLEMS+1))
      fi ;;
    debian|fedora)
      missing "Ollama not found: installing it with the official script…"
      if curl -fsSL https://ollama.com/install.sh | sh; then
        ok "Ollama installed"
      else
        fail "Ollama installation failed. Instructions: https://ollama.com"
        PROBLEMS=$((PROBLEMS+1))
      fi ;;
    *)
      fail "Ollama is missing. Download it from https://ollama.com"
      PROBLEMS=$((PROBLEMS+1)) ;;
  esac
fi

# Starts the daemon if needed, and downloads a model if there is none.
if exists ollama; then
  if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    note "Starting the Ollama server…"
    nohup ollama serve >/tmp/r2r-ollama.log 2>&1 &
    for _ in $(seq 1 15); do
      curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
      sleep 0.5
    done
  fi

  if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    ok "Ollama server up"
    MODELS="$(curl -sf http://localhost:11434/api/tags 2>/dev/null | grep -o '"name":"[^"]*"' | wc -l | tr -d ' ')"
    if [ "${MODELS:-0}" -gt 0 ]; then
      ok "models already present ($MODELS)"
    else
      missing "no model installed: downloading $DEFAULT_LLM_MODEL (~4.7 GB)…"
      note "Needed only the first time. You can interrupt and pull it later with: ollama pull $DEFAULT_LLM_MODEL"
      if ollama pull "$DEFAULT_LLM_MODEL"; then
        ok "model $DEFAULT_LLM_MODEL ready"
      else
        fail "The model download did not complete. Try again with: ollama pull $DEFAULT_LLM_MODEL"
        PROBLEMS=$((PROBLEMS+1))
      fi
    fi
  else
    fail "The Ollama server is not answering. Start it by hand with: ollama serve"
    PROBLEMS=$((PROBLEMS+1))
  fi
fi

# ============================================================ final check
heading "Final check"
if exists uv; then
  uv run r2r check 2>/dev/null || true
fi

printf "\n"
if [ "$PROBLEMS" -eq 0 ]; then
  printf "${GREEN}${BOLD}All ready.${OFF}\n\n"
  printf "  Start the web interface:   ${BOLD}uv run r2r serve${OFF}\n"
  printf "  then open:                 ${BOLD}http://localhost:8500${OFF}\n\n"
  printf "  Or from the terminal:      ${BOLD}uv run r2r cook <reel-link>${OFF}\n"
else
  printf "${YELLOW}${BOLD}Installation almost complete: $PROBLEMS point(s) to fix by hand${OFF} (see above).\n"
  printf "  Run ${BOLD}./install.sh${OFF} again once solved, or ${BOLD}uv run r2r check${OFF} to re-check.\n"
fi
printf "\n"
exit "$PROBLEMS"
