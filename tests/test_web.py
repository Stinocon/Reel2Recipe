"""test_web.py — guard strutturali sul frontend.

Non eseguono JavaScript: la suite è pytest e il frontend non ha (né vuole) una toolchain.
Controllano invece le sole cose che si possono verificare leggendo i file, ed è esattamente
la classe di difetto che è passata inosservata: **un comando disegnato che nessuno legge**,
e **una parola che esiste in una lingua sola**.

`index.html` dichiarava `#opt-lingua` e `#opt-sistema`, l'utente li vedeva e li usava, e
`app.js` non li interrogava mai — quindi ogni lavorazione usciva in italiano metrico. Un
controllo che non fa niente è peggio di un controllo assente: il primo insegna a non
fidarsi dell'interfaccia, il secondo almeno è onesto.
"""

from __future__ import annotations

import re

import pytest

from reel2recipe import api, pipeline
from reel2recipe.percorsi import RADICE_REPO

CARTELLA_WEB = RADICE_REPO / "web"
INDEX = (CARTELLA_WEB / "index.html").read_text(encoding="utf-8")
I18N = (CARTELLA_WEB / "i18n.js").read_text(encoding="utf-8")

# Tutti i moduli della pagina, non solo `app.js`: il selettore della lingua è collegato in
# `i18n.js`, e un guard che guardasse un file solo lo dichiarerebbe morto per sbaglio.
MODULI = {p.name: p.read_text(encoding="utf-8") for p in sorted(CARTELLA_WEB.glob("*.js"))}
JS = "\n".join(MODULI.values())

ID_DEFINITI = set(re.findall(r'id="([\w-]+)"', INDEX)) | set(re.findall(r'id="([\w-]+)"', JS))
ID_USATI = set(re.findall(r"""\$\$?\('#([\w-]+)'\)""", JS))


# --------------------------------------------------------------------------------------
# Comandi disegnati e comandi letti
# --------------------------------------------------------------------------------------


def test_ogni_controllo_delle_opzioni_viene_letto():
    """Ogni `#opt-…` disegnato deve essere interrogato da qualche modulo.

    È il guard che avrebbe fatto scattare il difetto della lingua: il menu esisteva da
    subito, la lettura no.
    """
    disegnati = {i for i in set(re.findall(r'id="([\w-]+)"', INDEX)) if i.startswith("opt-")}
    assert disegnati, "nessun controllo delle opzioni trovato: il guard si è scollegato"
    non_letti = sorted(disegnati - ID_USATI)
    assert not non_letti, (
        f"controlli disegnati in index.html ma mai letti dal JavaScript: {non_letti}. "
        "Un comando che non fa niente va collegato o tolto."
    )


def test_nessun_selettore_punta_nel_vuoto():
    """Il verso opposto: un `$('#tipo-sbagliato')` non fallisce, restituisce `null` — e il
    difetto si manifesta molto più tardi, come una riga che non reagisce."""
    inesistenti = sorted(ID_USATI - ID_DEFINITI)
    assert not inesistenti, f"il JavaScript interroga id che nessuno definisce: {inesistenti}"


# --------------------------------------------------------------------------------------
# I cataloghi: nessuna lingua a metà
# --------------------------------------------------------------------------------------


def _chiavi_i18n() -> dict[str, set[str]]:
    """Le chiavi dichiarate da ciascuna lingua in `i18n.js`.

    Si legge il file invece di eseguirlo: le due lingue sono due blocchi `it: { … }` e
    `en: { … }` dentro un oggetto letterale, e le chiavi stanno a inizio riga con due
    livelli di rientro. Basta a rispondere alla domanda che conta — *c'è una chiave che
    esiste di qua e non di là?* — senza tirarsi dentro un interprete JavaScript.
    """
    catalogo = I18N.split("export const LINGUE")[0]
    per_lingua: dict[str, set[str]] = {}
    lingua_corrente = None
    for riga in catalogo.splitlines():
        if intestazione := re.match(r"^  (\w+): \{$", riga):
            lingua_corrente = intestazione.group(1)
            per_lingua[lingua_corrente] = set()
        elif lingua_corrente and (chiave := re.match(r"^    (\w+):", riga)):
            per_lingua[lingua_corrente].add(chiave.group(1))
    return per_lingua


