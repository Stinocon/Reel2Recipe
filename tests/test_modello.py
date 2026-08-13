"""Gate sul comportamento del modello locale: rispetta la regola «non inventare»?

Perché esiste. La qualità di Reel2Recipe non dipende solo dal nostro codice: dipende anche
da quanto il modello locale rispetta il prompt. Provando un reel vero è emerso che
`qwen2.5:7b-instruct`, davanti a un elenco di ingredienti senza dosi («Salsa: soia, mirin e
dashi»), **distribuiva dosi plausibili** — «1 tazza» di soia che nessuno aveva mai scritto.
È il fallimento peggiore possibile per questo progetto: un numero inventato di cui l'utente non
sa che è inventato. È la regola d'oro "non inventare" (v. docs/architettura.md) messa alla
prova sul modello davvero installato. Il modello predefinito, `qwen2.5:14b`, non lo fa.

Quel difetto è stato scoperto per caso. Questo test fa in modo che non serva più la fortuna.

Non gira di default: richiede Ollama acceso e costa da decine di secondi a qualche minuto,
quindi non sta nel percorso di `./check.sh`. Si lancia deliberatamente, dopo aver toccato il
prompt di `extract.py` o cambiato il modello predefinito:

    R2R_TEST_MODELLO=1 uv run pytest tests/test_modello.py -v

Con `R2R_MODELLO` si prova un modello specifico invece del predefinito:

    R2R_TEST_MODELLO=1 R2R_MODELLO=qwen2.5:7b-instruct uv run pytest tests/test_modello.py -v
"""

from __future__ import annotations

import os

import pytest

from reel2recipe import extract

# Una didascalia costruita apposta: un ingrediente CON la dose e tre gruppi SENZA. È la
# forma in cui gli autori scrivono davvero, ed è la trappola in cui cade un modello piccolo.
DIDASCALIA = """\
Yaki Udon, pronti in 10 minuti netti!

🥣 INGREDIENTI:
Udon precotti
80g di Maiale (fettina grassa)
Verdure: Cipolla, Carote e Cavolo Cappuccio
Salsa: Soia, Mirin e Dashi in polvere

PROCEDIMENTO:
Taglia le verdure, rosola il maiale, aggiungi gli udon e la salsa. Salta tutto.
"""

# Gli ingredienti che nella didascalia NON hanno alcuna dose. Per ognuno il modello deve
# lasciare quantità e unità vuote e dichiarare la lacuna, non riempire a intuito.
SENZA_DOSE = ("cipolla", "carote", "cavolo", "soia", "mirin", "dashi", "udon")


def _senza_ollama() -> bool:
    return not extract.ollama_attivo()


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("R2R_TEST_MODELLO") != "1",
        reason="gate sul modello: lento e richiede Ollama. Attiva con R2R_TEST_MODELLO=1",
    ),
    pytest.mark.skipif(_senza_ollama(), reason="Ollama non risponde"),
]


@pytest.fixture(scope="module")
def bozza() -> dict:
    """Una sola estrazione per tutto il modulo: è la parte lenta."""
    return extract.estrai_bozza(
        didascalia=DIDASCALIA,
        transcript="",
        titolo="Yaki Udon",
        modello=os.environ.get("R2R_MODELLO"),
    ).bozza


def _ingredienti_senza_dose(bozza: dict) -> list[dict]:
    return [
        i for i in (bozza.get("ingredienti") or [])
        if any(parola in (i.get("nome") or "").lower() for parola in SENZA_DOSE)
    ]


def test_non_inventa_le_dosi_mancanti(bozza):
    """Il test che conta. Un elenco senza dosi deve restare senza dosi.

    Si controlla la comparsa di un **numero**, che è il danno vero: un peso plausibile di cui
    chi cucina non sa che è inventato. Una parola finita per sbaglio in `unita_raw` (il 14b
    manda "polvere" per «Dashi in polvere») non è questo problema, ed è già neutralizzata a
    valle da `units.py`, che la rende come nota fra parentesi invece che come unità.

    Se questo diventa rosso, il modello in uso non è affidabile per il compito: non
    "aggiustare" il test — cambiare modello o rinforzare il prompt.
    """
    inventate = [
        (i.get("nome"), i.get("quantita_raw"), i.get("unita_raw"))
        for i in _ingredienti_senza_dose(bozza)
        if any(c.isdigit() for c in f"{i.get('quantita_raw') or ''} {i.get('unita_raw') or ''}")
    ]
    assert not inventate, (
        "il modello ha inventato quantità per ingredienti che nella didascalia non ne "
        f"avevano: {inventate}. È la violazione della regola 2 del prompt: non inventare."
    )


