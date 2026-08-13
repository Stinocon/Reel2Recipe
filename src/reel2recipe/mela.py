"""mela.py — export nel formato di Mela (app di ricette per iOS/macOS).

Il formato è documentato pubblicamente dall'autore su https://mela.recipes/fileformat/.
Due cose contano più di tutte, e sono la ragione per cui questo modulo esiste invece di
un `json.dumps` sparso nel codice:

1. `ingredients` e `instructions` sono **stringhe separate da `\\n`**, non array. Una riga
   che inizia con `#` diventa un titolo di gruppo ("# Per la crema").
2. Il parser di Mela riconosce già quantità e unità in italiano. Quindi la forma giusta
   per un ingrediente è la stringa piana "200 g farina 00": inventare una struttura nostra
   e poi ricomporla peggiorerebbe il risultato. Il testo fra parentesi Mela lo tratta come
   commento, ed è lì che finiscono le note e gli equivalenti ("≈ 4 g").

`.melarecipe` è un singolo JSON; `.melarecipes` è uno zip di `.melarecipe`, che è come si
importano più ricette in un colpo solo.
"""

from __future__ import annotations

import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .recipe import Ricetta, percorso_libero
from .units import text_from

# Intestazioni e frasi dell'export, per lingua. Poche e stabili: un dizionario qui è più
# leggibile di un meccanismo di traduzione per una manciata di stringhe.
TESTI = {
    "it": {
        "da_verificare": "Da verificare",
        "fonte": "Fonte",
        "ricetta_di": "Ricetta di {autore}",
        "ricetta_di_con_url": "Ricetta di {autore} — {url}",
        "riorganizzata": "Trascritta e riorganizzata automaticamente con Reel2Recipe.",
    },
    "en": {
        "da_verificare": "To check",
        "fonte": "Source",
        "ricetta_di": "Recipe by {autore}",
        "ricetta_di_con_url": "Recipe by {autore} — {url}",
        "riorganizzata": "Transcribed and reorganised automatically with Reel2Recipe.",
    },
}


def testo(lingua: str, chiave: str, **dati) -> str:
    """Una stringa dell'export nella lingua della ricetta, con ripiego sull'italiano."""
    return text_from(TESTI, lingua, chiave, **dati)

# Mela memorizza le date come secondi dal 1° gennaio 2001 UTC (epoca di riferimento Apple).
_EPOCA_APPLE = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Numerazione in testa a un passo: "1. ", "2) ", "3 - ". Tre cautele, perché qui si cancella
# testo e cancellarne troppo è silenzioso: solo a inizio riga, sempre seguita da spazio, e solo
# se dopo comincia una parola. L'ultima serve per "5 - 6 minuti di cottura", che senza di essa
# diventerebbe "6 minuti di cottura" — un numero cambiato senza che nessuno se ne accorga, che
# è il danno che questo progetto esiste per non fare (AGENTS.md §3).
_NUMERAZIONE = re.compile(r"^\d{1,2}\s*[.)\-]\s+(?=[^\W\d_])")

ESTENSIONE_SINGOLA = ".melarecipe"
ESTENSIONE_MULTIPLA = ".melarecipes"


def _durata(minuti: int | None) -> str:
    """Durata come la scrive un ricettario: "25 min", "1 h 30 min"."""
    if not minuti or minuti <= 0:
        return ""
    ore, resto = divmod(int(minuti), 60)
    if ore and resto:
        return f"{ore} h {resto} min"
    if ore:
        return f"{ore} h"
    return f"{resto} min"


def _identificativo(ricetta: Ricetta) -> str:
    """Mela accetta un UUID oppure, per le ricette importate dal web, l'URL senza schema.

    Usare l'URL quando c'è non è un dettaglio: dà a Mela una chiave stabile, così
    reimportare la stessa ricetta aggiorna quella esistente invece di duplicarla.
    """
    url = ricetta.fonte.url if ricetta.fonte else None
    if url:
        return re.sub(r"^https?://", "", url.strip()).rstrip("/")
    return str(uuid.uuid4())


def righe_ingredienti(ricetta: Ricetta) -> list[str]:
    """Ingredienti come righe di testo, con i titoli di gruppo nel formato `# Titolo`."""
    righe: list[str] = []
    gruppi = ricetta.gruppi
    mostra_intestazioni = len([g for g in gruppi if g]) > 0 and len(gruppi) > 1

    for gruppo in gruppi:
        if mostra_intestazioni and gruppo:
            righe.append(f"# {gruppo}")
        for ingrediente in ricetta.ingredienti:
            if ingrediente.group == gruppo:
                righe.append(ingrediente.mela_line())
    return righe


