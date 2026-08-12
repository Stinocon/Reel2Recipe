"""units.py — normalizzazione deterministica delle quantità. Il cuore qualitativo del progetto.

PRINCIPIO: l'LLM estrae, il codice converte.

Un modello linguistico a cui si chiede "quanti grammi sono 1 cup di farina?" produce un
numero plausibile. A volte è 120, a volte 128, a volte 150, e per lo zucchero magari
ripete lo stesso numero della farina — che è sbagliato del 67%. Il modello non sta
calcolando, sta ricordando male.

Qui invece non si indovina niente: le quantità arrivano grezze da `extract.py`
(`quantita_raw`, `unita_raw`, esattamente come dette o scritte nel reel) e vengono
convertite con le tabelle versionate in `data/`. Se una conversione non è possibile —
tipicamente un volume di un ingrediente di cui non conosciamo la densità — **non si
inventa**: si conserva l'unità originale e si dichiara la lacuna.

Ogni quantità prodotta porta con sé la propria `provenienza`, così l'interfaccia può
distinguere a colpo d'occhio un dato dichiarato dal reel da una stima nostra.

Le tabelle sono tre, in `data/`:
  - `unita.yaml`    conversioni esatte fra unità (cup→ml, oz→g, °F→°C), etichette per lingua
  - `densita.yaml`  densità per ingrediente, per il passaggio volume→peso
  - `vaghe.yaml`    le misure "a occhio" (q.b., un pizzico, a pinch, a drizzle)

DUE ASSI, NON UNO: `sistema` e `lingua`.

`sistema` (metrico/imperiale) decide **i numeri**, quindi si fissa qui, alla conversione.
`lingua` (it/en) decide **le parole**: etichette delle unità e messaggi di lacuna. Non
coincidono — un australiano legge in inglese e cucina in grammi — e tenerli separati è
l'unico modo di servire entrambi.

Il sistema si applica alla quantità **grezza**, non a valle di una conversione intermedia.
"1 cup di farina" resta "1 cup" per chi cucina in imperiale invece di diventare 120 g e poi
tornare 0,83 cup: un doppio arrotondamento produce numeri che nessun misurino sa fare. Per
la stessa ragione, verso l'imperiale non si attraversa la densità: un volume resta volume,
un peso resta peso.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

# --------------------------------------------------------------------------------------
# Provenienza di una quantità: da dove viene il numero che mostriamo.
# --------------------------------------------------------------------------------------


class Lingua(str, Enum):
    """La lingua delle etichette e dei messaggi. Decide *come si scrive* una quantità."""

    IT = "it"
    EN = "en"


class Sistema(str, Enum):
    """Il sistema di misura di destinazione. Decide *quanto vale* una quantità.

    La differenza con `Lingua` non è pedanteria: un australiano legge in inglese e cucina in
    grammi, e a un italiano può servire una ricetta in cup per seguire un video americano.
    Gli assi sono due perché nella realtà non coincidono.
    """

    METRICO = "metrico"
    IMPERIALE = "imperiale"


# Messaggi rivolti a chi cucina. Stanno qui e non nelle tabelle di `data/` perché sono
# stringhe di programma, non dati di conversione: cambiano col codice che li produce.
MESSAGGI: dict[str, dict[str, str]] = {
    "it": {
        "assente": "quantità non indicata nel reel per «{nome}»",
        "non_interpretabile": "quantità «{originale}» non interpretabile per «{nome}»",
        "unita_ignota": "unità «{unita}» non riconosciuta per «{nome}»: lasciata invariata",
        "qualita_non_unita": ("quantità non indicata nel reel per «{nome}» («{unita}» è una "
                             "qualità dell'ingrediente, non un'unità)"),
        "indeterminata": "quantità indeterminata («{originale}») per «{nome}»",
        "densita_ignota": ("densità sconosciuta per «{nome}»: quantità lasciata in volume, "
                           "non convertita in peso"),
        "stima_vaga": "«{originale}» è una misura a occhio: il valore per «{nome}» è una stima",
        "unita_senza_conversione": "unità «{unita}» priva di conversione nelle tabelle",
        "unita_contraddittoria": ("per «{nome}» la quantità diceva «{dentro}» ma l'unità diceva "
                                  "«{fuori}»: si è usata «{dentro}», che sta insieme al suo "
                                  "numero — verifica sulla fonte"),
    },
    "en": {
        "assente": "no quantity given in the reel for «{nome}»",
        "non_interpretabile": "quantity «{originale}» could not be read for «{nome}»",
        "unita_ignota": "unit «{unita}» not recognised for «{nome}»: left as it was",
        "qualita_non_unita": ("no quantity given in the reel for «{nome}» («{unita}» describes "
                             "the ingredient, it is not a unit)"),
        "indeterminata": "open-ended quantity («{originale}») for «{nome}»",
        "densita_ignota": ("density unknown for «{nome}»: kept as a volume, not converted "
                           "to weight"),
        "stima_vaga": "«{originale}» is an eyeball measure: the value for «{nome}» is an estimate",
        "unita_senza_conversione": "unit «{unita}» has no conversion in the tables",
        "unita_contraddittoria": ("for «{nome}» the amount said «{dentro}» but the unit said "
                                  "«{fuori}»: «{dentro}» was used, as it belongs with its own "
                                  "number — check against the source"),
    },
}


def sigla(valore) -> str:
    """Il valore testuale di un enum, o la stringa così com'è.

    Serve perché `str()` su un enum che eredita da `str` NON dà il valore ma il nome
    qualificato: `str(Sistema.IMPERIALE)` è "Sistema.IMPERIALE", non "imperiale". È un
    inciampo classico, e qui costava caro: il confronto falliva sempre in silenzio e il
    ramo imperiale non veniva mai imboccato.
    """
    return valore.value if isinstance(valore, Enum) else str(valore)


def messaggio(lingua: str, chiave: str, **dati) -> str:
    """Un messaggio nella lingua richiesta. Se la lingua è ignota si ripiega sull'italiano:
    meglio un messaggio comprensibile a metà che un KeyError davanti all'utente."""
    catalogo = MESSAGGI.get(sigla(lingua), MESSAGGI["it"])
    return catalogo.get(chiave, MESSAGGI["it"][chiave]).format(**dati)


class Provenienza(str, Enum):
    ASSENTE = "assente"                      # il reel non dava alcuna quantità
    DICHIARATO = "dichiarato"                # già nell'unità giusta, nessuna conversione
    CONVERTITO_UNITA = "convertito:unita"    # conversione esatta (oz→g, cup→ml, °F→°C)
    CONVERTITO_DENSITA = "convertito:densita"  # volume→peso tramite densita.yaml
    CONTEGGIO = "conteggio"                  # pezzi contati: 2 uova, 3 spicchi
    STIMATO_VAGHE = "stimato:vaghe"          # stima da vaghe.yaml — dichiarata come tale
    INDETERMINATO = "indeterminato"          # "q.b.", "qualche": quantità non esprimibile


# Provenienze che l'interfaccia deve evidenziare perché non sono un dato certo.
PROVENIENZE_INCERTE = frozenset(
    {Provenienza.STIMATO_VAGHE, Provenienza.INDETERMINATO, Provenienza.ASSENTE}
)


# --------------------------------------------------------------------------------------
# Modello dati
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Quantita:
    """Una quantità normalizzata. `valore_max` è valorizzato solo per gli intervalli
    ("2-3 cucchiai"), dove conservare entrambi gli estremi è più onesto che sceglierne uno."""

    valore: float | None
    unita: str | None
    provenienza: Provenienza
    testo_originale: str
    valore_max: float | None = None
    nota: str | None = None
    # Il sistema in cui la quantità è espressa. Serve alla resa, non al valore: decide se
    # 0,75 si scrive "0,75" o "3/4", e quella differenza la vede solo chi legge.
    sistema: str = Sistema.METRICO.value

    @property
    def e_intervallo(self) -> bool:
        return self.valore_max is not None and self.valore_max != self.valore

    def testo(self) -> str:
        """Resa testuale della sola quantità, es. "200 g", "2-3 cucchiai", "3/4 cup"."""
        if self.valore is None:
            return self.unita or ""
        num = formatta_numero(self.valore, self.sistema)
        if self.e_intervallo:
            num = f"{num}-{formatta_numero(self.valore_max, self.sistema)}"
        return f"{num} {self.unita}".strip() if self.unita else num


