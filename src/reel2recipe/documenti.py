"""documenti.py — export in Markdown e PDF, per chi non usa Mela.

`.melarecipe` è il formato migliore *se* hai Mela. Chi non ce l'ha resterebbe senza niente
da tenere, e una ricetta che non puoi conservare non ha risolto il problema di partenza:
ritrovarla. Da qui due formati che non chiedono di installare nulla per essere letti —
il Markdown si apre ovunque e resta modificabile, il PDF si stampa e si manda.

I due formati condividono la stessa struttura (`_blocchi`), così una ricetta esportata nei
due modi dice le stesse cose nello stesso ordine. Cambia solo la resa.

**Le lacune si esportano.** È la scelta che conta in questo modulo: chi stampa la ricetta e
la porta in cucina deve vedere che le dosi della salsa non c'erano e che quel peso è una
stima nostra. Un PDF pulito che nasconde le incertezze sarebbe più bello e peggiore.

Il Markdown non ha dipendenze. Il PDF usa reportlab, che sta nell'extra opzionale `doc`
(`uv sync --extra doc`): è una libreria Python pura, senza librerie di sistema da
installare a parte — vincolo pratico visto che questo deve girare anche dentro un
container o su un Raspberry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .mela import righe_ingredienti
from .recipe import Ricetta, percorso_libero
from .units import UNCERTAIN_PROVENANCES, text_from

# Le stringhe dei documenti, per lingua. Come in `mela.py`: poche e stabili, un dizionario
# basta e si legge meglio di un meccanismo di traduzione.
TESTI = {
    "it": {
        "ingredienti": "Ingredienti",
        "procedimento": "Procedimento",
        "note": "Note",
        "da_verificare": "Da verificare",
        "fonte": "Fonte",
        "preparazione": "preparazione {minuti} min",
        "cottura": "cottura {minuti} min",
        "stima": "«{nome}»: {quantita} è una stima, non un dato del reel",
        "ricetta_di": "Ricetta di {autore} — {url}",
        "ricetta_di_senza_url": "Ricetta di {autore}",
        "piede": ("Estratta da un reel e riorganizzata con Reel2Recipe - le quantita "
                  "mancanti sono dichiarate, mai indovinate."),
        "chiusura_md": ("*Estratta da un reel e riorganizzata con "
                        "[Reel2Recipe](https://github.com/Stinocon/Reel2Recipe). "
                        "Le quantità convertite vengono da tabelle di densità verificate; "
                        "quelle mancanti sono dichiarate, mai indovinate.*"),
    },
    "en": {
        "ingredienti": "Ingredients",
        "procedimento": "Method",
        "note": "Notes",
        "da_verificare": "To check",
        "fonte": "Source",
        "preparazione": "prep {minuti} min",
        "cottura": "cooking {minuti} min",
        "stima": "«{nome}»: {quantita} is an estimate, not something the reel stated",
        "ricetta_di": "Recipe by {autore} — {url}",
        "ricetta_di_senza_url": "Recipe by {autore}",
        "piede": ("Extracted from a reel and reorganised with Reel2Recipe - missing "
                  "quantities are declared, never guessed."),
        "chiusura_md": ("*Extracted from a reel and reorganised with "
                        "[Reel2Recipe](https://github.com/Stinocon/Reel2Recipe). "
                        "Converted quantities come from verified density tables; "
                        "missing ones are declared, never guessed.*"),
    },
}


def testo(lingua: str, chiave: str, **dati) -> str:
    """Una stringa del documento nella lingua della ricetta, con ripiego sull'italiano."""
    return text_from(TESTI, lingua, chiave, **dati)

ESTENSIONE_MARKDOWN = ".md"
ESTENSIONE_PDF = ".pdf"


# --------------------------------------------------------------------------------------
# Struttura comune ai due formati
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Blocco:
    """Un pezzo di ricetta. `tipo` dice come renderlo, non cosa significa: `titolo`,
    `sottotitolo` (le sezioni), `gruppo` (un raggruppamento di ingredienti, che sta
    *dentro* una sezione), `paragrafo`, `voce` (elenco puntato), `passo` (numerato)."""

    tipo: str
    testo: str


