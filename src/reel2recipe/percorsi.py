"""percorsi.py — dove vivono i dati.

Un solo posto decide la radice di `workspace/`. Prima la decisione era ripetuta identica in
tre moduli (`store`, `pipeline`, `api`), ognuno col suo `parents[2]`: tre copie dello stesso
fatto, che è esattamente il modo in cui due di loro finiscono per divergere.

Serve anche perché la radice non è sempre "accanto al repo". Dentro un container — l'addon
Home Assistant — il codice sta in sola lettura e i dati devono finire sul volume persistente,
altrimenti la libreria sparisce al primo aggiornamento. `R2R_WORKSPACE` sposta la radice
senza toccare una riga di codice.

Il confine di `AGENTS.md §7` non cambia: qualunque sia la radice, lì dentro c'è materiale di
terzi e non va committato né ridistribuito.
"""

from __future__ import annotations

import os
from pathlib import Path

RADICE_REPO = Path(__file__).resolve().parents[2]


def cartella_workspace() -> Path:
    """La radice dei dati locali: `R2R_WORKSPACE` se impostata, altrimenti `workspace/`.

    Letta a ogni chiamata e non all'import: un modulo importato prima che l'ambiente sia
    pronto non deve congelare la scelta sbagliata.
    """
    if radice := os.environ.get("R2R_WORKSPACE", "").strip():
        return Path(radice).expanduser()
    return RADICE_REPO / "workspace"


def cartella_media() -> Path:
    """Dove atterrano video, audio e miniature scaricati."""
    return cartella_workspace() / "media"


def cartella_export() -> Path:
    """Dove finiscono i file esportati prima di essere scaricati dal browser."""
    return cartella_workspace() / "export"


def percorso_database() -> Path:
    """Il file della libreria."""
    return cartella_workspace() / "ricette.db"
