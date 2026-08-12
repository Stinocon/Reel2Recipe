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


# --------------------------------------------------------------------------------------
# La lingua del parlato: un asse dell'ingresso, non dell'uscita
# --------------------------------------------------------------------------------------


def test_il_parlato_si_riconosce_da_se_per_impostazione_predefinita():
    """Il valore che arriva a Whisper deve essere `None`, non "it".

    Qui c'era un "it" cablato in `asr.py` che nessuna opzione poteva togliere: ogni reel
    veniva dato a Whisper dichiarando che era italiano, anche quando era inglese. La
    trascrizione ne usciva storpiata e tutto il resto della catena lavorava su quella.
    """
    from reel2recipe import asr
    from reel2recipe.cli import lingua_del_parlato

    assert asr.LINGUA_PREDEFINITA is None
    args = _parser().parse_args(["cook", "https://esempio.test/reel"])
    assert args.lingua_parlato == "auto"
    assert lingua_del_parlato(args) is None


@pytest.mark.parametrize("scelta, atteso", [("auto", None), ("it", "it"), ("en", "en")])
def test_il_parlato_si_puo_forzare(scelta, atteso):
    from reel2recipe.cli import lingua_del_parlato

    args = _parser().parse_args(["cook", "https://esempio.test/reel", "--lingua-parlato", scelta])
    assert lingua_del_parlato(args) == atteso


def test_il_parlato_non_segue_la_lingua_di_uscita():
    """Chiedere la ricetta in inglese non significa che il reel sia parlato in inglese:
    tradurre è il caso normale, e dedurre l'una dall'altra direbbe a Whisper una cosa falsa."""
    from reel2recipe.cli import assi_di_uscita, lingua_del_parlato

    args = _parser().parse_args(["cook", "https://esempio.test/reel", "--lingua", "en"])
    assert assi_di_uscita(args)["lingua"] == "en"
    assert lingua_del_parlato(args) is None


def test_batch_accetta_la_stessa_opzione():
    """`cook` e `batch` non devono divergere sulle opzioni di lavorazione."""
    args = _parser().parse_args(["batch", "elenco.txt", "--lingua-parlato", "en"])
    assert args.lingua_parlato == "en"
