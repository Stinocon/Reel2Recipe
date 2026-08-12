#!/usr/bin/env bash
# install.sh — prepara Reel2Recipe su questa macchina.
#
# Controlla ogni componente necessario e, dove può, lo installa. Dove non può (perché
# richiederebbe privilegi o scelte che spettano a te), spiega esattamente cosa fare.
# È idempotente: rieseguirlo non rompe nulla e completa ciò che mancava.
#
# Cosa serve a Reel2Recipe, e perché:
#   uv              gestore Python del progetto (obbligatorio)
#   ffmpeg          estrae l'audio dai video          (per la trascrizione del parlato)
#   ollama + modello  LLM locale che struttura la ricetta (obbligatorio: è il cervello)
#   whisper locale  trascrizione del parlato           (opzionale: senza, usi le didascalie)
#
# Tutto gira in locale. Nessuna chiave API, nessun servizio a pagamento.

set -uo pipefail

# ------------------------------------------------------------------ estetica
if [ -t 1 ]; then
  VERDE='\033[32m'; GIALLO='\033[33m'; ROSSO='\033[31m'; GRASSETTO='\033[1m'; SPENTO='\033[2m'; FINE='\033[0m'
else
  VERDE=''; GIALLO=''; ROSSO=''; GRASSETTO=''; SPENTO=''; FINE=''
fi
ok()      { printf "  ${VERDE}✓${FINE} %s\n" "$1"; }
manca()   { printf "  ${GIALLO}•${FINE} %s\n" "$1"; }
errore()  { printf "  ${ROSSO}✗${FINE} %s\n" "$1"; }
titolo()  { printf "\n${GRASSETTO}%s${FINE}\n" "$1"; }
nota()    { printf "    ${SPENTO}%s${FINE}\n" "$1"; }

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RADICE"

MODELLO_LLM_PREDEFINITO="qwen2.5:7b-instruct"
PROBLEMI=0

esiste() { command -v "$1" >/dev/null 2>&1; }

# Rileva il gestore di pacchetti di sistema, per i suggerimenti giusti.
if [ "$(uname)" = "Darwin" ]; then
  SISTEMA="macos"
elif esiste apt-get; then
  SISTEMA="debian"
elif esiste dnf; then
  SISTEMA="fedora"
else
  SISTEMA="altro"
fi

printf "${GRASSETTO}🥘 Reel2Recipe — installazione${FINE}\n"
nota "Sistema rilevato: $SISTEMA"

# ============================================================ 1. uv (obbligatorio)
titolo "1. uv (gestore del progetto Python)"
if esiste uv; then
  ok "uv presente ($(uv --version 2>/dev/null))"
else
  manca "uv non trovato: lo installo…"
  if curl -LsSf https://astral.sh/uv/install.sh | sh; then
    # uv si installa in ~/.local/bin o ~/.cargo/bin: rendilo disponibile in questa shell.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    esiste uv && ok "uv installato" || { errore "uv installato ma non nel PATH: riapri il terminale e rilancia."; PROBLEMI=$((PROBLEMI+1)); }
  else
    errore "Installazione di uv fallita. Istruzioni: https://docs.astral.sh/uv/"
    PROBLEMI=$((PROBLEMI+1))
  fi
fi

# ============================================================ 2. dipendenze Python
titolo "2. Dipendenze Python"
if esiste uv; then
  # `--extra asr` include Whisper (faster-whisper); su Mac Apple Silicon aggiunge anche
  # l'accelerazione Metal. `--extra api` include l'interfaccia web, `--extra doc` l'export
  # in PDF (il Markdown non richiede nulla).
  EXTRA="--extra asr --extra api --extra doc"
  if [ "$(uname)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
    EXTRA="$EXTRA --extra asr-mlx"
    nota "Mac Apple Silicon: includo l'accelerazione Metal per la trascrizione."
  fi
  printf "    installazione in corso (può richiedere qualche minuto)…\n"
  if uv sync $EXTRA >/dev/null 2>&1; then
    ok "dipendenze installate (Whisper + interfaccia web + export PDF)"
  else
    errore "uv sync ha fallito. Riprova a mano:  uv sync $EXTRA"
    PROBLEMI=$((PROBLEMI+1))
  fi
else
  errore "Salto le dipendenze Python: manca uv."
  PROBLEMI=$((PROBLEMI+1))
fi

# ============================================================ 3. ffmpeg
titolo "3. ffmpeg (estrazione audio dai video)"
if esiste ffmpeg; then
  ok "ffmpeg presente"
else
  case "$SISTEMA" in
    macos)
      if esiste brew; then
        manca "ffmpeg non trovato: lo installo con Homebrew…"
        brew install ffmpeg >/dev/null 2>&1 && ok "ffmpeg installato" \
          || { errore "brew install ffmpeg fallito. Riprova a mano."; PROBLEMI=$((PROBLEMI+1)); }
      else
        errore "ffmpeg manca e Homebrew non è installato."
        nota "Installa Homebrew (https://brew.sh) e poi:  brew install ffmpeg"
        PROBLEMI=$((PROBLEMI+1))
      fi ;;
    debian)
      manca "ffmpeg non trovato. Installalo con:"
      nota "sudo apt update && sudo apt install -y ffmpeg"
      PROBLEMI=$((PROBLEMI+1)) ;;
    fedora)
      manca "ffmpeg non trovato. Installalo con:"
      nota "sudo dnf install -y ffmpeg"
      PROBLEMI=$((PROBLEMI+1)) ;;
    *)
      errore "ffmpeg manca: installalo dal gestore pacchetti del tuo sistema."
      PROBLEMI=$((PROBLEMI+1)) ;;
  esac
  nota "Senza ffmpeg puoi comunque usare le didascalie, ma non il parlato dei reel."