@dataclass(frozen=True)
class Ingrediente:
    """Un ingrediente normalizzato, pronto per l'export."""

    nome: str
    quantita: Quantita
    note: str | None = None
    gruppo: str | None = None
    lacuna: str | None = None

    def riga_mela(self) -> str:
        """Riga nel formato che il parser di Mela sa leggere.

        Mela riconosce nativamente quantità e unità in italiano, quindi la forma giusta è
        la stringa piana "200 g farina 00" — non una struttura nostra. Il testo fra
        parentesi è trattato da Mela come commento: ci mettiamo l'equivalente in grammi
        quando conserviamo l'unità originale, e le note dell'ingrediente.
        """
        commenti = [c for c in (self.quantita.nota, self.note) if c]
        coda = f" ({'; '.join(commenti)})" if commenti else ""

        if self.quantita.provenienza is Provenienza.INDETERMINATO:
            # Convenzione italiana: il "q.b." segue il nome ("sale q.b."), non lo precede.
            marcatore = self.quantita.unita or "q.b."
            return f"{self.nome} {marcatore}{coda}".strip()

        # I modelli a volte ripetono l'unità di conteggio nel nome ("2 uova" con nome
        # "uova"): "2 uova uova" è brutto e sbagliato. Se l'unità è già nel nome, si
        # tiene solo il numero.
        testo_quantita = self.quantita.testo()
        if self.quantita.unita and _ripetuta_nel_nome(self.quantita.unita, self.nome):
            testo_quantita = formatta_numero(self.quantita.valore)
            if self.quantita.e_intervallo:
                testo_quantita = f"{testo_quantita}-{formatta_numero(self.quantita.valore_max)}"

        if not testo_quantita:
            return f"{self.nome}{coda}".strip()
        return f"{testo_quantita} {self.nome}{coda}".strip()


# --------------------------------------------------------------------------------------
# Caricamento delle tabelle
# --------------------------------------------------------------------------------------


def _singolare_plurale(parola: str) -> set[str]:
    """Varianti banali singolare/plurale italiane, per confronti tolleranti
    ("uovo"/"uova", "spicchio"/"spicchi"). Non è morfologia completa, solo i casi frequenti."""
    forme = {parola}
    if parola.endswith(("a", "o", "e")):
        forme.add(parola[:-1] + "i")
        forme.add(parola[:-1] + "e")
    if parola.endswith("i"):
        forme.update({parola[:-1] + "o", parola[:-1] + "a", parola[:-1] + "e"})
    return forme


def _ripetuta_nel_nome(unita: str, nome: str) -> bool:
    """Vero se l'etichetta dell'unità coincide con una parola del nome ingrediente
    (a meno di singolare/plurale). Serve a non scrivere "2 uova uova"."""
    parole_nome = set(_chiave(nome).split())
    for forma in _singolare_plurale(_chiave(unita)):
        if forma in parole_nome:
            return True
    return False


def _chiave(testo: str) -> str:
    """Chiave di confronto: minuscolo, senza accenti, senza punteggiatura marginale,
    spazi normalizzati. Serve a far combaciare "Farina 00", "farina 00 " e "FARINA 00"."""
    testo = unicodedata.normalize("NFD", testo.strip().lower())
    testo = "".join(c for c in testo if unicodedata.category(c) != "Mn")
    testo = testo.replace("'", "'")
    testo = re.sub(r"[^\w\s'°/.-]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


@dataclass(frozen=True)
class Tabelle:
    volume: dict[str, float]
    peso: dict[str, float]
    conteggio: frozenset[str]
    alias: dict[str, str]
    misure_a_cucchiaio: frozenset[str]
    volume_metrico: frozenset[str]
    volume_imperiale: frozenset[str]
    etichette: dict[str, dict[str, str]]   # lingua → unità canonica → forma corrente
    plurale: dict[str, dict[str, str]]     # lingua → singolare → plurale
    destinazione: dict[str, dict[str, list[str]]]   # sistema → "peso"/"volume" → unità
    alias_temperatura: dict[str, str]
    arrotondamento_c: int
    densita: dict[str, float]          # chiave normalizzata (nome o alias) → g/ml
    densita_fonte: dict[str, str]      # stessa chiave → nota di provenienza del dato
    liquidi: frozenset[str]            # ingredienti che si misurano a volume, non a peso
    vaghe: dict[str, dict]             # chiave normalizzata → definizione
    indeterminate: frozenset[str]

    def etichetta(self, unita: str | None, valore: float | None,
                  lingua: str = Lingua.IT) -> str | None:
        """Etichetta da mostrare: nella forma corrente della lingua richiesta, al plurale
        se il numero lo richiede. "2 tbsp" diventa "2 cucchiai" in italiano, e "2 cucchiai"
        diventa "2 tbsp" in inglese — la tabella è simmetrica."""
        if not unita:
            return None
        l = sigla(lingua)
        u = self.etichette.get(l, {}).get(unita, unita)
        if valore is not None and abs(valore - 1.0) > 1e-9:
            return self.plurale.get(l, {}).get(u, u)
        return u

    def unita_destinazione(self, sistema: str, dimensione: str) -> list[str]:
        """Le unità in cui esprimere un risultato, dalla più grande alla più piccola."""
        return self.destinazione.get(sigla(sistema), {}).get(dimensione, [])

    def e_gia_nel_sistema(self, unita: str, sistema: str) -> bool:
        """Vero se l'unità è già eseguibile nel sistema di destinazione, e quindi va
        lasciata in pace. "500 ml" per un metrico e "1 cup" per un imperiale sono entrambe
        misure che si eseguono così come sono: convertirle è una perdita netta."""
        if sigla(sistema) == Sistema.METRICO.value:
            return unita in self.volume_metrico or unita == "g"
        return unita in self.volume_imperiale or unita in ("oz", "lb")

    def e_liquido(self, nome_ingrediente: str) -> bool:
        """Vero per gli ingredienti che in cucina si misurano a volume (acqua, latte,
        olio, vino). Per questi convertire in grammi è formalmente corretto ma
        praticamente peggiore: nessuno pesa il latte."""
        trovata = self._voce_densita(nome_ingrediente)
        return trovata is not None and trovata[0] in self.liquidi

    def unita_canonica(self, grezza: str | None) -> str | None:
        """Riporta un'unità alla sua forma canonica passando per gli alias. `None` se
        la stringa non corrisponde a nessuna unità nota."""
        if not grezza:
            return None
        k = _chiave(grezza).rstrip(".")
        if k in self.alias:
            return self.alias[k]
        if k in self.volume or k in self.peso or k in self.conteggio:
            return k
        return None

    def _voce_densita(self, nome_ingrediente: str) -> tuple[str, float, str] | None:
        """Trova la voce di `densita.yaml` che corrisponde a un nome di ingrediente.

        La ricerca è tollerante: prima il nome intero, poi — se non basta — la voce di
        tabella più lunga contenuta nel nome. Così "farina 00 setacciata" trova
        "farina 00", e fra "farina" e "farina integrale" vince la seconda perché più
        specifica. Ritorna `None` se non c'è corrispondenza: in quel caso NON si converte.
        """
        k = _chiave(nome_ingrediente)
        if k in self.densita:
            return k, self.densita[k], self.densita_fonte[k]
        candidati = [voce for voce in self.densita if re.search(rf"\b{re.escape(voce)}\b", k)]
        if not candidati:
            return None
        migliore = max(candidati, key=len)
        return migliore, self.densita[migliore], self.densita_fonte[migliore]

    def densita_per(self, nome_ingrediente: str) -> tuple[float, str] | None:
        """Densità in g/ml e relativa fonte, o `None` se l'ingrediente non è in tabella."""
        trovata = self._voce_densita(nome_ingrediente)
        return (trovata[1], trovata[2]) if trovata else None


def _percorso_dati_predefinito() -> Path:
    """`data/` sta alla radice del repo, due livelli sopra questo file
    (`src/reel2recipe/units.py` → `src/reel2recipe` → `src` → radice)."""
    return Path(__file__).resolve().parents[2] / "data"


@lru_cache(maxsize=4)
def carica_tabelle(cartella: str | None = None) -> Tabelle:
    """Carica e indicizza le tre tabelle. Il risultato è in cache: i file si leggono
    una volta sola per processo."""
    base = Path(cartella) if cartella else _percorso_dati_predefinito()

    def _leggi(nome: str) -> dict:
        percorso = base / nome
        if not percorso.is_file():
            raise FileNotFoundError(
                f"Tabella di conversione mancante: {percorso}. "
                "Senza le tabelle non si converte nulla (e non si inventa nulla)."
            )
        return yaml.safe_load(percorso.read_text(encoding="utf-8")) or {}

    u = _leggi("unita.yaml")
    d = _leggi("densita.yaml")
    v = _leggi("vaghe.yaml")

    alias = {_chiave(k): val for k, val in (u.get("alias") or {}).items()}
    temp = u.get("temperatura") or {}

    # Densità: sia il nome canonico sia ogni alias puntano allo stesso valore.
    densita: dict[str, float] = {}
    densita_fonte: dict[str, str] = {}
    liquidi: set[str] = set()
    for nome, voce in (d.get("ingredienti") or {}).items():
        g_ml = float(voce["g_per_ml"])
        fonte = voce.get("fonte", "")
        for etichetta in [nome, *(voce.get("alias") or [])]:
            k = _chiave(etichetta)
            densita[k] = g_ml
            densita_fonte[k] = fonte
            if voce.get("liquido"):
                liquidi.add(k)

    # Espressioni vaghe: idem, canonico + alias verso la stessa definizione.
    vaghe: dict[str, dict] = {}
    for nome, voce in (v.get("espressioni") or {}).items():
        for etichetta in [nome, *(voce.get("alias") or [])]:
            vaghe[_chiave(etichetta)] = dict(voce)

    per_lingua = lambda sezione: {   # noqa: E731 — due righe, un nome sarebbe rumore
        lingua: {_chiave(k): x for k, x in (voci or {}).items()}
        for lingua, voci in (sezione or {}).items()
    }

    return Tabelle(
        volume={_chiave(k): float(x) for k, x in (u.get("volume") or {}).items()},
        peso={_chiave(k): float(x) for k, x in (u.get("peso") or {}).items()},
        conteggio=frozenset(_chiave(x) for x in (u.get("conteggio") or [])),
        alias=alias,
        misure_a_cucchiaio=frozenset(_chiave(x) for x in (u.get("misure_a_cucchiaio") or [])),
        volume_metrico=frozenset(_chiave(x) for x in (u.get("volume_metrico") or [])),
        volume_imperiale=frozenset(_chiave(x) for x in (u.get("volume_imperiale") or [])),
        etichette=per_lingua(u.get("etichette")),
        plurale=per_lingua(u.get("plurale")),
        destinazione={
            sistema: {dim: [_chiave(x) for x in unita] for dim, unita in (voci or {}).items()}
            for sistema, voci in (u.get("destinazione") or {}).items()
        },
        alias_temperatura={_chiave(k): x for k, x in (temp.get("alias") or {}).items()},
        arrotondamento_c=int(temp.get("arrotondamento_c", 5)),
        densita=densita,
        densita_fonte=densita_fonte,
        liquidi=frozenset(liquidi),
        vaghe=vaghe,
        indeterminate=frozenset(_chiave(x) for x in (v.get("indeterminate") or [])),
    )


# --------------------------------------------------------------------------------------
# Parsing dei numeri
# --------------------------------------------------------------------------------------

_FRAZIONI_UNICODE = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
    "⅙": "1/6", "⅚": "5/6", "⅐": "1/7", "⅛": "1/8",
    "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅑": "1/9", "⅒": "1/10",
}

