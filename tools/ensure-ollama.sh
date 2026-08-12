#!/usr/bin/env bash
# ensure-ollama.sh — garantisce che Ollama sia in ascolto.
#
# Ollama non è un accessorio di questo progetto: è il cervello che struttura la ricetta
# (`extract.py`). Se è giù, la pipeline arriva fino alla trascrizione e poi fallisce — nel
# momento peggiore, dopo aver già scaricato il reel e fatto girare Whisper. Meglio
# accorgersene a inizio sessione che a metà lavoro.
#
# Idempotente e non bloccante, pensato per l'hook SessionStart: se l'API risponde già non fa
# nulla; se Ollama è installato ma fermo lo avvia in background; se non è installato avvisa e
# basta, senza bloccare la sessione (si può comunque lavorare al codice e alle tabelle).
# Il demone da fermo è leggero: carica i modelli solo alla prima richiesta.
#
# Uso:  bash tools/ensure-ollama.sh        (URL sovrascrivibile con R2R_OLLAMA_URL)
set -uo pipefail   # niente -e: un controllo soft non deve abortire al primo curl fallito

URL="${R2R_OLLAMA_URL:-http://localhost:11434}"

if curl -sf --max-time 3 "${URL}/api/tags" >/dev/null 2>&1; then
  echo "[ollama] già attivo su ${URL}"
  exit 0
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "[ollama] non installato: l'estrazione non funzionerà (brew install ollama, oppure ./install.sh). Salto."
  exit 0
fi

nohup ollama serve >/tmp/r2r-ollama.log 2>&1 &
for _ in 1 2 3 4 5 6 7 8 9 10; do   # ~5 s di attesa, senza bloccare l'avvio della sessione
  if curl -sf --max-time 2 "${URL}/api/tags" >/dev/null 2>&1; then
    echo "[ollama] avviato su ${URL} (log: /tmp/r2r-ollama.log)"
    exit 0
  fi
  sleep 0.5
done
echo "[ollama] avvio lanciato ma non ancora raggiungibile; vedi /tmp/r2r-ollama.log"
