"""Test della riga di comando, e in particolare del contratto con l'add-on.

L'add-on Home Assistant vive in un altro repository (`Stinocon/addons`) e avvia questo
programma con una riga fissa, scritta nel suo script di servizio. È un contratto fra due
repo che nessuno dei due controlla: se qui cambia la forma delle opzioni, là non se ne
accorge nessuno finché l'add-on non muore all'avvio davanti a un utente.

È già successo. `--ollama` è un'opzione globale, quindi va **prima** del sottocomando; lo
script la metteva dopo, argparse usciva con codice 2, s6 riavviava il servizio all'infinito
e Home Assistant — che sull'Ingress non trovava nessuno in ascolto — rispondeva «502 Bad
Gateway». Dal log dell'add-on:

    r2r: error: unrecognized arguments: --ollama http://127.0.0.1:11434
    WARNING: L'interfaccia si è fermata (codice 2). Fermo l'addon.

Questi test tengono ferma quella riga.
"""

from __future__ import annotations

import pytest

from reel2recipe.cli import _parser

# La riga esatta di `rootfs/etc/services.d/reel2recipe/run` nel repo dell'add-on.
# Se cambia là, cambia qui: sono le due metà dello stesso contratto.
INVOCAZIONE_ADDON = [
    "--ollama", "http://127.0.0.1:11434",
    "serve",
    "--host", "0.0.0.0",
    "--porta", "8500",
]


def test_invocazione_addon_e_valida():
    """La riga con cui l'add-on avvia l'interfaccia deve continuare a essere accettata."""
    args = _parser().parse_args(INVOCAZIONE_ADDON)

    assert args.comando == "serve"
    assert args.ollama == "http://127.0.0.1:11434"
    # 0.0.0.0 e non 127.0.0.1: a collegarsi è l'Ingress, da fuori dal container.
    assert args.host == "0.0.0.0"
    assert args.porta == 8500


def test_opzione_globale_dopo_il_sottocomando_e_rifiutata():
    """La forma sbagliata resta sbagliata, e questo test dice perché il contratto è fragile.

    Non è un difetto di argparse da aggirare: è il motivo per cui l'ordine delle opzioni
    nello script di servizio non è un dettaglio di stile.
    """
    with pytest.raises(SystemExit) as uscita:
        _parser().parse_args(["serve", "--ollama", "http://127.0.0.1:11434"])

    # Codice 2 è quello che argparse usa per un errore d'uso, ed è quello che compariva
    # nel log dell'add-on.
    assert uscita.value.code == 2


def test_serve_ha_i_valori_di_ripiego_dello_sviluppo():
    """Senza opzioni, `r2r serve` resta legato alla macchina locale."""
    args = _parser().parse_args(["serve"])

    assert args.host == "127.0.0.1"
    assert args.porta == 8500
    assert args.ollama == "http://localhost:11434"