def _sommario(ricetta: Ricetta) -> str:
    """La riga sotto il titolo: porzioni e tempi, se ci sono. Vuota se non si sa nulla."""
    pezzi = []
    if ricetta.porzioni:
        pezzi.append(str(ricetta.porzioni))
    if ricetta.tempo_preparazione_min:
        pezzi.append(testo(ricetta.lingua, "preparazione", minuti=ricetta.tempo_preparazione_min))
    if ricetta.tempo_cottura_min:
        pezzi.append(testo(ricetta.lingua, "cottura", minuti=ricetta.tempo_cottura_min))
    return " · ".join(pezzi)


def _blocchi(ricetta: Ricetta) -> list[Blocco]:
    """La ricetta come sequenza di blocchi, nell'ordine in cui va letta.

    L'ordine non è casuale: prima cosa serve (ingredienti), poi cosa fare (procedimento),
    poi ciò di cui diffidare (da verificare), infine di chi è la ricetta (fonte). Le note
    dell'autore stanno prima delle lacune perché sono sue, non nostre.
    """
    blocchi = [Blocco("titolo", ricetta.titolo)]

    if sommario := _sommario(ricetta):
        blocchi.append(Blocco("sommario", sommario))
    if ricetta.descrizione:
        blocchi.append(Blocco("paragrafo", ricetta.descrizione))

    lingua = ricetta.lingua
    blocchi.append(Blocco("sottotitolo", testo(lingua, "ingredienti")))
    for riga in righe_ingredienti(ricetta):
        # `righe_ingredienti` marca i titoli di gruppo con "#", che è la convenzione di
        # Mela. Qui diventano intestazioni di grado inferiore: "Salsa" è una parte degli
        # ingredienti, non una sezione pari a "Procedimento".
        if riga.startswith("# "):
            blocchi.append(Blocco("gruppo", riga[2:]))
        else:
            blocchi.append(Blocco("voce", riga))

    if ricetta.procedimento:
        blocchi.append(Blocco("sottotitolo", testo(lingua, "procedimento")))
        blocchi.extend(Blocco("passo", passo) for passo in ricetta.procedimento)

    if ricetta.note:
        blocchi.append(Blocco("sottotitolo", testo(lingua, "note")))
        blocchi.extend(Blocco("voce", nota) for nota in ricetta.note)

    if avvertenze := _avvertenze(ricetta):
        blocchi.append(Blocco("sottotitolo", testo(lingua, "da_verificare")))
        blocchi.extend(Blocco("voce", a) for a in avvertenze)

    if riga := _riga_fonte(ricetta):
        blocchi.append(Blocco("sottotitolo", testo(lingua, "fonte")))
        blocchi.append(Blocco("paragrafo", riga))

    return blocchi


def _avvertenze(ricetta: Ricetta) -> list[str]:
    """Le lacune dichiarate, più le quantità che sono stime e non dati.

    Le due cose sono diverse e vanno dette entrambe: "non era indicato" è un buco,
    "un pizzico ≈ 0,5 g" è un numero nostro. Chi cucina deve poter distinguere.
    """
    righe = list(ricetta.lacune)
    stimate = [
        testo(ricetta.lingua, "stima", nome=i.name, quantita=i.quantity.text())
        for i in ricetta.ingredienti
        if i.quantity.provenance in UNCERTAIN_PROVENANCES and i.quantity.value is not None
    ]
    # Le lacune di `recipe.py` già nominano gli ingredienti senza quantità: si tengono solo
    # le stime che non sono già state dichiarate, per non ripetere la stessa cosa due volte.
    return righe + [s for s in stimate if not any(s.split("»")[0] in r for r in righe)]


