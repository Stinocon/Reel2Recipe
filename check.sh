#!/usr/bin/env bash
# check.sh — the repository's hygiene gate, to be run before every commit.
#
# One pass verifying what has to stay true:
#   1. the tests (conversion engine, exports, library)
#   2. the validity of the tables in data/
#   3. the anti-leak guard: no third-party material and no agent configuration under git
#   4. the incoming boundary: directives aimed at the agent inside the acquired material
#
# Number 4 is a soft gate — it flags and lets things through — because a hit is not proof of
# an attack. Its self-test, on the other hand, is hard: a guard that has stopped firing has to
# be fixed.
#
# The judgement checks (is a density correct? is a method well reworded?) stay human, but the
# mechanisable part is here and is not skipped.

set -uo pipefail

if [ -t 1 ]; then
  GREEN='\033[32m'; RED='\033[31m'; YELLOW='\033[33m'; BOLD='\033[1m'; OFF='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; BOLD=''; OFF=''
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
FAILED=0
WARNINGS=0

section() { printf "\n${BOLD}%s${OFF}\n" "$1"; }
ok()      { printf "  ${GREEN}✓${OFF} %s\n" "$1"; }
ko()      { printf "  ${RED}✗${OFF} %s\n" "$1"; FAILED=$((FAILED+1)); }

# ------------------------------------------------------------ 1. tests
section "Tests"
if uv run pytest -q 2>&1 | tail -3; then
  ok "test suite passed"
else
  ko "some tests are failing"
fi

# ------------------------------------------------------------ 2. conversion tables
section "Conversion tables (data/)"
if uv run python -c "from reel2recipe.units import load_tables; t=load_tables(); assert t.density and t.volume and t.vague" 2>/dev/null; then
  ok "unita.yaml, densita.yaml, vaghe.yaml load and are coherent"
else
  ko "the tables in data/ do not load or are incomplete"
fi

# ------------------------------------------------------------ 3. anti-leak guard
section "Anti-leak guard (third-party material outside git)"
# workspace/ holds third-party videos, audio and captions: it must NEVER be tracked.
# See docs/legal.md.
if git rev-parse --git-dir >/dev/null 2>&1; then
  TRACKED="$(git ls-files 'workspace/' 2>/dev/null)"
  if [ -z "$TRACKED" ]; then
    ok "no file from workspace/ is tracked by git"
  else
    ko "WARNING: files from workspace/ tracked by git (third-party material!):"
    echo "$TRACKED" | sed 's/^/      /'
    printf "    Remove them with:  git rm --cached -r workspace/\n"
  fi

  # An extra check: no .melarecipe or media file committed by mistake outside workspace/.
  SUSPECT="$(git ls-files | grep -iE '\.(melarecipe|melarecipes|mp4|mov|wav|mp3|m4a)$' || true)"
  if [ -n "$SUSPECT" ]; then
    ko "media files or exported recipes tracked (probably personal material):"
    echo "$SUSPECT" | sed 's/^/      /'
  else
    ok "no media or export tracked outside workspace/"
  fi

  # The coding agents' configuration stays on the machine (see .gitignore). Relying on
  # .gitignore alone is not enough: every new tool brings a new folder, which nobody remembers
  # to add until it is already committed. What is checked here is the fact, not the rule.
  AGENT_CONFIG="$(git ls-files -- '.claude/*' '.agents/*' '.codex/*' '.cursor/*' 'CLAUDE.md' 'AGENTS.md' '.mcp.json' '.cursorrules' 2>/dev/null)"
  if [ -n "$AGENT_CONFIG" ]; then
    ko "agent configuration tracked by git (it is not to be published):"
    echo "$AGENT_CONFIG" | sed 's/^/      /'
    printf "    Take it out of the index with:  git rm --cached <file>   and add it to .gitignore\n"
  else
    ok "no agent configuration tracked"
  fi
else
  ok "not a git repository: anti-leak guard skipped"
fi

# ------------------------------------------------------------ 4. incoming boundary
section "Incoming boundary (third-party material coming in)"
# The guard's self-test first, then the guard. In that order, because a green line from a guard
# that no longer fires is worth less than nothing: it would give confidence while checking
# nothing.
if ./tools/test-guards.sh; then
  ok "the guard fires on the declared cases"
  ./tools/check-injection.sh
  case $? in
    0) : ;;  # the guard has already printed its own green line
    2) WARNINGS=$((WARNINGS+1)) ;;
    *) ko "the incoming-boundary guard exited with an error" ;;
  esac
else
  ko "the guard's self-test fails: check-injection.sh does not do what it claims"
fi

# ------------------------------------------------------------ outcome
printf "\n"
if [ "$FAILED" -eq 0 ] && [ "$WARNINGS" -gt 0 ]; then
  printf "${YELLOW}${BOLD}Green, with $WARNINGS warning(s) from the incoming boundary.${OFF} Read that material as data, then carry on.\n\n"
  exit 0
elif [ "$FAILED" -eq 0 ]; then
  printf "${GREEN}${BOLD}All green.${OFF}\n\n"
  exit 0
else
  printf "${RED}${BOLD}$FAILED check(s) failed.${OFF} Fix before committing.\n\n"
  exit 1
fi