_NUMERI_A_PAROLE = {
    "un": 1.0, "uno": 1.0, "una": 1.0, "un'": 1.0,
    "due": 2.0, "tre": 3.0, "quattro": 4.0, "cinque": 5.0, "sei": 6.0,
    "sette": 7.0, "otto": 8.0, "nove": 9.0, "dieci": 10.0, "undici": 11.0,
    "dodici": 12.0, "quindici": 15.0, "venti": 20.0,
    "mezzo": 0.5, "mezza": 0.5, "meta": 0.5,
}

_SEPARATORI_INTERVALLO = re.compile(r"\s*(?:-|–|—|\bo\b|\ba\b|÷)\s*")

_RE_MISTO = re.compile(r"^(\d+)\s+(\d+)\s*/\s*(\d+)$")   # "1 1/2"
_RE_FRAZIONE = re.compile(r"^(\d+)\s*/\s*(\d+)$")        # "3/4"
_RE_DECIMALE = re.compile(r"^\d+(?:[.,]\d+)?$")          # "1,5" o "1.5"


def _espandi_frazioni_unicode(testo: str) -> str:
    """"1½" → "1 1/2"; "½" → " 1/2". Lo spazio separatore evita che "1½" diventi "11/2"."""
    for simbolo, ascii_ in _FRAZIONI_UNICODE.items():
        testo = testo.replace(simbolo, f" {ascii_}")
    return testo


def _parse_scalare(testo: str) -> float | None:
    """Un singolo numero: intero, decimale (virgola o punto), frazione, misto, o parola."""
    t = _chiave(testo)
    if not t:
        return None
    if m := _RE_MISTO.match(t):
        intero, num, den = (float(x) for x in m.groups())
        return intero + num / den if den else None
    if m := _RE_FRAZIONE.match(t):
        num, den = (float(x) for x in m.groups())
        return num / den if den else None
    if _RE_DECIMALE.match(t):
        return float(t.replace(",", "."))
    if t in _NUMERI_A_PAROLE:
        return _NUMERI_A_PAROLE[t]
    return None


# Una quantità che si porta dentro la propria unità: almeno una cifra, poi una coda di
# lettere ("80g", "2 tbsp", "1 1/2 cup"). La coda deve essere alfabetica, così "1 1/2" e
# "2-3" non vengono toccati.
_RE_QUANTITA_CON_UNITA = re.compile(r"^(.*\d.*?)\s*([^\W\d_]+\.?)$", re.UNICODE)


def _scorpora_unita(grezza: str | None, tabelle: Tabelle) -> tuple[tuple[float, float], str] | None:
    """Separa l'unità rimasta attaccata alla quantità, se ne riconosce una.

    Ritorna `((minimo, massimo), unita_canonica)` oppure `None` se non c'è niente da
    scorporare. Il numero viene riletto dalla sola parte numerica: `parse_quantita("1 1/2
    cup")` cadrebbe sul suo ultimo tentativo e restituirebbe 1, non 1,5.

    Le misure a occhio non passano di qui: "una tazza" si scorpora in ("una", "tazza"), ma
    "tazza" non è un'unità di `unita.yaml` — sta in `vaghe.yaml` — quindi la funzione si
    tira indietro e la gestisce `_prova_vaghe`, come deve.
    """
    if not grezza:
        return None
    m = _RE_QUANTITA_CON_UNITA.match(_espandi_frazioni_unicode(str(grezza)).strip())
    if not m:
        return None
    unita = tabelle.unita_canonica(m.group(2))
    if unita is None:
        return None
    numero = parse_quantita(m.group(1))
    return (numero, unita) if numero else None