def _riga_fonte(ricetta: Ricetta) -> str:
    """L'attribuzione. Non è un dettaglio di cortesia: la ricetta è di chi l'ha fatta, e il
    procedimento riformulato ha senso solo se resta il rimando all'originale (docs/legale.md)."""
    if not ricetta.fonte:
        return ""
    autore, url = ricetta.fonte.autore, ricetta.fonte.url
    if autore and url:
        return testo(ricetta.lingua, "ricetta_di", autore=autore, url=url)
    if autore:
        return testo(ricetta.lingua, "ricetta_di_senza_url", autore=autore)
    return url or ""


# --------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------


def verso_markdown(ricetta: Ricetta) -> str:
    """La ricetta in Markdown. Nessuna dipendenza: è testo."""
    righe: list[str] = []
    numero_passo = 0

    for blocco in _blocchi(ricetta):
        if blocco.tipo == "titolo":
            righe += [f"# {blocco.testo}"]
        elif blocco.tipo == "sommario":
            righe += ["", f"*{blocco.testo}*"]
        elif blocco.tipo in ("sottotitolo", "gruppo"):
            numero_passo = 0
            cancelletti = "##" if blocco.tipo == "sottotitolo" else "###"
            righe += ["", f"{cancelletti} {blocco.testo}", ""]
        elif blocco.tipo == "paragrafo":
            righe += [blocco.testo, ""]
        elif blocco.tipo == "voce":
            righe.append(f"- {blocco.testo}")
        elif blocco.tipo == "passo":
            numero_passo += 1
            righe.append(f"{numero_passo}. {blocco.testo}")

    corpo = "\n".join(righe).strip()
    return f"{corpo}\n\n---\n\n" + testo(ricetta.lingua, "chiusura_md") + "\n"


def scrivi_markdown(ricetta: Ricetta, cartella: Path | str) -> Path:
    """Scrive la ricetta come file `.md`. Ritorna il percorso creato."""
    percorso = percorso_libero(cartella, ricetta.nome_file(), ESTENSIONE_MARKDOWN)
    percorso.write_text(verso_markdown(ricetta), encoding="utf-8")
    return percorso


# --------------------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------------------

# I font standard del PDF coprono Latin-1: gli accenti italiani ci sono, i simboli
# tipografici e le emoji no. Invece di lasciare che diventino rettangoli neri, i pochi
# caratteri che produciamo davvero si traducono, e il resto si toglie.
_SOSTITUZIONI_PDF = {
    "≈": "~", "–": "-", "—": "-", "→": "->", "×": "x", "°": "°",
    "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "·": "-", " ": " ",
}


def _testo_pdf(testo: str) -> str:
    """Riduce il testo a ciò che i font standard sanno disegnare.

    Il PDF è l'unico formato dei tre che non può rendere qualunque carattere: il Markdown
    è UTF-8 e Mela pure. Qui una emoji rimasta in una nota diventerebbe un rettangolo, che
    è peggio della sua assenza. Gli accenti — l'unica cosa che conta davvero in italiano —
    stanno in Latin-1 e restano.
    """
    for prima, dopo in _SOSTITUZIONI_PDF.items():
        testo = testo.replace(prima, dopo)
    ripulito = testo.encode("latin-1", "ignore").decode("latin-1")
    # Le emoji sparendo lasciano doppi spazi: si richiudono, o il testo sembra sbagliato.
    return " ".join(ripulito.split())


def _xml_sicuro(testo: str) -> str:
    """reportlab legge i paragrafi come mini-XML: `<` e `&` vanno protetti o l'export
    esplode su un ingrediente che contiene "<" o una nota con "&"."""
    return testo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ErroreDocumento(RuntimeError):
    """L'export non è stato prodotto. Il messaggio deve dire cosa fare."""


