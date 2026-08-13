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

import ast
from pathlib import Path

from reel2recipe import api, documents, mela, pipeline, units
from reel2recipe.paths import REPO_ROOT

CARTELLA_WEB = REPO_ROOT / "web"
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


@pytest.mark.parametrize("modulo, catalogo", [("pipeline", pipeline.TEXTS), ("api", api.TEXTS)])
def test_i_cataloghi_python_sono_completi(modulo, catalogo):
    """Stessa regola per le stringhe che nascono nel server: avanzamento, avvertenze ed
    errori dell'API. Il ripiego sull'italiano c'è, ma serve a non rompere nulla — non a
    rendere accettabile una traduzione mancante."""
    assert set(catalogo) == {"it", "en"}, f"{modulo}.TESTI: lingue {sorted(catalogo)}"
    mancanti = set(catalogo["it"]) - set(catalogo["en"])
    assert not mancanti, f"{modulo}.TESTI, chiavi senza traduzione inglese: {sorted(mancanti)}"
    in_piu = set(catalogo["en"]) - set(catalogo["it"])
    assert not in_piu, f"{modulo}.TESTI, chiavi inglesi orfane: {sorted(in_piu)}"


@pytest.mark.parametrize("modulo, catalogo", [("pipeline", pipeline.TEXTS), ("api", api.TEXTS)])
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


# --------------------------------------------------------------------------------------
# Il contratto fra il JSON del server e le chiavi che la pagina legge
# --------------------------------------------------------------------------------------


def _ricetta_di_prova():
    """Una ricetta vera, costruita dalla pipeline invece che scritta a mano: le chiavi
    devono essere quelle che il server produce davvero, non quelle che ricordiamo."""
    from reel2recipe.recipe import Source, from_draft

    return from_draft(
        {"titolo": "Torta di mele", "porzioni": "6 persone",
         "ingredienti": [{"nome": "farina 00", "quantita_raw": "1", "unita_raw": "cup",
                          "gruppo": "Per l'impasto"}],
         "procedimento": ["Inforna a 180 °C."], "categorie": ["Dolci"],
         "tempo_preparazione_min": 20, "tempo_cottura_min": 45, "lacune": []},
        source=Source.now(url="https://x/y", author="nonna", platform="instagram"),
        images=["Zm90bw=="],
    )


def test_ogni_chiave_letta_dalla_pagina_esiste_nel_json_del_server():
    """Il guard che avrebbe intercettato in un colpo solo la rinomina dei campi di `Recipe`.

    `app.js` legge il JSON per attributo: `ricetta.titolo` su un oggetto che non ha più quel
    campo non solleva niente, restituisce `undefined`, e la scheda si disegna lo stesso — con
    il titolo vuoto. È la stessa famiglia di difetto muto dei guard qui sopra, e su un
    frontend senza toolchain non c'è nient'altro che possa accorgersene.

    Il confronto è deliberatamente **strutturale e non esaustivo**: si guardano solo gli
    accessi `ricetta.X`, che sono quelli sul primo livello del JSON. Gli accessi annidati
    (`ing.riga`, `i.gruppo`) restano fuori perché le loro chiavi sono italiane per scelta e
    non seguono i nomi Python.
    """
    ricetta = _ricetta_di_prova().to_dict()
    # `id` lo aggiunge l'API dopo il salvataggio, non `to_dict()`.
    disponibili = set(ricetta) | {"id"}

    lette = set(re.findall(r"\b(?:current)?[Rr]ecipe\.(\w+)", MODULI["app.js"]))
    assert lette, "nessun accesso a `recipe.` in app.js: il guard si è scollegato"

    mancanti = sorted(lette - disponibili)
    assert not mancanti, (
        f"app.js legge chiavi che il server non produce: {mancanti}. "
        f"Il server ne produce: {sorted(disponibili)}"
    )