def parse_quantita(grezza: str | None) -> tuple[float, float] | None:
    """Interpreta una quantità grezza come `(minimo, massimo)`.

    Gestisce interi, decimali all'italiana ("1,5"), frazioni ("3/4", "1 1/2"), frazioni
    unicode ("½"), numeri a parole ("due", "mezzo") e intervalli ("2-3", "2 o 3").
    Ritorna `None` se non c'è alcun numero interpretabile — che non è un errore:
    "q.b." e "un pizzico" non sono numeri e vengono trattati altrove.
    """
    if grezza is None:
        return None
    testo = _espandi_frazioni_unicode(str(grezza)).strip()
    if not testo:
        return None

    if diretto := _parse_scalare(testo):
        return (diretto, diretto)

    # Intervallo: si accetta solo se ENTRAMBI gli estremi sono numeri, altrimenti
    # "sale-pepe" o "un a due" verrebbero letti come intervalli inesistenti.
    parti = [p for p in _SEPARATORI_INTERVALLO.split(testo) if p.strip()]
    if len(parti) == 2:
        a, b = _parse_scalare(parti[0]), _parse_scalare(parti[1])
        if a is not None and b is not None:
            return (min(a, b), max(a, b))

    # Una coda alfabetica ("1 1/4 cups", "2/3 lb") non deve far cadere la lettura
    # sull'ultimo tentativo qui sotto: quello vede solo la prima cifra e restituisce 1
    # invece di 1,25, cioè una frazione che sparisce in silenzio. Si rilegge la sola parte
    # numerica, che è esattamente ciò che `_scorpora_unita` sapeva già fare — ma lui viene
    # interpellato solo quando l'unità manca, e questo errore non aspetta quel caso.
    if m := _RE_QUANTITA_CON_UNITA.match(testo):
        if (dalla_testa := parse_quantita(m.group(1))) is not None:
            return dalla_testa

    # Ultimo tentativo: un numero in mezzo ad altro testo ("circa 200"). Qui non si arriva
    # con una coda alfabetica, perché il caso qui sopra l'ha già intercettata.
    if m := re.search(r"\d+(?:[.,]\d+)?", testo):
        valore = float(m.group(0).replace(",", "."))
        return (valore, valore)
    return None


# --------------------------------------------------------------------------------------
# Arrotondamento e formattazione
# --------------------------------------------------------------------------------------


def arrotonda_cucina(valore: float, unita: str | None) -> float:
    """Arrotondamento con la precisione che serve davvero in cucina.

    Una bilancia da cucina legge il grammo, non il milligrammo: mostrare "119,9967 g"
    sarebbe una precisione falsa. Sopra i 100 g si va a scatti di 5, perché nessuno pesa
    237 g di farina. Le temperature seguono gli scatti del forno (5 °C / 25 °F).

    Le unità anglosassoni seguono una logica diversa: non si arrotondano a scatti decimali
    ma a **frazioni**, perché è così che sono fatti i misurini. Un quarto di cup esiste come
    oggetto fisico, 0,23 cup no.
    """
    if unita == "°C":
        return float(round(valore / 5) * 5)
    if unita == "°F":
        return float(round(valore / 25) * 25)
    if unita in ("g", "ml"):
        if valore < 10:
            return round(valore * 2) / 2      # scatti di mezzo grammo
        if valore < 100:
            return float(round(valore))
        return float(round(valore / 5) * 5)
    if unita in ("cup", "tbsp", "tsp"):
        return _arrotonda_a_frazione(valore)
    if unita in ("oz", "lb"):
        return round(valore * 4) / 4          # quarti di oncia
    return round(valore, 2)


# I denominatori che esistono davvero su un misurino: ottavi, terzi, quarti. Un sedicesimo
# di cup non è una misura, è un numero.
_FRAZIONI_UTILI = (1, 2, 3, 4, 8)


def _arrotonda_a_frazione(valore: float) -> float:
    """Al più vicino fra i valori esprimibili con una frazione da cucina.

    Le frazioni ammesse sono quelle che un misurino sa fare: 1/8, 1/4, 1/3, 1/2, 2/3, 3/4.
    Sopra le 3 unità si passa ai mezzi, perché "3 1/8 cup" è una precisione che nessuno
    misura davvero.
    """
    if valore >= 3:
        return round(valore * 2) / 2
    candidati = {
        round(intero + num / den, 6)
        for den in _FRAZIONI_UTILI
        for num in range(den)
        for intero in range(0, 4)
    }
    # Lo zero è escluso di proposito: una quantità che esiste non deve diventare "0 cup"
    # per effetto dell'arrotondamento. Sotto un ottavo si tiene il valore com'è.
    candidati.discard(0.0)
    return min(candidati, key=lambda c: abs(c - valore))


# Frazioni scritte come le scrive un ricettario anglosassone.
_FRAZIONI_TESTO = {
    0.125: "1/8", 0.25: "1/4", 0.333333: "1/3", 0.375: "3/8", 0.5: "1/2",
    0.625: "5/8", 0.666667: "2/3", 0.75: "3/4", 0.875: "7/8",
}


def formatta_numero(valore: float | None, sistema: str = Sistema.METRICO) -> str:
    """Il numero come lo scriverebbe una ricetta, nel sistema richiesto.

    In metrico: decimali con la virgola, senza zeri inutili — "1,5". In imperiale:
    **frazioni**, perché "0,75 cup" non si trova su nessun misurino mentre "3/4 cup" sì,
    e i numeri misti si scrivono come "1 1/2".
    """
    if valore is None:
        return ""
    if abs(valore - round(valore)) < 1e-9:
        return str(int(round(valore)))

    if sigla(sistema) == Sistema.IMPERIALE.value:
        intero = int(valore)
        resto = round(valore - intero, 6)
        for esatto, testo in _FRAZIONI_TESTO.items():
            if abs(resto - esatto) < 0.005:
                return f"{intero} {testo}" if intero else testo
        # Nessuna frazione da cucina ci si avvicina: meglio un decimale onesto che una
        # frazione inventata che poi non si riesce a misurare.
        return f"{valore:.2f}".rstrip("0").rstrip(".")

    return f"{valore:.2f}".rstrip("0").rstrip(".").replace(".", ",")


# --------------------------------------------------------------------------------------
# Normalizzazione di un ingrediente
# --------------------------------------------------------------------------------------

def unita_per_peso(grammi: float, sistema: str) -> tuple[float, str]:
    """Il peso espresso nel sistema richiesto, con l'unità di grandezza giusta.

    Sotto la libbra si usano le once: "7 oz" è una misura che una cucina americana esegue,
    "0,44 lb" no.
    """
    if sigla(sistema) == Sistema.METRICO.value:
        return grammi, "g"
    return (grammi / 453.59237, "lb") if grammi >= 453.59237 else (grammi / 28.349523125, "oz")


def unita_per_volume(ml: float, sistema: str, tabelle: Tabelle) -> tuple[float, str]:
    """Il volume espresso nel sistema richiesto, con l'unità di grandezza giusta.

    La soglia non è arbitraria: si sceglie l'unità più grande che dia ancora un numero
    maneggiabile, come farebbe un ricettario. 5 ml sono un cucchiaino, non due centesimi
    di cup.
    """
    if sigla(sistema) == Sistema.METRICO.value:
        return ml, "ml"
    if ml < tabelle.volume["tbsp"]:
        return ml / tabelle.volume["tsp"], "tsp"
    if ml < tabelle.volume["cup"] / 4:
        return ml / tabelle.volume["tbsp"], "tbsp"
    return ml / tabelle.volume["cup"], "cup"