def test_i18n_dichiara_le_lingue_attese():
    chiavi = _chiavi_i18n()
    assert set(chiavi) == {"it", "en"}, f"lingue trovate in i18n.js: {sorted(chiavi)}"
    assert len(chiavi["it"]) > 50, "il catalogo sembra vuoto: il guard non sta leggendo nulla"


def test_i18n_non_ha_lingue_a_meta():
    """Una chiave presente in una lingua sola non è un errore visibile: il ripiego
    sull'italiano la copre, e chi legge in inglese trova una frase italiana in mezzo alla
    pagina senza che niente lo segnali."""
    chiavi = _chiavi_i18n()
    assert not (chiavi["it"] - chiavi["en"]), (
        f"chiavi senza traduzione inglese: {sorted(chiavi['it'] - chiavi['en'])}"
    )
    assert not (chiavi["en"] - chiavi["it"]), (
        f"chiavi inglesi senza corrispettivo italiano: {sorted(chiavi['en'] - chiavi['it'])}"
    )


def test_ogni_chiave_del_markup_esiste_nel_catalogo():
    """Un `data-i18n` che non trova la sua chiave non solleva niente: `t()` ripiega sulla
    chiave stessa, e a schermo compare `lbl_misure` al posto di «Misure»."""
    chiavi = _chiavi_i18n()["it"]
    usate = set(re.findall(r'data-i18n(?:-\w+)?="([\w-]+)"', INDEX))
    assert usate, "nessun attributo data-i18n nel markup: il guard si è scollegato"
    assert not (usate - chiavi), f"chiavi usate nel markup e assenti dal catalogo: {sorted(usate - chiavi)}"


@pytest.mark.parametrize("modulo, catalogo", [("pipeline", pipeline.TESTI), ("api", api.TESTI)])
def test_i_cataloghi_python_sono_completi(modulo, catalogo):
    """Stessa regola per le stringhe che nascono nel server: avanzamento, avvertenze ed
    errori dell'API. Il ripiego sull'italiano c'è, ma serve a non rompere nulla — non a
    rendere accettabile una traduzione mancante."""
    assert set(catalogo) == {"it", "en"}, f"{modulo}.TESTI: lingue {sorted(catalogo)}"
    mancanti = set(catalogo["it"]) - set(catalogo["en"])
    assert not mancanti, f"{modulo}.TESTI, chiavi senza traduzione inglese: {sorted(mancanti)}"
    in_piu = set(catalogo["en"]) - set(catalogo["it"])
    assert not in_piu, f"{modulo}.TESTI, chiavi inglesi orfane: {sorted(in_piu)}"


@pytest.mark.parametrize("modulo, catalogo", [("pipeline", pipeline.TESTI), ("api", api.TESTI)])
def test_i_segnaposto_coincidono_fra_le_lingue(modulo, catalogo):
    """Un `{titolo}` che sparisce nella traduzione inglese non dà errore: dà una frase a cui
    manca il pezzo che la rendeva utile. Un segnaposto *inventato* invece esplode, e lo fa
    davanti all'utente, a metà lavorazione."""
    for chiave, testo_it in catalogo["it"].items():
        attesi = set(re.findall(r"\{(\w+)\}", testo_it))
        trovati = set(re.findall(r"\{(\w+)\}", catalogo["en"][chiave]))
        assert attesi == trovati, (
            f"{modulo}.TESTI['{chiave}']: segnaposto it={sorted(attesi)} en={sorted(trovati)}"
        )
