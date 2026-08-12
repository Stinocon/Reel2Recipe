"""recipe.py — il modello di una ricetta e il passaggio dalla bozza dell'LLM alla ricetta finita.

L'LLM produce una *bozza* (`RecipeDraft`): testo estratto dal reel, con le quantità grezze
esattamente come erano dette o scritte. Qui la bozza diventa una `Ricetta`: le quantità
passano per `units.py` e si trasformano in misure metriche con la loro provenienza, le
temperature in Fahrenheit diventano Celsius, e tutto ciò che non è stato possibile
determinare finisce in `lacune` invece di sparire.

La regola che governa questo modulo: **una lacuna dichiarata vale più di un numero
inventato**. Chi cucina può gestire "quantità non indicata"; non può gestire un peso
sbagliato di cui non sa che è sbagliato.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .units import (
    PROVENIENZE_INCERTE,
    Lingua,
    Sistema,
    Ingrediente,
    Provenienza,
    Quantita,
    Tabelle,
    carica_tabelle,
    converti_temperature_nel_testo,
    normalizza_ingrediente,
    sigla,
)


def percorso_libero(cartella: Path | str, base: str, estensione: str) -> Path:
    """Un percorso che non esiste ancora, aggiungendo `-2`, `-3`… se serve.

    Un export non deve mai sovrascrivere in silenzio quello di ieri: se ne accorgerebbe
    solo chi va a cercare il file vecchio e non lo trova più. La cartella viene creata.
    """
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / f"{base}{estensione}"
    n = 2
    while percorso.exists():
        percorso = cartella / f"{base}-{n}{estensione}"
        n += 1
    return percorso


@dataclass
class Fonte:
    """Da dove viene la ricetta. Va sempre valorizzata quando è nota: l'attribuzione
    all'autore originale non è un optional, è il modo corretto di usare il suo lavoro."""

    url: str | None = None
    autore: str | None = None
    piattaforma: str | None = None
    titolo_originale: str | None = None
    acquisita_il: str | None = None

    @staticmethod
    def adesso(**kwargs) -> "Fonte":
        return Fonte(acquisita_il=datetime.now(timezone.utc).isoformat(timespec="seconds"), **kwargs)


@dataclass
class Ricetta:
    titolo: str
    ingredienti: list[Ingrediente] = field(default_factory=list)
    procedimento: list[str] = field(default_factory=list)
    descrizione: str | None = None
    porzioni: str | None = None
    tempo_preparazione_min: int | None = None
    tempo_cottura_min: int | None = None
    note: list[str] = field(default_factory=list)
    categorie: list[str] = field(default_factory=list)
    fonte: Fonte | None = None
    lacune: list[str] = field(default_factory=list)
    confidenza: dict[str, str] = field(default_factory=dict)
    immagini: list[str] = field(default_factory=list)   # base64, senza intestazione data:
    trascrizione: str | None = None                     # conservata per la revisione manuale
    # I due assi con cui la ricetta è stata prodotta. Il sistema è quello in cui le quantità
    # sono espresse e non si può cambiare senza riconvertire; la lingua è quella in cui il
    # modello ha scritto nomi e procedimento, e cambiarla richiede una nuova estrazione.
    lingua: str = Lingua.IT.value
    sistema: str = Sistema.METRICO.value

    # ---- proprietà utili all'interfaccia -----------------------------------------

    @property
    def ha_incertezze(self) -> bool:
        return bool(self.lacune) or any(
            i.quantita.provenienza in PROVENIENZE_INCERTE for i in self.ingredienti
        )

    @property
    def gruppi(self) -> list[str | None]:
        """Gruppi di ingredienti nell'ordine in cui compaiono ("Per la base", "Per la crema")."""
        visti: list[str | None] = []
        for i in self.ingredienti:
            if i.gruppo not in visti:
                visti.append(i.gruppo)
        return visti

    def tempo_totale_min(self) -> int | None:
        parti = [t for t in (self.tempo_preparazione_min, self.tempo_cottura_min) if t]
        return sum(parti) if parti else None

    def nome_file(self) -> str:
        """Nome di file leggibile e sicuro, derivato dal titolo.

        Sta qui e non nei moduli di export perché ogni formato deve chiamare la stessa
        ricetta allo stesso modo: `yaki-udon.melarecipe`, `yaki-udon.md`, `yaki-udon.pdf`
        sono la stessa cosa in tre vestiti.
        """
        base = unicodedata.normalize("NFKD", self.titolo)
        base = base.encode("ascii", "ignore").decode("ascii")
        base = re.sub(r"[^\w\s-]", "", base).strip()
        base = re.sub(r"[\s_]+", "-", base).lower()
        return (base or "ricetta")[:60]

    # ---- serializzazione ----------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ingredienti"] = [
            {
                "nome": i.nome,
                "note": i.note,
                "gruppo": i.gruppo,
                "lacuna": i.lacuna,
                "riga": i.riga_mela(),
                "quantita": {
                    "valore": i.quantita.valore,
                    "valore_max": i.quantita.valore_max,
                    "unita": i.quantita.unita,
                    "provenienza": i.quantita.provenienza.value,
                    "testo_originale": i.quantita.testo_originale,
                    "nota": i.quantita.nota,
                    "sistema": i.quantita.sistema,
                    "incerta": i.quantita.provenienza in PROVENIENZE_INCERTE,
                },
            }
            for i in self.ingredienti
        ]
        d["tempo_totale_min"] = self.tempo_totale_min()
        d["ha_incertezze"] = self.ha_incertezze
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @staticmethod
    def from_dict(d: dict) -> "Ricetta":
        ingredienti = []
        for i in d.get("ingredienti", []):
            q = i.get("quantita") or {}
            ingredienti.append(
                Ingrediente(
                    nome=i.get("nome", ""),
                    note=i.get("note"),
                    gruppo=i.get("gruppo"),
                    lacuna=i.get("lacuna"),
                    quantita=Quantita(
                        valore=q.get("valore"),
                        unita=q.get("unita"),
                        provenienza=Provenienza(q.get("provenienza", "assente")),
                        testo_originale=q.get("testo_originale", ""),
                        valore_max=q.get("valore_max"),
                        nota=q.get("nota"),
                        sistema=q.get("sistema", Sistema.METRICO.value),
                    ),
                )
            )
        fonte = Fonte(**d["fonte"]) if d.get("fonte") else None
        return Ricetta(
            titolo=d.get("titolo", "Senza titolo"),
            ingredienti=ingredienti,
            procedimento=list(d.get("procedimento") or []),
            descrizione=d.get("descrizione"),
            porzioni=d.get("porzioni"),
            tempo_preparazione_min=d.get("tempo_preparazione_min"),
            tempo_cottura_min=d.get("tempo_cottura_min"),
            note=list(d.get("note") or []),
            categorie=list(d.get("categorie") or []),
            fonte=fonte,
            lacune=list(d.get("lacune") or []),
            confidenza=dict(d.get("confidenza") or {}),
            immagini=list(d.get("immagini") or []),
            trascrizione=d.get("trascrizione"),
            lingua=d.get("lingua", Lingua.IT.value),
            sistema=d.get("sistema", Sistema.METRICO.value),
        )