def righe_procedimento(ricetta: Ricetta) -> list[str]:
    """Passi senza numerazione: la mette Mela.

    Qui prima si scriveva "1. ", per l'ipotesi che una numerazione esplicita sopravvivesse
    all'import meglio di una implicita. La prima ricetta aperta davvero in Mela l'ha smentita:
    Mela numera le righe da sé e il risultato era "1 1. Frullare il tofu…". L'ipotesi non era
    verificabile finché l'app non l'ha vista, ed è caduta al primo riscontro.

    Un passo che arriva già numerato dal modello viene ripulito, altrimenti si ricade nello
    stesso doppione per un'altra strada.
    """
    return [_NUMERAZIONE.sub("", passo.strip()) for passo in ricetta.procedimento]


def righe_note(ricetta: Ricetta) -> list[str]:
    """Note, avvertenze sulle conversioni e attribuzione.

    Le lacune finiscono qui e non vengono nascoste: chi apre la ricetta in cucina deve
    sapere quali quantità sono stime nostre e quali il reel non le diceva affatto.
    """
    righe: list[str] = list(ricetta.note)
    lingua = ricetta.lingua

    if ricetta.lacune:
        righe.append("")
        righe.append("# " + testo(lingua, "da_verificare"))
        righe.extend(f"* {l}" for l in ricetta.lacune)

    if ricetta.fonte and (ricetta.fonte.url or ricetta.fonte.autore):
        righe.append("")
        righe.append("# " + testo(lingua, "fonte"))
        autore = ricetta.fonte.autore
        url = ricetta.fonte.url
        if autore and url:
            righe.append(testo(lingua, "ricetta_di_con_url", autore=autore, url=url))
        elif autore:
            righe.append(testo(lingua, "ricetta_di", autore=autore))
        elif url:
            righe.append(url)
        righe.append(testo(lingua, "riorganizzata"))

    return righe


def verso_melarecipe(ricetta: Ricetta) -> dict:
    """Costruisce il dizionario `.melarecipe`. Le chiavi e i tipi seguono il formato
    documentato: tutte stringhe tranne `images` (array), `favorite`/`wantToCook` (bool)
    e `date` (float)."""
    return {
        "id": _identificativo(ricetta),
        "title": ricetta.titolo,
        "text": ricetta.descrizione or "",
        "images": list(ricetta.immagini),
        # Mela non ammette virgole nei nomi di categoria: le sostituiamo invece di
        # produrre categorie spezzate all'import.
        "categories": [c.replace(",", " ").strip() for c in ricetta.categorie if c.strip()],
        "yield": ricetta.porzioni or "",
        "prepTime": _durata(ricetta.tempo_preparazione_min),
        "cookTime": _durata(ricetta.tempo_cottura_min),
        "totalTime": _durata(ricetta.tempo_totale_min()),
        "ingredients": "\n".join(righe_ingredienti(ricetta)),
        "instructions": "\n".join(righe_procedimento(ricetta)),
        "notes": "\n".join(righe_note(ricetta)).strip(),
        "nutrition": "",
        "link": (ricetta.fonte.url if ricetta.fonte else "") or "",
        "favorite": False,
        "wantToCook": False,
        "date": (datetime.now(timezone.utc) - _EPOCA_APPLE).total_seconds(),
    }


def scrivi_melarecipe(ricetta: Ricetta, cartella: Path | str) -> Path:
    """Scrive una singola ricetta come `.melarecipe`. Ritorna il percorso creato."""
    percorso = percorso_libero(cartella, ricetta.nome_file(), ESTENSIONE_SINGOLA)
    percorso.write_text(
        json.dumps(verso_melarecipe(ricetta), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return percorso


def scrivi_melarecipes(ricette: list[Ricetta], percorso: Path | str) -> Path:
    """Scrive più ricette in un unico `.melarecipes` (uno zip di `.melarecipe`),
    che è il modo di importare un'infornata di ricette in Mela in una volta sola."""
    percorso = Path(percorso)
    if percorso.suffix != ESTENSIONE_MULTIPLA:
        percorso = percorso.with_suffix(ESTENSIONE_MULTIPLA)
    percorso.parent.mkdir(parents=True, exist_ok=True)

    usati: set[str] = set()
    with zipfile.ZipFile(percorso, "w", zipfile.ZIP_DEFLATED) as z:
        for ricetta in ricette:
            base = ricetta.nome_file()
            nome, n = f"{base}{ESTENSIONE_SINGOLA}", 2
            while nome in usati:
                nome = f"{base}-{n}{ESTENSIONE_SINGOLA}"
                n += 1
            usati.add(nome)
            z.writestr(
                nome,
                json.dumps(verso_melarecipe(ricetta), ensure_ascii=False, indent=2),
            )
    return percorso


def leggi_melarecipe(percorso: Path | str) -> dict:
    """Rilegge un `.melarecipe`. Serve ai test di round-trip e a reimportare un export."""
    return json.loads(Path(percorso).read_text(encoding="utf-8"))