def _risolvi_unita_contraddittoria(
    quantita_raw: str | None, unita_raw: str | None, nome: str, tabelle: Tabelle, lingua: str,
) -> tuple[str, str, str] | None:
    """La quantità si porta dentro un'unità che contraddice quella isolata dal modello.

    Succede quando il reel scrive la stessa dose in due modi e il modello ne mescola i
    pezzi. Da «1¼ cups (300 ml) water» sono usciti `quantita_raw="1¼ cups"` e
    `unita_raw="ml"`: il numero di una rappresentazione e l'unità dell'altra. Il prodotto
    era "1 ml" d'acqua invece di 300, con provenienza `dichiarato` — cioè un numero
    sbagliato presentato come certo, che è il guasto che questo progetto esiste per evitare.

    **Vince la coppia interna**, perché è l'unica internamente coerente: «1¼» e «cups»
    stanno nello stesso pezzo di testo, il «ml» viene da un'altra parte della frase. Fuori
    da questo caso la politica non cambia: se il modello ha isolato l'unità, la sua resta
    quella buona.

    Ma indovinare non basta. La discrepanza **si dichiara**, perché lì la fonte era ambigua
    e chi cucina deve poterlo sapere: una lacuna dichiarata vale più di un numero silenzioso.

    Ritorna `(quantita_riscritta, unita_riscritta, avviso)`, oppure `None` quando non c'è
    nulla da risolvere — che è il caso di gran lunga più frequente.
    """
    if tabelle.unita_canonica(unita_raw) is None:
        return None      # nessuna unità isolata riconoscibile: se ne occupa il motore
    m = _RE_QUANTITA_CON_UNITA.match(_espandi_frazioni_unicode(str(quantita_raw or "")).strip())
    if not m:
        return None      # la quantità è solo un numero: nessuna contraddizione possibile
    interna = tabelle.unita_canonica(m.group(2))
    if interna is None or interna == tabelle.unita_canonica(unita_raw):
        return None      # o non è un'unità, o le due dicono la stessa cosa
    return m.group(1), m.group(2), messaggio(
        lingua, "unita_contraddittoria",
        nome=nome, dentro=m.group(2), fuori=str(unita_raw).strip(),
    )


def _unita_fra_parentesi(unita_raw: str | None, tabelle: Tabelle) -> str | None:
    """Il contenuto di un'«unità» che è in realtà una parola fra parentesi.

    Da «1 melanzana bianca (facoltativa)» il modello produce `unita_raw="(facoltativa)"`, e
    l'ingrediente veniva reso «1 (facoltativa) melanzana bianca». La regola che degrada una
    non-unità a nota non scattava, perché richiede che manchi il numero — e qui il numero c'è.

    «Nessuna unità si scrive fra parentesi» sembra un criterio sufficiente, e non lo è: il
    modello scrive anche `unita_raw="(g)"`, e `_chiave` toglie già le parentesi, quindi prima
    di questo controllo «200» + «(g)» si convertiva benissimo. Degradarlo a nota lo
    trasformava in un conteggio di duecento farine — un numero sbagliato senza nemmeno una
    lacuna. Quindi si guarda **dentro** le parentesi: se è un'unità nota, non si tocca nulla.
    """
    testo = str(unita_raw or "").strip()
    if len(testo) <= 2 or not (testo.startswith("(") and testo.endswith(")")):
        return None
    dentro = testo[1:-1].strip()
    if not dentro or tabelle.unita_canonica(dentro) is not None:
        return None
    return dentro


_RE_PARENTESI_IN_CODA = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def _misura_in_coda(nome: str, tabelle: Tabelle) -> tuple[str, str] | None:
    """La misura che il modello ha attaccato in fondo al nome invece di metterla nel campo.

    Succede in due forme, viste entrambe su reel veri, e con lo stesso esito: il codice non
    vedeva alcuna indicazione e dichiarava «quantità non indicata nel reel» — una lacuna
    **falsa**, perché il reel aveva indicato eccome. Una lacuna che mente vale meno di
    nessuna lacuna, perché insegna a non fidarsi nemmeno di quelle vere, e su quel meccanismo
    poggia l'onestà di tutto il prodotto.

    1. **Fra parentesi**, qualunque misura a occhio nota: «sale (un pizzico)» diventa una
       stima dichiarata invece di un buco. Le parentesi sono un segnale forte che quel testo
       annota la quantità; un parentetico che non è una misura — «crema di cocco (lattina di
       cocco parte sopra più grassa)» — non compare in `vaghe.yaml` e resta dov'è.
    2. **In chiaro**, solo la famiglia di «q.b.»: «semi di sesamo q.b.». Qui si resta stretti
       di proposito, perché senza parentesi il rischio di rubare una parola al nome è reale.

    Il confronto è **esatto e ancorato in coda**, mai per contenimento: «pomodori poco maturi»
    non deve diventare una quantità indeterminata perché una parola vaga compare nel mezzo. E
    il nome non può essere fatto solo dell'espressione, o resterebbe vuoto.

    Ritorna `(nome_ripulito, misura)` oppure `None`.
    """
    testo = str(nome or "").strip()

    if m := _RE_PARENTESI_IN_CODA.match(testo):
        resto, dentro = m.group(1).strip(), m.group(2).strip()
        # Almeno due parole: «(un pizzico)» è una dose, «(noce)» è la varietà della frutta
        # secca e «(tazza)» il recipiente. Molte voci di `vaghe.yaml` hanno alias di una
        # parola sola — noce, presa, punta, tazza, bicchiere, filo — che fra parentesi dopo
        # un nome quasi sempre lo qualificano invece di dosarlo.
        if resto and len(dentro.split()) >= 2 and _chiave(dentro) in tabelle.vaghe:
            return resto, dentro

    parole = testo.split()
    for n in (3, 2, 1):          # "quanto basta", "a piacere", "q.b."
        if len(parole) <= n:
            continue
        coda = " ".join(parole[-n:])
        chiave = _senza_punti(_chiave(coda))
        for espressione, voce in tabelle.vaghe.items():
            if voce.get("senza_quantita") and _senza_punti(_chiave(espressione)) == chiave:
                return " ".join(parole[:-n]), coda
    return None


def normalizza_ingrediente(
    nome: str,
    quantita_raw: str | None = None,
    unita_raw: str | None = None,
    note: str | None = None,
    gruppo: str | None = None,
    tabelle: Tabelle | None = None,
    sistema: str = Sistema.METRICO,
    lingua: str = Lingua.IT,
) -> Ingrediente:
    """Come `_normalizza_ingrediente`, ma prima rimette in sesto gli ingressi malformati.

    Sta fuori dal motore di conversione e non dentro perché è un problema di **lettura**,
    non di conversione: quando arriva una coppia coerente il motore fa già la cosa giusta.
    Tenerlo qui lascia intatta la parte più delicata del progetto.
    """
    t = tabelle or carica_tabelle()

    # Una parola fra parentesi che NON sia un'unità nota è una nota sull'ingrediente.
    if (fra_parentesi := _unita_fra_parentesi(unita_raw, t)) is not None:
        note, unita_raw = _unisci_note(note, fra_parentesi), ""

    # Una misura finita altrove è comunque un'indicazione, e va letta come tale invece di
    # produrre una lacuna che dice il falso. Solo quando non c'è nessun'altra quantità: se il
    # modello ne ha già isolata una, ciò che sta nel nome o nelle note è un commento.
    #
    # Il modello ha tre modi di sbagliare campo, visti tutti e tre: dentro il nome («semi di
    # sesamo q.b.»), fra parentesi nel nome («sale (un pizzico)») e — quando proprio non sa
    # dove metterlo — nelle note. Il terzo l'ha trovato la suite di regressione, non un reel.
    if not str(quantita_raw or "").strip() and not str(unita_raw or "").strip():
        if spostata := _misura_in_coda(nome, t):
            nome, quantita_raw = spostata
        elif (nota := str(note or "").strip().strip("()").strip()) and _chiave(nota) in t.vaghe:
            quantita_raw, note = nota, None

    avviso: str | None = None
    if riscritta := _risolvi_unita_contraddittoria(quantita_raw, unita_raw, nome, t, lingua):
        quantita_raw, unita_raw, avviso = riscritta

    ingrediente = _normalizza_ingrediente(nome, quantita_raw, unita_raw, note, gruppo,
                                          t, sistema, lingua)
    if not avviso:
        return ingrediente
    # Le lacune non si sostituiscono a vicenda: se il motore ne aveva già una (una densità
    # sconosciuta, per esempio) valgono entrambe. `Ingrediente` è congelato, quindi si
    # ricostruisce invece di modificarlo.
    return replace(
        ingrediente,
        lacuna=f"{avviso}; {ingrediente.lacuna}" if ingrediente.lacuna else avviso,
    )