def scrivi_pdf(ricetta: Ricetta, cartella: Path | str) -> Path:
    """Scrive la ricetta come PDF impaginato. Ritorna il percorso creato."""
    try:
        from reportlab.lib.enums import TA_JUSTIFY
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate
    except ImportError as e:
        raise ErroreDocumento(
            "L'export in PDF richiede le dipendenze «doc». Installale con:\n"
            "  uv sync --extra doc\n"
            "Il Markdown invece non richiede nulla: usa --formato markdown."
        ) from e

    stili = {
        "titolo": ParagraphStyle("titolo", fontName="Helvetica-Bold", fontSize=20,
                                 leading=25, spaceAfter=2 * mm),
        "sommario": ParagraphStyle("sommario", fontName="Helvetica-Oblique", fontSize=10,
                                   leading=14, textColor="#666666", spaceAfter=5 * mm),
        "sottotitolo": ParagraphStyle("sottotitolo", fontName="Helvetica-Bold", fontSize=13,
                                      leading=17, spaceBefore=6 * mm, spaceAfter=2 * mm),
        "gruppo": ParagraphStyle("gruppo", fontName="Helvetica-Bold", fontSize=10.5,
                                 leading=14, spaceBefore=3 * mm, spaceAfter=1 * mm),
        "paragrafo": ParagraphStyle("paragrafo", fontName="Helvetica", fontSize=10.5,
                                    leading=15, alignment=TA_JUSTIFY, spaceAfter=2 * mm),
        "voce": ParagraphStyle("voce", fontName="Helvetica", fontSize=10.5, leading=15),
        "passo": ParagraphStyle("passo", fontName="Helvetica", fontSize=10.5, leading=15),
    }

    def paragrafo(blocco: Blocco):
        return Paragraph(_xml_sicuro(_testo_pdf(blocco.testo)), stili[blocco.tipo])

    contenuto: list = []
    # Voci e passi si accumulano per essere resi come un elenco unico: reportlab numera i
    # passi da sé, e così la numerazione riparte a ogni sezione senza contarla a mano.
    gruppo: list = []
    tipo_gruppo = ""

    def chiudi_gruppo():
        nonlocal gruppo, tipo_gruppo
        if not gruppo:
            return
        numerato = tipo_gruppo == "passo"
        contenuto.append(ListFlowable(
            [ListItem(p, leftIndent=6 * mm) for p in gruppo],
            bulletType="1" if numerato else "bullet",
            bulletFontName="Helvetica",
            # I numeri dei passi vanno letti come il testo che introducono; il punto di un
            # elenco puntato invece si vuole discreto.
            bulletFontSize=10.5 if numerato else 8,
            leftIndent=6 * mm, spaceAfter=2 * mm,
        ))
        gruppo, tipo_gruppo = [], ""

    for blocco in _blocchi(ricetta):
        if blocco.tipo in ("voce", "passo"):
            if tipo_gruppo and blocco.tipo != tipo_gruppo:
                chiudi_gruppo()
            tipo_gruppo = blocco.tipo
            gruppo.append(paragrafo(blocco))
        else:
            chiudi_gruppo()
            contenuto.append(paragrafo(blocco))
    chiudi_gruppo()

    def piede(canvas, documento):
        """La provenienza sta nel piede, non in fondo al testo.

        Messa nel flusso finiva da sola su una seconda pagina quasi vuota ogni volta che la
        ricetta riempiva la prima. Nel piede compare su ogni pagina, non sposta niente e
        non può restare orfana. Il numero di pagina c'è solo se le pagine sono più d'una.
        """
        canvas.saveState()
        canvas.setFont("Helvetica-Oblique", 7.5)
        canvas.setFillGray(0.55)
        canvas.drawString(20 * mm, 11 * mm, _testo_pdf(testo(ricetta.lingua, "piede")))
        if canvas.getPageNumber() > 1 or documento.page > 1:
            canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()

    percorso = percorso_libero(cartella, ricetta.nome_file(), ESTENSIONE_PDF)
    SimpleDocTemplate(
        str(percorso), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
        title=_testo_pdf(ricetta.titolo), author="Reel2Recipe",
    ).build(contenuto, onFirstPage=piede, onLaterPages=piede)
    return percorso