fi

# ============================================================ 4. Ollama (obbligatorio)
titolo "4. Ollama (il modello di linguaggio locale)"
if esiste ollama; then
  ok "Ollama presente"
else
  case "$SISTEMA" in
    macos)
      if esiste brew; then
        manca "Ollama non trovato: lo installo con Homebrew…"
        brew install ollama >/dev/null 2>&1 && ok "Ollama installato" \
          || { errore "brew install ollama fallito. Scaricalo da https://ollama.com"; PROBLEMI=$((PROBLEMI+1)); }
      else
        errore "Ollama manca. Scaricalo da https://ollama.com"
        PROBLEMI=$((PROBLEMI+1))
      fi ;;
    debian|fedora)
      manca "Ollama non trovato: lo installo con lo script ufficiale…"
      if curl -fsSL https://ollama.com/install.sh | sh; then
        ok "Ollama installato"
      else
        errore "Installazione di Ollama fallita. Istruzioni: https://ollama.com"
        PROBLEMI=$((PROBLEMI+1))
      fi ;;
    *)
      errore "Ollama manca. Scaricalo da https://ollama.com"
      PROBLEMI=$((PROBLEMI+1)) ;;
  esac
fi

# Avvia il demone se serve, e scarica un modello se non ce n'è nessuno.
if esiste ollama; then
  if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    nota "Avvio del server Ollama…"
    nohup ollama serve >/tmp/r2r-ollama.log 2>&1 &
    for _ in $(seq 1 15); do
      curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
      sleep 0.5
    done
  fi

  if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    ok "server Ollama attivo"
    MODELLI="$(curl -sf http://localhost:11434/api/tags 2>/dev/null | grep -o '"name":"[^"]*"' | wc -l | tr -d ' ')"
    if [ "${MODELLI:-0}" -gt 0 ]; then
      ok "modelli già presenti ($MODELLI)"
    else
      manca "nessun modello installato: scarico $MODELLO_LLM_PREDEFINITO (~4,7 GB)…"
      nota "Serve solo la prima volta. Puoi interrompere e scaricarlo dopo con: ollama pull $MODELLO_LLM_PREDEFINITO"
      if ollama pull "$MODELLO_LLM_PREDEFINITO"; then
        ok "modello $MODELLO_LLM_PREDEFINITO pronto"
      else
        errore "Download del modello non completato. Riprova con: ollama pull $MODELLO_LLM_PREDEFINITO"
        PROBLEMI=$((PROBLEMI+1))
      fi
    fi
  else
    errore "Il server Ollama non risponde. Avvialo a mano con: ollama serve"
    PROBLEMI=$((PROBLEMI+1))
  fi
fi

# ============================================================ verifica finale
titolo "Verifica finale"
if esiste uv; then
  uv run r2r check 2>/dev/null || true
fi

printf "\n"
if [ "$PROBLEMI" -eq 0 ]; then
  printf "${VERDE}${GRASSETTO}Tutto pronto.${FINE}\n\n"
  printf "  Avvia l'interfaccia web:   ${GRASSETTO}uv run r2r serve${FINE}\n"
  printf "  poi apri:                  ${GRASSETTO}http://localhost:8500${FINE}\n\n"
  printf "  Oppure da terminale:       ${GRASSETTO}uv run r2r cook <link-del-reel>${FINE}\n"
else
  printf "${GIALLO}${GRASSETTO}Installazione quasi completa: $PROBLEMI punto/i da sistemare a mano${FINE} (vedi sopra).\n"
  printf "  Rilancia ${GRASSETTO}./install.sh${FINE} dopo aver risolto, oppure ${GRASSETTO}uv run r2r check${FINE} per ricontrollare.\n"
fi
printf "\n"
exit "$PROBLEMI"