def _normalizza_ingrediente(
    nome: str,
    quantita_raw: str | None = None,
    unita_raw: str | None = None,
    note: str | None = None,
    gruppo: str | None = None,
    tabelle: Tabelle | None = None,
    sistema: str = Sistema.METRICO,
    lingua: str = Lingua.IT,
) -> Ingrediente:
    """Porta un ingrediente grezzo nel sistema di destinazione, o dichiara perché non è possibile.

    `quantita_raw` e `unita_raw` sono ciò che il reel diceva o scriveva, non toccati
    dall'LLM. Tutta la conversione avviene qui.

    I due assi fanno cose diverse e vanno tenuti distinti. **`sistema` decide i numeri**:
    scegliere metrico o imperiale cambia il valore, quindi va fissato qui, alla conversione.
    **`lingua` decide le parole**: etichette delle unità e messaggi di lacuna.

    Il sistema si applica alla quantità **grezza**, non a valle di una conversione
    intermedia. È la ragione per cui "1 cup di farina" resta "1 cup" per chi cucina in
    imperiale invece di diventare 120 g e poi tornare 0,83 cup: un doppio arrotondamento
    produce numeri che nessun misurino sa fare.
    """
    t = tabelle or carica_tabelle()
    nome = (nome or "").strip()
    originale = " ".join(x for x in (str(quantita_raw or "").strip(), str(unita_raw or "").strip()) if x)

    # 1. Nessuna quantità nel reel.
    if not originale:
        return Ingrediente(
            nome=nome, note=note, gruppo=gruppo,
            quantita=Quantita(None, None, Provenienza.ASSENTE, ""),
            lacuna=messaggio(lingua, "assente", nome=nome),
        )

    # 2. Espressioni che non esprimono una quantità ("q.b.") o la lasciano indeterminata
    #    ("qualche"): non si stima, si conserva la dicitura e si segnala.
    if esito := _prova_indeterminate(nome, originale, quantita_raw, unita_raw, note, gruppo,
                                     t, lingua):
        return esito

    numero = parse_quantita(quantita_raw)
    unita = t.unita_canonica(unita_raw)

    # 2-bis. Il modello non sempre separa numero e unità: capita che `quantita_raw` arrivi
    #    come "80g" o "1 1/2 cup" con `unita_raw` vuoto. Senza questo recupero l'unità
    #    andrebbe persa e il numero finirebbe interpretato come un conteggio di pezzi —
    #    "80g di maiale" diventava "80 maiale". Si recupera solo quando l'unità manca del
    #    tutto: se il modello l'ha isolata, la sua resta quella buona.
    if unita is None and not str(unita_raw or "").strip():
        if (scorporata := _scorpora_unita(quantita_raw, t)) is not None:
            numero, unita = scorporata

    # 3. Misure a occhio con un valore tipico ("un pizzico", "un filo d'olio").
    if esito := _prova_vaghe(nome, originale, numero, unita_raw, quantita_raw, note, gruppo,
                             t, sistema, lingua):
        return esito

    # 4. Unità non riconosciuta.
    if unita is None and unita_raw:
        testo_unita = str(unita_raw).strip()

        # 4a. Senza un numero davanti, una parola non riconosciuta NON è un'unità: è un
        #     attributo dell'ingrediente che il modello ha infilato nel campo sbagliato
        #     ("Dashi in polvere" arriva come nome="Dashi", unita_raw="polvere"). Trattarla
        #     da unità la mette davanti al nome e produce "polvere Dashi". Diventa invece
        #     una nota fra parentesi — che Mela legge come commento — e la quantità resta
        #     onestamente assente.
        if numero is None:
            q = Quantita(None, None, Provenienza.ASSENTE, originale)
            return Ingrediente(
                nome, q, _unisci_note(note, testo_unita), gruppo,
                lacuna=messaggio(lingua, "qualita_non_unita", nome=nome, unita=testo_unita),
            )

        # 4b. C'è un numero: l'unità sconosciuta si conserva intatta accanto ad esso, che è
        #     meglio che forzarla in uno schema che non le appartiene.
        q = Quantita(
            numero[0],
            testo_unita,
            Provenienza.DICHIARATO,
            originale,
            valore_max=numero[1],
        )
        return Ingrediente(nome, q, note, gruppo,
                           lacuna=messaggio(lingua, "unita_ignota", unita=unita_raw, nome=nome))

    # 5. Nessun numero interpretabile.
    if numero is None:
        q = Quantita(None, str(unita_raw or "").strip() or None, Provenienza.ASSENTE, originale)
        return Ingrediente(nome, q, note, gruppo,
                           lacuna=messaggio(lingua, "non_interpretabile", originale=originale, nome=nome))

    minimo, massimo = numero

    # 6. Conteggio di pezzi: non si converte. "2 uova" resta "2 uova"; se `vaghe.yaml`
    #    conosce un peso tipico lo aggiungiamo come commento, senza sostituire il conteggio.
    if unita is None or unita in t.conteggio:
        return _come_conteggio(nome, minimo, massimo, unita, unita_raw, originale, note,
                              gruppo, t, sistema, lingua)

    # 7. Misure a cucchiaio. Non si convertono mai: il cucchiaino ce l'hanno tutti in casa,
    #    la bilancia di precisione no. Si traduce solo l'etichetta ("2 tbsp" → "2 cucchiai")
    #    e si mette l'equivalente fra parentesi, che Mela tratta come commento.
    if unita in t.misure_a_cucchiaio:
        return _come_misura_a_cucchiaio(nome, minimo, massimo, unita, originale, note, gruppo,
                                       t, sistema, lingua)

    # 8. Peso: conversione esatta, nessuna densità in gioco.
    if unita in t.peso:
        grammi_min, grammi_max = minimo * t.peso[unita], massimo * t.peso[unita]
        val_min, u = unita_per_peso(grammi_min, sistema)
        val_max, _ = unita_per_peso(grammi_max, sistema)
        # "Dichiarato" solo se l'unità di partenza è già quella di arrivo: altrimenti c'è
        # stata una conversione, e va detto.
        prov = Provenienza.DICHIARATO if unita == u else Provenienza.CONVERTITO_UNITA
        return _confeziona(nome, val_min, val_max, u, prov, originale, note, gruppo, sistema)

    # 9. Volume.
    if unita in t.volume:
        ml_min, ml_max = minimo * t.volume[unita], massimo * t.volume[unita]

        def come_volume(provenienza: Provenienza) -> Ingrediente:
            val_min, u = unita_per_volume(ml_min, sistema, t)
            val_max, _ = unita_per_volume(ml_max, sistema, t)
            prov = Provenienza.DICHIARATO if unita == u else provenienza
            return _confeziona(nome, val_min, val_max, u, prov, originale, note, gruppo, sistema)

        # 9a. Già eseguibile nel sistema richiesto: "500 ml" per chi cucina in metrico e
        #     "1 cup" per chi cucina in imperiale si usano così come sono. Convertirle
        #     sarebbe una perdita netta.
        if t.e_gia_nel_sistema(unita, sistema):
            return come_volume(Provenienza.CONVERTITO_UNITA)

        # 9b. Liquido: resta un volume, solo espresso nel sistema di destinazione. Nessuna
        #     densità in gioco — nessuno pesa il latte, in nessun paese.
        if t.e_liquido(nome):
            return come_volume(Provenienza.CONVERTITO_UNITA)

        # 9c. Secco con densità nota, e destinazione metrica: è il caso per cui esiste
        #     `densita.yaml`. Verso l'imperiale NON si attraversa la densità: un volume
        #     resta un volume, perché "200 g di farina" reso in cup darebbe 1,67 cup, cioè
        #     un numero che nessun misurino sa fare. La fonte del dato non diventa una nota
        #     per l'utente: è documentazione della tabella, e contiene parentesi che
        #     confonderebbero il parser di Mela.
        if sigla(sistema) == Sistema.METRICO.value and (trovata := t.densita_per(nome)) is not None:
            g_per_ml, _ = trovata
            return _confeziona(nome, ml_min * g_per_ml, ml_max * g_per_ml, "g",
                               Provenienza.CONVERTITO_DENSITA, originale, note, gruppo, sistema)

        # 9d. Densità sconosciuta: si conserva il volume e si dichiara la lacuna. Qui NON
        #     si inventa una densità plausibile.
        ingr = come_volume(Provenienza.CONVERTITO_UNITA)
        if sigla(sistema) == Sistema.METRICO.value:
            return replace(ingr, lacuna=messaggio(lingua, "densita_ignota", nome=nome))
        return ingr

    # Difensivo: un'unità presente negli alias ma in nessuna tabella è un errore di dati.
    q = Quantita(minimo, unita, Provenienza.DICHIARATO, originale, valore_max=massimo)
    return Ingrediente(nome, q, note, gruppo,
                       lacuna=messaggio(lingua, "unita_senza_conversione", unita=unita))