def test_ogni_chiave_della_scheda_libreria_esiste_nell_elenco(tmp_path):
    """Lo stesso per le carte della libreria, che vengono da `Library.list_` e non da
    `to_dict()`: è una seconda forma, con chiavi sue, e quindi una seconda strada per
    divergere in silenzio dal frontend."""
    from reel2recipe.store import Library

    with Library(tmp_path / "guard.db") as libreria:
        libreria.save(_ricetta_di_prova())
        disponibili = set(libreria.list_()[0])

    # Le carte si disegnano dentro `voci.map((v) => …)`: gli accessi sono tutti su `v`.
    lette = set(re.findall(r"\bv\.(\w+)", MODULI["app.js"]))
    assert lette, "nessun accesso a `v.` in app.js: il guard si è scollegato"

    mancanti = sorted(lette - disponibili)
    assert not mancanti, (
        f"app.js legge dalle carte chiavi che `Library.list_` non produce: {mancanti}. "
        f"L'elenco ne produce: {sorted(disponibili)}"
    )


@pytest.mark.parametrize("modulo, catalogo, sorgente", [
    ("pipeline", pipeline.TEXTS, pipeline.__file__),
    ("api", api.TEXTS, api.__file__),
    ("mela", mela.TEXTS, mela.__file__),
    ("documents", documents.TEXTS, documents.__file__),
    ("units", units.MESSAGES, units.__file__),
])
def test_ogni_chiamata_passa_i_segnaposto_che_la_frase_chiede(modulo, catalogo, sorgente):
    """I nomi passati a `text(...)` devono essere quelli che la frase aspetta.

    Il guard qui sopra confronta i segnaposto **fra le due lingue**; questo confronta i
    segnaposto con **chi li riempie**, che è un'altra cosa e ha lasciato passare un difetto
    vero: durante la migrazione una rinomina meccanica ha trasformato
    `text(lingua, "pronta", titolo=…)` in `title=…` mentre la frase diceva ancora `{titolo}`.
    `str.format` solleva `KeyError`, quindi ogni lavorazione riuscita sarebbe esplosa
    all'ultimo messaggio — ma nessun test lo vedeva, perché per arrivare lì servono Ollama e
    un file vero. Il difetto è rimasto per due commit.

    Si legge il sorgente invece di eseguirlo: interessa la chiamata scritta, non quella
    percorsa da un test.
    """
    albero = ast.parse(Path(sorgente).read_text(encoding="utf-8"))
    per_chiave: dict[str, set[str]] = {
        chiave: set(re.findall(r"\{(\w+)\}", frase))
        for chiave, frase in catalogo["it"].items()
    }

    controllate = 0
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.Call) or len(nodo.args) < 2:
            continue
        nome = getattr(nodo.func, "id", None) or getattr(nodo.func, "attr", None)
        if nome not in ("text", "message"):
            continue
        chiave_nodo = nodo.args[1]
        if not (isinstance(chiave_nodo, ast.Constant) and isinstance(chiave_nodo.value, str)):
            continue                      # chiave calcolata: non verificabile da qui
        chiave = chiave_nodo.value
        assert chiave in per_chiave, f"{modulo}: `{chiave}` non esiste nel catalogo"
        passati = {kw.arg for kw in nodo.keywords if kw.arg}
        attesi = per_chiave[chiave]
        assert passati == attesi, (
            f"{modulo}, chiave `{chiave}` (riga {nodo.lineno}): la frase chiede "
            f"{sorted(attesi)}, la chiamata passa {sorted(passati)}"
        )
        controllate += 1

    assert controllate, f"{modulo}: nessuna chiamata trovata, il guard si è scollegato"


