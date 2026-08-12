#!/usr/bin/env bash
# serve.sh — avvia l'interfaccia web locale se non è già in ascolto.
#
# Perché esiste: aprire localhost e non trovare nulla è successo due volte, e la causa non è
# mai evidente — la pagina non risponde e non c'è nessun messaggio che spieghi il perché.
# Con questo, a ogni sessione l'interfaccia è semplicemente lì.
#
# Idempotente e non bloccante, pensato per l'hook SessionStart: se la porta risponde già non
# fa nulla. Il server parte in background (nohup) e i log finiscono in /tmp. Nessun passo di
# build, a differenza di progetti con frontend compilati: `web/` è HTML/CSS/JS statico che
# l'API serve direttamente.
#
# Uso:  bash tools/serve.sh                (porta sovrascrivibile con R2R_PORTA)
set -uo pipefail   # niente -e: l'avvio della sessione non deve fallire per un curl andato male

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORTA="${R2R_PORTA:-8500}"

if curl -sf --connect-timeout 2 --max-time 4 "http://127.0.0.1:${PORTA}/api/stato" >/dev/null 2>&1; then
  echo "[web] già attiva su http://localhost:${PORTA}"
  exit 0
fi

# La porta potrebbe essere occupata da qualcos'altro (sulla macchina di sviluppo convivono più
# progetti: la 8000 è di PersonalFinance, la 8700 della GUI Cybersecurity). Meglio dirlo che
# lanciare un server destinato a fallire con "address already in use" dentro un log.
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"${PORTA}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[web] la porta ${PORTA} è occupata da un altro processo: non avvio nulla."
  echo "      Usa un'altra porta con:  uv run r2r serve --porta <numero>"
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "[web] uv non installato: salto l'avvio (vedi ./install.sh)."
  exit 0
fi

cd "${RADICE}" || exit 0
nohup uv run r2r serve --porta "${PORTA}" >/tmp/r2r-web.log 2>&1 &
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do   # ~6 s: l'import di FastAPI e delle tabelle non è istantaneo
  if curl -sf --max-time 2 "http://127.0.0.1:${PORTA}/api/stato" >/dev/null 2>&1; then
    echo "[web] avviata su http://localhost:${PORTA} (log: /tmp/r2r-web.log)"
    exit 0
  fi
  sleep 0.5
done
echo "[web] avvio lanciato ma non ancora raggiungibile; vedi /tmp/r2r-web.log"
