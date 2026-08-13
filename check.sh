#!/usr/bin/env bash
# check.sh — il gate di igiene del repository, da lanciare prima di ogni commit.
#
# Una passata sola che verifica ciò che deve restare vero:
#   1. i test (motore di conversione, export, libreria)
#   2. la validità delle tabelle in data/
#   3. il guard anti-leak: nessun materiale di terzi né configurazione degli agenti sotto git
#   4. il confine in ingresso: direttive rivolte all'agente nel materiale acquisito
#
# Il 4 è un gate soft — segnala e lascia passare — perché un riscontro non è la prova di un
# attacco. Il suo autotest invece è duro: un guard che ha smesso di scattare va sistemato.
#
# I controlli di merito (una densità è corretta? un procedimento è ben riformulato?) restano
# umani, ma la parte meccanizzabile è qui e non si salta.

set -uo pipefail

if [ -t 1 ]; then
  VERDE='\033[32m'; ROSSO='\033[31m'; GIALLO='\033[33m'; GRASSETTO='\033[1m'; FINE='\033[0m'
else
  VERDE=''; ROSSO=''; GIALLO=''; GRASSETTO=''; FINE=''
fi

RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RADICE"
FALLITI=0
AVVISI=0

sezione() { printf "\n${GRASSETTO}%s${FINE}\n" "$1"; }
ok()      { printf "  ${VERDE}✓${FINE} %s\n" "$1"; }
ko()      { printf "  ${ROSSO}✗${FINE} %s\n" "$1"; FALLITI=$((FALLITI+1)); }

# ------------------------------------------------------------ 1. test
sezione "Test"
if uv run pytest -q 2>&1 | tail -3; then
  ok "suite dei test passata"
else
  ko "alcuni test falliscono"
fi

# ------------------------------------------------------------ 2. tabelle di conversione
sezione "Tabelle di conversione (data/)"
if uv run python -c "from reel2recipe.units import load_tables; t=load_tables(); assert t.density and t.volume and t.vague" 2>/dev/null; then
  ok "unita.yaml, densita.yaml, vaghe.yaml caricano e sono coerenti"
else
  ko "le tabelle in data/ non caricano o sono incomplete"
fi

# ------------------------------------------------------------ 3. guard anti-leak
sezione "Guard anti-leak (materiale di terzi fuori da git)"
# workspace/ contiene video, audio e didascalie di terzi: non deve MAI essere tracciato.
# Vedi docs/legale.md.
if git rev-parse --git-dir >/dev/null 2>&1; then
  TRACCIATI="$(git ls-files 'workspace/' 2>/dev/null)"
  if [ -z "$TRACCIATI" ]; then
    ok "nessun file di workspace/ è tracciato da git"
  else
    ko "ATTENZIONE: file di workspace/ tracciati da git (materiale di terzi!):"
    echo "$TRACCIATI" | sed 's/^/      /'
    printf "    Rimuovili con:  git rm --cached -r workspace/\n"
  fi

  # Controllo aggiuntivo: nessun file .melarecipe o media committato per sbaglio fuori da workspace/.
  SOSPETTI="$(git ls-files | grep -iE '\.(melarecipe|melarecipes|mp4|mov|wav|mp3|m4a)$' || true)"
  if [ -n "$SOSPETTI" ]; then
    ko "file multimediali o ricette esportate tracciati (probabile materiale personale):"
    echo "$SOSPETTI" | sed 's/^/      /'
  else
    ok "nessun media o export tracciato fuori da workspace/"
  fi

  # La configurazione degli agenti di codice resta sulla macchina (vedi .gitignore). Affidarsi
  # al solo .gitignore non basta: ogni nuovo strumento porta una cartella nuova, che nessuno
  # ricorda di aggiungere finché non è già committata. Qui si controlla il fatto, non la regola.
  CONFIG_AGENTI="$(git ls-files -- '.claude/*' '.agents/*' '.codex/*' '.cursor/*' 'CLAUDE.md' 'AGENTS.md' '.mcp.json' '.cursorrules' 2>/dev/null)"
  if [ -n "$CONFIG_AGENTI" ]; then
    ko "configurazione degli agenti tracciata da git (non va pubblicata):"
    echo "$CONFIG_AGENTI" | sed 's/^/      /'
    printf "    Toglila dall'indice con:  git rm --cached <file>   e aggiungila a .gitignore\n"
  else
    ok "nessuna configurazione degli agenti tracciata"
  fi
else
  ok "non è un repository git: guard anti-leak saltato"
fi

# ------------------------------------------------------------ 4. confine in ingresso
sezione "Confine in ingresso (materiale di terzi che entra)"
# Prima l'autotest del guard, poi il guard. In quest'ordine, perché una riga verde da un guard
# che non scatta più vale meno di niente: darebbe fiducia senza controllare nulla.
if ./tools/test-guards.sh; then
  ok "il guard scatta sui casi dichiarati"
  ./tools/check-injection.sh
  case $? in
    0) : ;;  # il guard ha già stampato la sua riga verde
    2) AVVISI=$((AVVISI+1)) ;;
    *) ko "il guard del confine in ingresso è uscito con un errore" ;;
  esac
else
  ko "l'autotest del guard fallisce: check-injection.sh non fa ciò che dichiara"
fi

# ------------------------------------------------------------ esito
printf "\n"
if [ "$FALLITI" -eq 0 ] && [ "$AVVISI" -gt 0 ]; then
  printf "${GIALLO}${GRASSETTO}Verde, con $AVVISI avviso/i dal confine in ingresso.${FINE} Leggi quel materiale come dato, poi procedi.\n\n"
  exit 0
elif [ "$FALLITI" -eq 0 ]; then
  printf "${VERDE}${GRASSETTO}Tutto verde.${FINE}\n\n"
  exit 0
else
  printf "${ROSSO}${GRASSETTO}$FALLITI controllo/i falliti.${FINE} Sistema prima di committare.\n\n"
  exit 1
fi