def _unisci_note(*pezzi: str | None) -> str | None:
    presenti = [p.strip() for p in pezzi if p and p.strip()]
    return "; ".join(dict.fromkeys(presenti)) or None


def _confeziona(
    nome: str, valore_min: float, valore_max: float, unita: str, provenienza: Provenienza,
    originale: str, note: str | None, gruppo: str | None,
    sistema: str = Sistema.METRICO, lingua: str = Lingua.IT, tabelle: Tabelle | None = None,
) -> Ingrediente:
    """Arrotonda alla precisione da cucina e costruisce l'ingrediente finale."""
    q = Quantita(
        arrotonda_cucina(valore_min, unita), unita, provenienza, originale,
        valore_max=arrotonda_cucina(valore_max, unita), sistema=sigla(sistema),
    )
    return Ingrediente(nome, q, note, gruppo)


def _come_misura_a_cucchiaio(
    nome: str, minimo: float, massimo: float, unita: str, originale: str,
    note: str | None, gruppo: str | None, tabelle: Tabelle,
    sistema: str = Sistema.METRICO, lingua: str = Lingua.IT,
) -> Ingrediente:
    """Cucchiai e cucchiaini restano tali, con l'equivalente in peso o volume fra parentesi.

    "1 cucchiaino di lievito" è un'istruzione che si esegue; "4 g" richiede una bilancia
    che pochi hanno. Convertirla sarebbe una perdita netta di usabilità. L'unica cosa che
    si tocca è l'etichetta, se arriva in inglese: "2 tbsp" → "2 cucchiai".
    """
    ml_min, ml_max = minimo * tabelle.volume[unita], massimo * tabelle.volume[unita]

    # L'equivalente fra parentesi segue il sistema di destinazione: a un americano "≈ 25 g"
    # non dice nulla, e a un italiano "≈ 0,9 oz" nemmeno.
    if not tabelle.e_liquido(nome) and (trovata := tabelle.densita_per(nome)) is not None:
        g_per_ml, _ = trovata
        eq_min, unita_eq = unita_per_peso(ml_min * g_per_ml, sistema)
        eq_max, _ = unita_per_peso(ml_max * g_per_ml, sistema)
    else:
        eq_min, unita_eq = unita_per_volume(ml_min, sistema, tabelle)
        eq_max, _ = unita_per_volume(ml_max, sistema, tabelle)
    eq_min, eq_max = arrotonda_cucina(eq_min, unita_eq), arrotonda_cucina(eq_max, unita_eq)

    testo_eq = formatta_numero(eq_min, sistema)
    if eq_max != eq_min:
        testo_eq = f"{testo_eq}-{formatta_numero(eq_max, sistema)}"

    # L'equivalente serve solo se aggiunge qualcosa: per chi cucina in imperiale, "2 tbsp
    # (≈ 2 tbsp)" è rumore. Si mostra quando l'unità dell'equivalente è diversa da quella
    # della quantità.
    nota = f"≈ {testo_eq} {unita_eq}" if unita_eq != unita else None

    q = Quantita(
        minimo, tabelle.etichetta(unita, massimo, lingua), Provenienza.DICHIARATO, originale,
        valore_max=massimo, nota=nota, sistema=sigla(sistema),
    )
    return Ingrediente(nome, q, note, gruppo)


def _come_conteggio(
    nome: str, minimo: float, massimo: float, unita: str | None, unita_raw: str | None,
    originale: str, note: str | None, gruppo: str | None, tabelle: Tabelle,
    sistema: str = Sistema.METRICO, lingua: str = Lingua.IT,
) -> Ingrediente:
    """Pezzi contati. Il conteggio resta il dato primario; il peso tipico, se noto,
    diventa un commento fra parentesi."""
    grezza = unita or (str(unita_raw).strip() if unita_raw else None)
    nota = None
    if grezza and (definizione := tabelle.vaghe.get(_chiave(grezza))):
        if (tipico := _valore_vago(definizione, sistema)) is not None:
            quantita_tipica, u = tipico
            totale = arrotonda_cucina(quantita_tipica * massimo, u)
            nota = f"≈ {formatta_numero(totale, sistema)} {u}"
    etichetta = tabelle.etichetta(unita, massimo, lingua) if unita else grezza
    q = Quantita(minimo, etichetta, Provenienza.CONTEGGIO, originale,
                 valore_max=massimo, nota=nota, sistema=sigla(sistema))
    return Ingrediente(nome, q, note, gruppo)


def _valore_vago(definizione: dict, sistema: str) -> tuple[float, str] | None:
    """Il valore tipico di una misura a occhio, nel sistema richiesto.

    Sta in tabella per sistema e non si calcola: un pizzico è 0,5 g in metrico e 1/8 tsp in
    imperiale, e convertire il primo nel secondo darebbe 0,018 oz — un numero che nessuno
    esegue (v. l'intestazione di `vaghe.yaml`).
    """
    valore = definizione.get("valore")
    if not isinstance(valore, dict):
        return None
    per_sistema = valore.get(sigla(sistema)) or valore.get(Sistema.METRICO.value)
    if not isinstance(per_sistema, dict) or per_sistema.get("quantita") is None:
        return None
    return float(per_sistema["quantita"]), per_sistema.get("unita", "g")


def _nota_vaga(definizione: dict, valore: float, unita: str, sistema: str, lingua: str) -> str:
    """La nota che spiega una stima, composta dal valore effettivo.

    Non si scrive in tabella: scritta a mano dipenderebbe dalla lingua mentre il numero
    dipende dal sistema, e le due cose divergono. Componendola qui non può contraddire la
    quantità che accompagna.
    """
    nomi = definizione.get("nome") or {}
    nome_espressione = nomi.get(sigla(lingua)) or nomi.get(Lingua.IT.value) or ""
    return f"{nome_espressione} ≈ {formatta_numero(valore, sistema)} {unita}".strip()