def test_ogni_chiamata_a_t_passa_i_segnaposto_che_la_frase_chiede():
    """Lo stesso guard del lato Python, per il lato senza toolchain.

    `t('minuti', { quanti: … })` contro una frase che dice `{how_many}` non solleva niente:
    `t()` sostituisce ciò che trova e lascia il resto letterale, quindi a schermo compare
    «{how_many} min». È successo davvero durante la migrazione, quando le chiavi e i
    segnaposto del catalogo sono passati all'inglese e i punti di chiamata no.

    Si legge il sorgente, come gli altri guard qui: nessun interprete JavaScript, solo la
    forma `t('chiave', { a: …, b: … })` che è l'unica usata in `app.js`.
    """
    catalogo = _chiavi_i18n()
    testi = MODULI["i18n.js"]

    # I segnaposto dichiarati da ciascuna chiave, letti dal blocco italiano.
    per_chiave: dict[str, set[str]] = {}
    chiave_corrente = None
    for riga in testi.split("export const LINGUE")[0].splitlines():
        if intestazione := re.match(r"^    (\w+):", riga):
            chiave_corrente = intestazione.group(1)
            per_chiave.setdefault(chiave_corrente, set())
        if chiave_corrente:
            per_chiave[chiave_corrente].update(re.findall(r"\{(\w+)\}", riga))

    controllate = 0
    for chiave, corpo in re.findall(r"t\('(\w+)',\s*\{([^}]*)\}", MODULI["app.js"]):
        assert chiave in catalogo["it"], f"`{chiave}` non esiste nel catalogo"
        passati = set(re.findall(r"(\w+)\s*:", corpo)) | {
            n for n in re.findall(r"^\s*(\w+)\s*$", corpo)   # forma abbreviata { cerca }
        }
        attesi = per_chiave.get(chiave, set())
        assert passati == attesi, (
            f"t('{chiave}'): la frase chiede {sorted(attesi)}, la chiamata passa {sorted(passati)}"
        )
        controllate += 1

    assert controllate, "nessuna chiamata `t(chiave, {…})` trovata: il guard si è scollegato"


# Classi presenti nel markup ma senza una regola in `style.css`. Non sono un danno — un
# gancio inutilizzato non rompe niente — ma esistevano già prima della migrazione, e
# metterle qui per nome è più onesto che allentare il guard fino a non farlo scattare più.
CLASSI_SENZA_STILE = {"btn-cook-testo", "fase-testo", "libreria"}


def test_ogni_classe_usata_ha_una_regola_nel_foglio_di_stile():
    """Una classe scritta male non solleva niente: l'elemento si disegna senza stile.

    È il difetto che il frontend rende invisibile — nessuna toolchain, nessun compilatore —
    e la rinomina degli identificatori di `app.js` ci è caduta dentro: `'fase'` era diventato
    `'stage'`, `scheda-copertina` era diventato `card-cover`, e `style.css` continuava a
    definire i nomi di prima. La pagina avrebbe funzionato e sarebbe stata illeggibile.

    I nomi delle classi restano in italiano di proposito: vivono in tre file — `index.html`,
    `app.js` e `style.css` — e spostarli è un passo suo, che non fa parte di questa
    migrazione (v. docs/naming.md).
    """
    stile = (CARTELLA_WEB / "style.css").read_text(encoding="utf-8")
    definite = set(re.findall(r"\.([a-z][\w-]*)", stile))

    usate: set[str] = set()
    for sorgente in (MODULI["app.js"], INDEX):
        for m in re.finditer(r"""class="([a-z][\w -]*)\"""", sorgente):
            usate |= set(m.group(1).split())
        for m in re.finditer(r"""className\s*=\s*'([a-z][\w -]*)'""", sorgente):
            usate |= set(m.group(1).split())
        for m in re.finditer(r"""classList\.(?:add|remove|toggle)\('([\w-]+)'\)""", sorgente):
            usate.add(m.group(1))
        for m in re.finditer(r"""querySelector(?:All)?\('\.([\w-]+)""", sorgente):
            usate.add(m.group(1))

    assert usate, "nessuna classe trovata: il guard si è scollegato"
    orfane = sorted(usate - definite - CLASSI_SENZA_STILE)
    assert not orfane, f"classi usate ma senza regola in style.css: {orfane}"