def test_riporta_la_dose_che_c_era(bozza):
    """Speculare al precedente: la prudenza non deve diventare cecità. Gli 80 g del maiale
    sono scritti, e devono uscire — grezzi, non convertiti."""
    maiale = [i for i in (bozza.get("ingredienti") or []) if "maiale" in (i.get("nome") or "").lower()]
    assert maiale, "il maiale è sparito dall'estrazione"
    grezzo = f"{maiale[0].get('quantita_raw') or ''} {maiale[0].get('unita_raw') or ''}".lower()
    assert "80" in grezzo, f"la dose dichiarata non è stata riportata: {grezzo!r}"
    # Il modello non deve convertire: 80 g non diventano cup, once o altro (§3).
    assert not any(u in grezzo for u in ("cup", "oz", "once")), f"il modello ha convertito: {grezzo!r}"


def test_dichiara_le_lacune(bozza):
    """Non inventare non basta: il buco va anche dichiarato, o l'utente non sa che c'è."""
    assert (bozza.get("lacune") or []), "nessuna lacuna dichiarata malgrado tre gruppi senza dosi"


def test_riconosce_i_gruppi_scritti_con_i_due_punti(bozza):
    """«Verdure:», «Salsa:» sono il modo in cui le didascalie raggruppano davvero.
    Meno critico dei precedenti — un gruppo mancato è un peggioramento, non un pericolo."""
    gruppi = {(i.get("gruppo") or "").strip().lower() for i in (bozza.get("ingredienti") or [])}
    assert {"verdure", "salsa"} & gruppi, f"nessun gruppo riconosciuto: {gruppi}"


# ----------------------------------------------------------------------------------
# Lingua di uscita del modello
# ----------------------------------------------------------------------------------

# Un materiale in inglese, per verificare la traduzione verso l'italiano — la direzione
# affidabile. La direzione opposta (input IT lungo → output EN) è un limite noto di
# qwen2.5:14b, che resta ancorato all'italiano: è affidabilità del modello, non del codice,
# e non la si mette a gate.
DIDASCALIA_EN = """\
Quick Carbonara!
INGREDIENTS:
200g spaghetti
2 eggs
100g pancetta
Sauce: pecorino, black pepper
METHOD: Fry the pancetta, mix the eggs with pecorino, combine off the heat.
"""


@pytest.fixture(scope="module")
def bozza_it_da_en() -> dict:
    return extract.estrai_bozza(
        didascalia=DIDASCALIA_EN, transcript="", titolo="Carbonara",
        modello=os.environ.get("R2R_MODELLO"), language="it",
    ).bozza


def test_traduce_verso_l_italiano(bozza_it_da_en):
    """Un reel inglese chiesto in italiano deve uscire in italiano: è il caso dell'utente
    italiano che guarda un video americano, il più comune per questo progetto."""
    nomi = " ".join((i.get("nome") or "").lower() for i in (bozza_it_da_en.get("ingredienti") or []))
    # Almeno un termine chiaramente tradotto: "eggs" -> "uova", "black pepper" -> "pepe".
    assert "uova" in nomi or "pepe" in nomi, f"nomi non tradotti in italiano: {nomi}"


# ----------------------------------------------------------------------------------
# I quattro difetti trovati su reel veri
# ----------------------------------------------------------------------------------
#
# Sei estrazioni su materiale reale (09/08/2026) hanno prodotto quattro difetti. Li avevamo
# scoperti solo perché qualcuno stava guardando: nessun test copriva il prompt e lo schema di
# `extract.py`, quindi un domani che rimettesse `porzioni` fra i campi opzionali o
# indebolisse l'istruzione su `null` non avrebbe fatto diventare rosso niente.
#
# La didascalia qui sotto è **sintetica**, scritta apposta: riproduce i quattro pattern senza
# portare in repo materiale di terzi (v. docs/legale.md). Le verifiche guardano il RISULTATO
# della catena completa, non le scelte interne del modello: la stessa dose può arrivare come
# "1¼"+"cups" o come "300"+"ml" e va bene comunque — ciò che non deve succedere è che
# diventi un millilitro.

DIDASCALIA_AMBIGUA = """\
Torta di mele della nonna — per 6 persone

INGREDIENTI:
1¼ cups (300 ml) di latte
250 g di farina 00
1 mela grande (facoltativa)
sale q.b.
un pizzico di cannella

PROCEDIMENTO:
Mescola tutto e inforna a 180°C per 40 minuti.
"""


@pytest.fixture(scope="module")
def ricetta_ambigua():
    """Una sola estrazione, portata fino in fondo alla catena: è il risultato che conta."""
    from reel2recipe.recipe import Source, from_draft

    bozza = extract.estrai_bozza(
        didascalia=DIDASCALIA_AMBIGUA, transcript="", titolo="Torta di mele",
        modello=os.environ.get("R2R_MODELLO"),
    ).bozza
    return bozza, from_draft(bozza, source=Source.now(url=None, author="test"))


