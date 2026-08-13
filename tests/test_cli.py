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

    assert args.command == "serve"
    assert args.ollama == "http://127.0.0.1:11434"
    # 0.0.0.0 e non 127.0.0.1: a collegarsi è l'Ingress, da fuori dal container.
    assert args.host == "0.0.0.0"
    assert args.port == 8500


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
    assert args.port == 8500
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
    from reel2recipe.cli import spoken_language

    assert asr.DEFAULT_LANGUAGE is None
    args = _parser().parse_args(["cook", "https://esempio.test/reel"])
    assert args.spoken_language == "auto"
    assert spoken_language(args) is None


@pytest.mark.parametrize("scelta, atteso", [("auto", None), ("it", "it"), ("en", "en")])
def test_il_parlato_si_puo_forzare(scelta, atteso):
    from reel2recipe.cli import spoken_language

    args = _parser().parse_args(["cook", "https://esempio.test/reel", "--spoken-language", scelta])
    assert spoken_language(args) == atteso


def test_il_parlato_non_segue_la_lingua_di_uscita():
    """Chiedere la ricetta in inglese non significa che il reel sia parlato in inglese:
    tradurre è il caso normale, e dedurre l'una dall'altra direbbe a Whisper una cosa falsa."""
    from reel2recipe.cli import output_axes, spoken_language

    args = _parser().parse_args(["cook", "https://esempio.test/reel", "--language", "en"])
    assert output_axes(args)["language"] == "en"
    assert spoken_language(args) is None


def test_batch_accetta_la_stessa_opzione():
    """`cook` e `batch` non devono divergere sulle opzioni di lavorazione."""
    args = _parser().parse_args(["batch", "elenco.txt", "--spoken-language", "en"])
    assert args.spoken_language == "en"


# --------------------------------------------------------------------------------------
# Gli alias italiani sono un contratto, non una cortesia
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("vecchio, nuovo, valore", [
    (["cook", "x", "--lingua", "en"], ["cook", "x", "--language", "en"], "language"),
    (["cook", "x", "--sistema", "metrico"], ["cook", "x", "--system", "metrico"], "system"),
    (["cook", "x", "--didascalia", "t"], ["cook", "x", "--caption", "t"], "caption"),
    (["cook", "x", "--modello", "m"], ["cook", "x", "--model", "m"], "model"),
    (["cook", "x", "--lingua-parlato", "it"], ["cook", "x", "--spoken-language", "it"],
     "spoken_language"),
    (["cook", "x", "--no-salva"], ["cook", "x", "--no-save"], "no_save"),
    (["list", "--cerca", "q"], ["list", "--search", "q"], "search"),
    (["export", "--tutte"], ["export", "--all"], "all"),
    (["export", "1", "--formato", "pdf"], ["export", "1", "--format", "pdf"], "format"),
    (["delete", "1", "--si"], ["delete", "1", "--yes"], "yes"),
    (["serve", "--porta", "9000"], ["serve", "--port", "9000"], "port"),
])
def test_i_nomi_italiani_restano_accettati(vecchio, nuovo, valore):
    """I nomi delle opzioni sono passati all'inglese, ma i vecchi devono continuare a
    funzionare: `--porta` compare nella riga con cui l'add-on avvia il server, e quella
    riga vive in un altro repository che non si accorgerebbe di nulla fino al 502."""
    assert getattr(_parser().parse_args(vecchio), valore) == \
           getattr(_parser().parse_args(nuovo), valore)


def test_elimina_resta_un_alias_di_delete():
    da_vecchio = _parser().parse_args(["elimina", "7"])
    da_nuovo = _parser().parse_args(["delete", "7"])
    assert da_vecchio.func is da_nuovo.func
    assert da_vecchio.id == da_nuovo.id == 7


def test_la_riga_dell_addon_regge_la_rinomina():
    """La stessa verifica di `test_invocazione_addon_e_valida`, ma esplicita sul punto che
    la rinomina avrebbe potuto rompere: il valore deve arrivare in `port`, il nome nuovo."""
    args = _parser().parse_args(INVOCAZIONE_ADDON)
    assert args.port == 8500