def _prova_indeterminate(
    nome: str, originale: str, quantita_raw: str | None, unita_raw: str | None,
    note: str | None, gruppo: str | None, tabelle: Tabelle, lingua: str = Lingua.IT,
) -> Ingrediente | None:
    """"q.b.", "qualche", "un po'": nessun numero da estrarre, e va detto chiaramente.

    Il match tollera che l'espressione sia annegata in una stringa più lunga: i modelli
    a volte producono unita_raw="burro q.b." invece di isolare il "q.b.". In quel caso il
    nome resta quello del campo `nome` e l'ingrediente diventa "burro q.b.".
    """
    for grezzo in (quantita_raw, unita_raw, originale):
        if not grezzo:
            continue
        k = _chiave(str(grezzo)).rstrip(".")
        parole = set(k.split())
        definizione = tabelle.vaghe.get(k) or tabelle.vaghe.get(_chiave(str(grezzo)))
        # Match esatto, oppure l'espressione compare come token nella stringa
        # ("q.b." dentro "burro q.b."). Il confronto ignora i punti, che rendono
        # "q.b." difficile da tokenizzare in modo affidabile.
        if not definizione:
            k_np = _senza_punti(k)
            for chiave_vaga, voce in tabelle.vaghe.items():
                if voce.get("senza_quantita") and _contiene_espressione(k_np, _senza_punti(chiave_vaga)):
                    definizione = voce
                    break
        if definizione and definizione.get("senza_quantita"):
            # "q.b." in italiano, "to taste" in inglese: la resa sta in tabella per lingua.
            rese = definizione.get("resa") or {}
            resa = rese.get(sigla(lingua)) or rese.get(Lingua.IT.value) or "q.b."
            q = Quantita(None, resa, Provenienza.INDETERMINATO, originale)
            return Ingrediente(nome, q, note, gruppo)
        if k in tabelle.indeterminate or (parole & tabelle.indeterminate):
            q = Quantita(None, str(grezzo).strip(), Provenienza.INDETERMINATO, originale)
            return Ingrediente(
                nome, q, note, gruppo,
                lacuna=messaggio(lingua, "indeterminata", originale=str(grezzo).strip(), nome=nome),
            )
    return None


def _senza_punti(testo: str) -> str:
    """Normalizza via i punti per il confronto delle sigle: "q.b." → "qb"."""
    return re.sub(r"\.", "", testo)


def _contiene_espressione(testo: str, espressione: str) -> bool:
    """Vero se `espressione` (già normalizzata) compare come sequenza di token in `testo`.
    Evita i falsi positivi da sottostringa: "qb" non deve scattare dentro "sqb"."""
    tok_testo = testo.split()
    tok_esp = espressione.split()
    if not tok_esp:
        return False
    for i in range(len(tok_testo) - len(tok_esp) + 1):
        if tok_testo[i:i + len(tok_esp)] == tok_esp:
            return True
    return False


def _prova_vaghe(
    nome: str, originale: str, numero: tuple[float, float] | None, unita_raw: str | None,
    quantita_raw: str | None, note: str | None, gruppo: str | None, tabelle: Tabelle,
    sistema: str = Sistema.METRICO, lingua: str = Lingua.IT,
) -> Ingrediente | None:
    """Misure a occhio con un valore tipico. Il risultato è marcato `stimato:vaghe`
    e porta in nota il perché — non deve mai passare per un dato certo."""
    for grezzo in (unita_raw, quantita_raw, originale):
        if not grezzo:
            continue
        definizione = tabelle.vaghe.get(_chiave(str(grezzo)))

        # Le didascalie scrivono «1 presa di sale», «1 bel pizzico»: un numerale davanti
        # all'espressione. Il match esatto non lo vedeva e l'ingrediente finiva come
        # conteggio — «1 sale», cioè un sale. Si riprova sulla sola coda; il fattore
        # moltiplicativo lo applica già `numero` qui sotto, quindi «2 pizzichi» varrebbe
        # il doppio senza aggiungere altro.
        if not definizione and (m := _RE_QUANTITA_CON_UNITA.match(_chiave(str(grezzo)))):
            definizione = tabelle.vaghe.get(_chiave(m.group(2)))

        if not definizione or definizione.get("senza_quantita"):
            continue

        # Moltiplicatori ("un paio", "una dozzina"): non producono un peso, moltiplicano
        # un conteggio. Se non c'è un'unità da moltiplicare, valgono come pezzi.
        if (moltiplicatore := definizione.get("moltiplicatore")) is not None:
            n = float(moltiplicatore) * (numero[0] if numero else 1.0)
            q = Quantita(n, None, Provenienza.CONTEGGIO, originale)
            return Ingrediente(nome, q, note, gruppo)

        if (tipico := _valore_vago(definizione, sistema)) is None:
            continue
        valore, unita = tipico
        conteggio = numero[1] if numero else 1.0
        conteggio_min = numero[0] if numero else 1.0
        q = Quantita(
            arrotonda_cucina(valore * conteggio_min, unita),
            unita,
            Provenienza.STIMATO_VAGHE,
            originale,
            valore_max=arrotonda_cucina(valore * conteggio, unita),
            nota=_nota_vaga(definizione, valore, unita, sistema, lingua),
            sistema=sigla(sistema),
        )
        return Ingrediente(
            nome, q, note, gruppo,
            lacuna=messaggio(lingua, "stima_vaga", originale=originale, nome=nome),
        )
    return None


# --------------------------------------------------------------------------------------
# Temperature nel testo libero del procedimento
# --------------------------------------------------------------------------------------

_RE_FAHRENHEIT = re.compile(r"(\d{2,3})\s*°?\s*F\b", re.IGNORECASE)
_RE_CELSIUS = re.compile(r"(\d{2,3})\s*°?\s*C\b", re.IGNORECASE)


def fahrenheit_in_celsius(gradi_f: float, arrotondamento: int = 5) -> float:
    celsius = (gradi_f - 32.0) * 5.0 / 9.0
    return float(round(celsius / arrotondamento) * arrotondamento)


def celsius_in_fahrenheit(gradi_c: float, arrotondamento: int = 25) -> float:
    """Verso i Fahrenheit si arrotonda a 25: le manopole dei forni americani sono tarate
    così (325, 350, 375), e un "347 °F" non corrisponderebbe a nessuna posizione."""
    fahrenheit = gradi_c * 9.0 / 5.0 + 32.0
    return float(round(fahrenheit / arrotondamento) * arrotondamento)


def converti_temperature_nel_testo(
    testo: str, tabelle: Tabelle | None = None, sistema: str = Sistema.METRICO,
) -> tuple[str, list[str]]:
    """Porta le temperature nella scala del sistema di destinazione.

    Un reel anglosassone dice "bake at 350°F" e un forno italiano non ha quella scala; uno
    italiano dice "180 °C" e un forno americano nemmeno. La conversione va quindi nei due
    sensi, secondo chi legge.

    Ritorna il testo convertito e l'elenco delle sostituzioni fatte, perché ogni modifica al
    testo dell'autore va tracciata e non applicata di nascosto.
    """
    t = tabelle or carica_tabelle()
    sostituzioni: list[str] = []
    verso_metrico = sigla(sistema) == Sistema.METRICO.value

    def _sostituisci(m: re.Match[str]) -> str:
        gradi = float(m.group(1))
        # Sotto una certa soglia non è quasi mai una temperatura di cottura ("cuoci 20
        # minuti a fuoco medio" contiene numeri che non sono gradi): meglio non toccare.
        if verso_metrico and gradi < 100:
            return m.group(0)
        if not verso_metrico and gradi < 40:
            return m.group(0)

        if verso_metrico:
            convertita, unita = fahrenheit_in_celsius(gradi, t.arrotondamento_c), "°C"
        else:
            convertita, unita = celsius_in_fahrenheit(gradi), "°F"
        reso = f"{formatta_numero(convertita)} {unita}"
        sostituzioni.append(f"{m.group(0).strip()} → {reso}")
        return reso

    espressione = _RE_FAHRENHEIT if verso_metrico else _RE_CELSIUS
    return espressione.sub(_sostituisci, testo), sostituzioni