def _ingrediente(ricetta, parola):
    for i in ricetta.ingredients:
        if parola in i.name.lower():
            return i
    return None


def test_una_dose_scritta_due_volte_non_diventa_un_millilitro(ricetta_ambigua):
    """Il difetto peggiore trovato: «1¼ cups (300 ml)» produceva «1 ml» d'acqua, dichiarato
    come certo. Non importa quale delle due rappresentazioni sceglie il modello — devono
    portare entrambe allo stesso posto."""
    _, ricetta = ricetta_ambigua
    latte = _ingrediente(ricetta, "latte")
    assert latte, "il latte è sparito dall'estrazione"
    assert latte.quantity.unit == "ml", f"il latte non è un volume: {latte.mela_line()!r}"
    assert 250 <= latte.quantity.value <= 350, (
        f"il latte doveva restare intorno ai 300 ml, è uscito {latte.mela_line()!r}"
    )


def test_porzioni_e_cottura_non_si_possono_omettere(ricetta_ambigua):
    """Erano opzionali nello schema e il modello li ometteva SEMPRE, anche quando la fonte
    li dichiarava. Se questo torna rosso, guardare `required` in extract.py prima del prompt."""
    _, ricetta = ricetta_ambigua
    assert ricetta.servings and "6" in ricetta.servings, f"porzioni: {ricetta.servings!r}"
    assert ricetta.cook_time_min == 40, f"cottura: {ricetta.cook_time_min!r}"


def test_il_tempo_di_preparazione_non_si_inventa(ricetta_ambigua):
    """La didascalia dichiara solo la cottura. Reso obbligatorio, il campo veniva riempito
    con un numero plausibile — e spezzando un intervallo di cottura fra i due campi."""
    _, ricetta = ricetta_ambigua
    assert ricetta.prep_time_min is None, (
        f"preparazione inventata: {ricetta.prep_time_min!r} (la fonte non la dichiara)"
    )


def _grezzo(bozza: dict, parola: str) -> dict | None:
    for i in bozza.get("ingredienti") or []:
        if parola in (i.get("nome") or "").lower():
            return i
    return None


@pytest.mark.parametrize("parola, espressione", [("sale", "q.b"), ("cannella", "pizzico")])
def test_una_misura_vaga_ricevuta_non_diventa_una_lacuna_falsa(ricetta_ambigua, parola, espressione):
    """Il modello mette «q.b.» e «un pizzico» un po' dove capita — nel nome, fra parentesi nel
    nome, nelle note — e il codice non vedeva alcuna indicazione: dichiarava «quantità non
    indicata nel reel», che è falso. Una lacuna che mente vale meno di nessuna lacuna.

    La verifica riguarda **ciò che possiamo controllare**: se l'espressione è arrivata in un
    campo qualsiasi, deve diventare una quantità indeterminata o una stima. Quando il modello
    la **perde per strada** — capita, ed è un difetto suo, non nostro — non c'è nulla da
    recuperare e asserirlo renderebbe questo gate ballerino invece che informativo. In quel
    caso il test si salta dicendo perché, così l'informazione non va persa.
    """
    from reel2recipe.units import Provenance

    bozza, ricetta = ricetta_ambigua
    grezzo = _grezzo(bozza, parola)
    assert grezzo, f"«{parola}» è sparito dall'estrazione"

    campi = " ".join(str(grezzo.get(c) or "") for c in ("nome", "quantita_raw", "unita_raw", "note"))
    # I punti si tolgono da ENTRAMBI i lati: «q.b.» è impossibile da tokenizzare in modo
    # affidabile, e normalizzare solo il testo cercato produceva uno skip falso.
    if espressione.replace(".", "") not in campi.lower().replace(".", ""):
        pytest.skip(
            f"il modello non ha riportato «{espressione}» per «{parola}» in nessun campo "
            f"({campi!r}): è una perdita del modello, non un difetto della normalizzazione"
        )

    ingr = _ingrediente(ricetta, parola)
    assert ingr and ingr.quantity.provenance in {
        Provenance.INDETERMINATE, Provenance.ESTIMATED_VAGUE
    }, (
        f"«{parola}»: il modello aveva riportato l'indicazione ({campi!r}) ma è uscita come "
        f"{ingr.quantity.provenance.value} ({ingr.mela_line()!r})"
    )


def test_una_parola_fra_parentesi_non_diventa_un_unita(ricetta_ambigua):
    """«1 mela grande (facoltativa)» dava «1 (facoltativa) mela»."""
    _, ricetta = ricetta_ambigua
    mela = _ingrediente(ricetta, "mela")
    assert mela, "la mela è sparita dall'estrazione"
    assert not (mela.quantity.unit or "").startswith("("), (
        f"una parentesi è stata scambiata per un'unità: {mela.mela_line()!r}"
    )