# --------------------------------------------------------------------------------------
# Dalla bozza dell'LLM alla ricetta normalizzata
# --------------------------------------------------------------------------------------


def _intero_o_none(valore) -> int | None:
    try:
        n = int(float(valore))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def da_bozza(
    bozza: dict,
    fonte: Fonte | None = None,
    immagini: list[str] | None = None,
    trascrizione: str | None = None,
    tabelle: Tabelle | None = None,
    lingua: str = Lingua.IT,
    sistema: str = Sistema.METRICO,
) -> Ricetta:
    """Trasforma la bozza JSON prodotta da `extract.py` in una `Ricetta` normalizzata.

    Qui avviene tutta la conversione delle quantità: la bozza arriva con i valori grezzi
    ("1", "cup") e ne esce con quelli metrici e la loro provenienza. Le lacune emerse
    durante la conversione si sommano a quelle già dichiarate dall'LLM.
    """
    t = tabelle or carica_tabelle()

    ingredienti: list[Ingrediente] = []
    lacune: list[str] = list(bozza.get("lacune") or [])

    for grezzo in bozza.get("ingredienti") or []:
        nome = (grezzo.get("nome") or "").strip()
        if not nome:
            continue
        ingrediente = normalizza_ingrediente(
            nome=nome,
            quantita_raw=grezzo.get("quantita_raw"),
            unita_raw=grezzo.get("unita_raw"),
            note=(grezzo.get("note") or None),
            gruppo=(grezzo.get("gruppo") or None),
            tabelle=t,
            sistema=sistema,
            lingua=lingua,
        )
        ingredienti.append(ingrediente)
        if ingrediente.lacuna:
            lacune.append(ingrediente.lacuna)

    # Le temperature in Fahrenheit nel procedimento vanno portate a Celsius: un forno
    # italiano non ha quella scala. Ogni sostituzione viene tracciata fra le note.
    procedimento: list[str] = []
    note_temperature: list[str] = []
    for passo in bozza.get("procedimento") or []:
        testo = str(passo).strip()
        if not testo:
            continue
        convertito, sostituzioni = converti_temperature_nel_testo(testo, t, sistema)
        procedimento.append(convertito)
        note_temperature.extend(sostituzioni)

    note = list(bozza.get("note") or [])
    if note_temperature:
        # La direzione dipende dal sistema: verso il metrico si arriva ai Celsius, verso
        # l'imperiale ai Fahrenheit. Dirlo al contrario sarebbe peggio che tacerlo.
        intestazioni = {
            "it": {"metrico": "Temperature convertite in Celsius: ",
                   "imperiale": "Temperature convertite in Fahrenheit: "},
            "en": {"metrico": "Temperatures converted to Celsius: ",
                   "imperiale": "Temperatures converted to Fahrenheit: "},
        }
        per_lingua = intestazioni.get(sigla(lingua), intestazioni["it"])
        note.append(per_lingua[sigla(sistema)] + ", ".join(dict.fromkeys(note_temperature)))

    return Ricetta(
        lingua=sigla(lingua),
        sistema=sigla(sistema),
        titolo=(bozza.get("titolo") or "Ricetta senza titolo").strip(),
        ingredienti=ingredienti,
        procedimento=procedimento,
        descrizione=(bozza.get("descrizione") or None),
        porzioni=(bozza.get("porzioni") or None),
        tempo_preparazione_min=_intero_o_none(bozza.get("tempo_preparazione_min")),
        tempo_cottura_min=_intero_o_none(bozza.get("tempo_cottura_min")),
        note=note,
        categorie=[c for c in (bozza.get("categorie") or []) if c],
        fonte=fonte,
        lacune=list(dict.fromkeys(lacune)),
        confidenza=dict(bozza.get("confidenza") or {}),
        immagini=list(immagini or []),
        trascrizione=trascrizione,
    )
