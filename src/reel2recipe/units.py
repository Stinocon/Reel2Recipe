"""units.py — deterministic normalisation of quantities. The qualitative heart of the project.

PRINCIPLE: the LLM extracts, the code converts.

Ask a language model "how many grams is 1 cup of flour?" and it produces a plausible number.
Sometimes 120, sometimes 128, sometimes 150, and for sugar it may well repeat the same number
it gave for flour — which is wrong by 67%. The model is not calculating, it is misremembering.

Here nothing is guessed: quantities arrive raw from `extract.py` (`quantita_raw`, `unita_raw`,
exactly as spoken or written in the reel) and are converted with the versioned tables in
`data/`. When a conversion is not possible — typically a volume of an ingredient whose density
we do not know — **nothing is invented**: the original unit is kept and the gap is declared.

Every quantity produced carries its own `provenance`, so the interface can tell at a glance a
figure declared by the reel from an estimate of ours.

There are three tables, in `data/`:
  - `unita.yaml`    exact conversions between units (cup→ml, oz→g, °F→°C), labels per language
  - `densita.yaml`  density per ingredient, for the volume→weight step
  - `vaghe.yaml`    eyeball measures (q.b., un pizzico, a pinch, a drizzle)

TWO AXES, NOT ONE: `system` and `language`.

`system` (metric/imperial) decides **the numbers**, so it is settled here, at the conversion.
`language` (it/en) decides **the words**: unit labels and gap messages. They do not coincide —
an Australian reads in English and cooks in grams — and keeping them apart is the only way to
serve both.

The system applies to the **raw** quantity, not downstream of an intermediate conversion.
"1 cup of flour" stays "1 cup" for someone cooking in imperial rather than becoming 120 g and
then coming back as 0.83 cup: a double rounding produces numbers no measuring cup can make.
For the same reason, nothing crosses density on the way to imperial: a volume stays a volume,
a weight stays a weight.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

# --------------------------------------------------------------------------------------
# Provenance of a quantity: where the number we show comes from.
# --------------------------------------------------------------------------------------


class Language(str, Enum):
    """The language of labels and messages. Decides *how a quantity is written*."""

    IT = "it"
    EN = "en"


class System(str, Enum):
    """The target system of measurement. Decides *what a quantity is worth*.

    The difference from `Language` is not pedantry: an Australian reads in English and cooks
    in grams, and an Italian may want a recipe in cups in order to follow an American video.
    There are two axes because in reality they do not coincide.
    """

    METRIC = "metrico"
    IMPERIAL = "imperiale"


# Messages addressed to whoever is cooking. They live here and not in the `data/` tables
# because they are program strings, not conversion data: they change with the code that
# produces them.
MESSAGES: dict[str, dict[str, str]] = {
    "it": {
        "absent": "quantità non indicata nel reel per «{name}»",
        "unreadable": "quantità «{original}» non interpretabile per «{name}»",
        "unknown_unit": "unità «{unit}» non riconosciuta per «{name}»: lasciata invariata",
        "quality_not_unit": ("quantità non indicata nel reel per «{name}» («{unit}» è una "
                             "qualità dell'ingrediente, non un'unità)"),
        "indeterminate": "quantità indeterminata («{original}») per «{name}»",
        "unknown_density": ("densità sconosciuta per «{name}»: quantità lasciata in volume, "
                            "non convertita in peso"),
        "vague_estimate": "«{original}» è una misura a occhio: il valore per «{name}» è una stima",
        "unit_without_conversion": "unità «{unit}» priva di conversione nelle tabelle",
        "contradictory_unit": ("per «{name}» la quantità diceva «{inside}» ma l'unità diceva "
                               "«{outside}»: si è usata «{inside}», che sta insieme al suo "
                               "numero — verifica sulla fonte"),
    },
    "en": {
        "absent": "no quantity given in the reel for «{name}»",
        "unreadable": "quantity «{original}» could not be read for «{name}»",
        "unknown_unit": "unit «{unit}» not recognised for «{name}»: left as it was",
        "quality_not_unit": ("no quantity given in the reel for «{name}» («{unit}» describes "
                             "the ingredient, it is not a unit)"),
        "indeterminate": "open-ended quantity («{original}») for «{name}»",
        "unknown_density": ("density unknown for «{name}»: kept as a volume, not converted "
                            "to weight"),
        "vague_estimate": "«{original}» is an eyeball measure: the value for «{name}» is an estimate",
        "unit_without_conversion": "unit «{unit}» has no conversion in the tables",
        "contradictory_unit": ("for «{name}» the amount said «{inside}» but the unit said "
                               "«{outside}»: «{inside}» was used, as it belongs with its own "
                               "number — check against the source"),
    },
}


def code_of(value) -> str:
    """The textual value of an enum, or the string as it is.

    Needed because `str()` on an enum that inherits from `str` does NOT give the value but
    the qualified name: `str(System.IMPERIAL)` is "System.IMPERIAL", not "imperiale". It is a
    classic trip-up, and here it cost dearly: the comparison always failed silently and the
    imperial branch was never taken.
    """
    return value.value if isinstance(value, Enum) else str(value)


Catalogue = dict[str, dict[str, str]]   # language → key → text


def text_from(catalogue: Catalogue, language: str, key: str, **data) -> str:
    """A string from a per-language catalogue, falling back to Italian.

    It lives here, and not next to each catalogue, because there are quite a few catalogues by
    now — the conversion messages just above, the export headings in `mela.py` and
    `documents.py`, the temperature notes in `recipe.py`, the progress lines in `pipeline.py` —
    and the function to read them had already been copied out three times identically.

    The fallback has two levels and the two serve different purposes: an unforeseen **language**
    must not make the message disappear, and neither must a half-translated **key**. Better an
    Italian sentence inside English output than a `KeyError` halfway through an export, or a
    hole where a declared gap should have been.
    """
    per_language = catalogue.get(code_of(language), catalogue["it"])
    return per_language.get(key, catalogue["it"][key]).format(**data)


def message(language: str, key: str, **data) -> str:
    """A conversion message in the requested language."""
    return text_from(MESSAGES, language, key, **data)


class Provenance(str, Enum):
    ABSENT = "assente"                        # the reel gave no quantity at all
    DECLARED = "dichiarato"                   # already in the right unit, no conversion
    CONVERTED_UNIT = "convertito:unita"       # exact conversion (oz→g, cup→ml, °F→°C)
    CONVERTED_DENSITY = "convertito:densita"  # volume→weight via densita.yaml
    COUNT = "conteggio"                       # counted pieces: 2 eggs, 3 cloves
    ESTIMATED_VAGUE = "stimato:vaghe"         # estimate from vaghe.yaml — declared as such
    INDETERMINATE = "indeterminato"           # "q.b.", "qualche": quantity not expressible


# Provenances the interface must highlight, because they are not certain data.
UNCERTAIN_PROVENANCES = frozenset(
    {Provenance.ESTIMATED_VAGUE, Provenance.INDETERMINATE, Provenance.ABSENT}
)


# --------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Quantity:
    """A normalised quantity. `value_max` is filled in only for ranges ("2-3 tablespoons"),
    where keeping both ends is more honest than picking one."""

    value: float | None
    unit: str | None
    provenance: Provenance
    original_text: str
    value_max: float | None = None
    note: str | None = None
    # The system the quantity is expressed in. It serves the rendering, not the value: it
    # decides whether 0.75 is written "0,75" or "3/4", and only the reader sees that difference.
    system: str = System.METRIC.value

    @property
    def is_range(self) -> bool:
        return self.value_max is not None and self.value_max != self.value

    def text(self) -> str:
        """Textual rendering of the quantity alone, e.g. "200 g", "2-3 cucchiai", "3/4 cup"."""
        if self.value is None:
            return self.unit or ""
        num = format_number(self.value, self.system)
        if self.is_range:
            num = f"{num}-{format_number(self.value_max, self.system)}"
        return f"{num} {self.unit}".strip() if self.unit else num


@dataclass(frozen=True)
class Ingredient:
    """A normalised ingredient, ready for export."""

    name: str
    quantity: Quantity
    notes: str | None = None
    group: str | None = None
    gap: str | None = None

    def mela_line(self) -> str:
        """A line in the format Mela's parser can read.

        Mela natively recognises quantities and units in Italian, so the right shape is the
        plain string "200 g farina 00" — not a structure of ours. Text in brackets is treated
        by Mela as a comment: that is where we put the equivalent in grams when we keep the
        original unit, and the ingredient's own notes.
        """
        comments = [c for c in (self.quantity.note, self.notes) if c]
        tail = f" ({'; '.join(comments)})" if comments else ""

        if self.quantity.provenance is Provenance.INDETERMINATE:
            # Italian convention: "q.b." follows the name ("sale q.b."), it does not precede it.
            marker = self.quantity.unit or "q.b."
            return f"{self.name} {marker}{tail}".strip()

        # Models sometimes repeat the counting unit inside the name ("2 uova" with name
        # "uova"): "2 uova uova" is both ugly and wrong. If the unit is already in the name,
        # only the number is kept.
        quantity_text = self.quantity.text()
        if self.quantity.unit and _repeated_in_name(self.quantity.unit, self.name):
            quantity_text = format_number(self.quantity.value)
            if self.quantity.is_range:
                quantity_text = f"{quantity_text}-{format_number(self.quantity.value_max)}"

        if not quantity_text:
            return f"{self.name}{tail}".strip()
        return f"{quantity_text} {self.name}{tail}".strip()


# --------------------------------------------------------------------------------------
# Loading the tables
# --------------------------------------------------------------------------------------


def _singular_plural(word: str) -> set[str]:
    """Trivial Italian singular/plural variants, for tolerant comparisons ("uovo"/"uova",
    "spicchio"/"spicchi"). Not full morphology, only the frequent cases."""
    forms = {word}
    if word.endswith(("a", "o", "e")):
        forms.add(word[:-1] + "i")
        forms.add(word[:-1] + "e")
    if word.endswith("i"):
        forms.update({word[:-1] + "o", word[:-1] + "a", word[:-1] + "e"})
    return forms


def _repeated_in_name(unit: str, name: str) -> bool:
    """True if the unit label coincides with a word of the ingredient name (up to
    singular/plural). It is what stops us writing "2 uova uova"."""
    name_words = set(_key(name).split())
    for form in _singular_plural(_key(unit)):
        if form in name_words:
            return True
    return False


def _key(text: str) -> str:
    """Comparison key: lower case, no accents, no marginal punctuation, normalised spaces.
    It is what makes "Farina 00", "farina 00 " and "FARINA 00" match."""
    text = unicodedata.normalize("NFD", text.strip().lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Typographic apostrophes (U+2019, U+2018) to the ASCII one. A line with this intent was
    # already here, but it put the ASCII apostrophe in place of itself: it did nothing, and on
    # a re-read it looked fine. It cost dearly, because the curly apostrophe is what iOS
    # keyboards and Instagram captions write by default. With that one, the `vaghe.yaml` entry
    # "bicchiere d'acqua" was no longer found: instead of "200 ml acqua" declared as an
    # estimate, out came "1 bicchiere d'acqua acqua" with provenance `dichiarato` — a
    # meaningless line presented as certain data.
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^\w\s'°/.-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Tables:
    volume: dict[str, float]
    weight: dict[str, float]
    count: frozenset[str]
    aliases: dict[str, str]
    spoon_measures: frozenset[str]
    metric_volume: frozenset[str]
    imperial_volume: frozenset[str]
    labels: dict[str, dict[str, str]]   # language → canonical unit → current form
    plural: dict[str, dict[str, str]]   # language → singular → plural
    temperature_aliases: dict[str, str]
    rounding_c: int
    density: dict[str, float]          # normalised key (name or alias) → g/ml
    density_source: dict[str, str]     # same key → provenance note for the datum
    liquids: frozenset[str]            # ingredients measured by volume, not by weight
    vague: dict[str, dict]             # normalised key → definition
    indeterminate: frozenset[str]

    def label(self, unit: str | None, value: float | None,
              language: str = Language.IT) -> str | None:
        """The label to show: in the current form of the requested language, plural if the
        number calls for it. "2 tbsp" becomes "2 cucchiai" in Italian, and "2 cucchiai"
        becomes "2 tbsp" in English — the table is symmetric."""
        if not unit:
            return None
        l = code_of(language)
        u = self.labels.get(l, {}).get(unit, unit)
        if value is not None and abs(value - 1.0) > 1e-9:
            return self.plural.get(l, {}).get(u, u)
        return u

    def is_already_in_system(self, unit: str, system: str) -> bool:
        """True if the unit can already be executed in the target system, and is therefore to
        be left alone. "500 ml" for a metric cook and "1 cup" for an imperial one are both
        measures you carry out exactly as they are: converting them is a net loss."""
        if code_of(system) == System.METRIC.value:
            return unit in self.metric_volume or unit == "g"
        return unit in self.imperial_volume or unit in ("oz", "lb")

    def is_liquid(self, ingredient_name: str) -> bool:
        """True for ingredients that in a kitchen are measured by volume (water, milk, oil,
        wine). For these, converting to grams is formally correct but practically worse:
        nobody weighs milk."""
        found = self._density_entry(ingredient_name)
        return found is not None and found[0] in self.liquids

    def canonical_unit(self, raw: str | None) -> str | None:
        """Brings a unit back to its canonical form by way of the aliases. `None` if the
        string matches no known unit."""
        if not raw:
            return None
        k = _key(raw).rstrip(".")
        if k in self.aliases:
            return self.aliases[k]
        if k in self.volume or k in self.weight or k in self.count:
            return k
        return None

    def _density_entry(self, ingredient_name: str) -> tuple[str, float, str] | None:
        """Finds the `densita.yaml` entry matching an ingredient name.

        The search is tolerant: first the whole name, then — if that is not enough — the
        longest table entry contained in the name. That way "farina 00 setacciata" finds
        "farina 00", and between "farina" and "farina integrale" the second wins because it is
        more specific. Returns `None` when there is no match: in that case we do NOT convert.
        """
        k = _key(ingredient_name)
        if k in self.density:
            return k, self.density[k], self.density_source[k]
        candidates = [entry for entry in self.density if re.search(rf"\b{re.escape(entry)}\b", k)]
        if not candidates:
            return None
        best = max(candidates, key=len)
        return best, self.density[best], self.density_source[best]

    def density_for(self, ingredient_name: str) -> tuple[float, str] | None:
        """Density in g/ml and its source, or `None` if the ingredient is not in the table."""
        found = self._density_entry(ingredient_name)
        return (found[1], found[2]) if found else None


def _default_data_path() -> Path:
    """`data/` sits at the root of the repo, two levels above this file
    (`src/reel2recipe/units.py` → `src/reel2recipe` → `src` → root)."""
    return Path(__file__).resolve().parents[2] / "data"


@lru_cache(maxsize=4)
def load_tables(folder: str | None = None) -> Tables:
    """Loads and indexes the three tables. The result is cached: the files are read once per
    process."""
    base = Path(folder) if folder else _default_data_path()

    def _read(name: str) -> dict:
        path = base / name
        if not path.is_file():
            raise FileNotFoundError(
                f"Conversion table missing: {path}. "
                "Without the tables nothing is converted (and nothing is invented)."
            )
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    u = _read("unita.yaml")
    d = _read("densita.yaml")
    v = _read("vaghe.yaml")

    aliases = {_key(k): val for k, val in (u.get("alias") or {}).items()}
    temp = u.get("temperature") or {}

    # Density: both the canonical name and every alias point at the same value.
    density: dict[str, float] = {}
    density_source: dict[str, str] = {}
    liquids: set[str] = set()
    for name, entry in (d.get("ingredients") or {}).items():
        g_ml = float(entry["g_per_ml"])
        source = entry.get("source", "")
        for label in [name, *(entry.get("alias") or [])]:
            k = _key(label)
            density[k] = g_ml
            density_source[k] = source
            if entry.get("liquid"):
                liquids.add(k)

    # Vague expressions: same again, canonical + aliases towards the same definition.
    vague: dict[str, dict] = {}
    for name, entry in (v.get("expressions") or {}).items():
        for label in [name, *(entry.get("alias") or [])]:
            vague[_key(label)] = dict(entry)

    per_language = lambda section: {   # noqa: E731 — two lines, a name would be noise
        language: {_key(k): x for k, x in (entries or {}).items()}
        for language, entries in (section or {}).items()
    }

    return Tables(
        volume={_key(k): float(x) for k, x in (u.get("volume") or {}).items()},
        weight={_key(k): float(x) for k, x in (u.get("weight") or {}).items()},
        count=frozenset(_key(x) for x in (u.get("count") or [])),
        aliases=aliases,
        spoon_measures=frozenset(_key(x) for x in (u.get("spoon_measures") or [])),
        metric_volume=frozenset(_key(x) for x in (u.get("metric_volume") or [])),
        imperial_volume=frozenset(_key(x) for x in (u.get("imperial_volume") or [])),
        labels=per_language(u.get("labels")),
        plural=per_language(u.get("plural")),
        temperature_aliases={_key(k): x for k, x in (temp.get("alias") or {}).items()},
        rounding_c=int(temp.get("rounding_c", 5)),
        density=density,
        density_source=density_source,
        liquids=frozenset(liquids),
        vague=vague,
        indeterminate=frozenset(_key(x) for x in (v.get("indeterminate") or [])),
    )


# --------------------------------------------------------------------------------------
# Parsing numbers
# --------------------------------------------------------------------------------------

_UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
    "⅙": "1/6", "⅚": "5/6", "⅐": "1/7", "⅛": "1/8",
    "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅑": "1/9", "⅒": "1/10",
}

_NUMBER_WORDS = {
    "un": 1.0, "uno": 1.0, "una": 1.0, "un'": 1.0,
    "due": 2.0, "tre": 3.0, "quattro": 4.0, "cinque": 5.0, "sei": 6.0,
    "sette": 7.0, "otto": 8.0, "nove": 9.0, "dieci": 10.0, "undici": 11.0,
    "dodici": 12.0, "quindici": 15.0, "venti": 20.0,
    "mezzo": 0.5, "mezza": 0.5, "meta": 0.5,
}

_RANGE_SEPARATORS = re.compile(r"\s*(?:-|–|—|\bo\b|\ba\b|÷)\s*")

_RE_MIXED = re.compile(r"^(\d+)\s+(\d+)\s*/\s*(\d+)$")   # "1 1/2"
_RE_FRACTION = re.compile(r"^(\d+)\s*/\s*(\d+)$")        # "3/4"
_RE_DECIMAL = re.compile(r"^\d+(?:[.,]\d+)?$")           # "1,5" or "1.5"


def _expand_unicode_fractions(text: str) -> str:
    """"1½" → "1 1/2"; "½" → " 1/2". The separating space stops "1½" becoming "11/2"."""
    for symbol, ascii_ in _UNICODE_FRACTIONS.items():
        text = text.replace(symbol, f" {ascii_}")
    return text


def _parse_scalar(text: str) -> float | None:
    """A single number: integer, decimal (comma or point), fraction, mixed, or word."""
    t = _key(text)
    if not t:
        return None
    if m := _RE_MIXED.match(t):
        whole, num, den = (float(x) for x in m.groups())
        return whole + num / den if den else None
    if m := _RE_FRACTION.match(t):
        num, den = (float(x) for x in m.groups())
        return num / den if den else None
    if _RE_DECIMAL.match(t):
        return float(t.replace(",", "."))
    if t in _NUMBER_WORDS:
        return _NUMBER_WORDS[t]
    return None


# A quantity carrying its own unit inside it: at least one digit, then a tail of letters
# ("80g", "2 tbsp", "1 1/2 cup"). The tail has to be alphabetic, so that "1 1/2" and "2-3"
# are left alone.
_RE_QUANTITY_WITH_UNIT = re.compile(r"^(.*\d.*?)\s*([^\W\d_]+\.?)$", re.UNICODE)


def _split_off_unit(raw: str | None, tables: Tables) -> tuple[tuple[float, float], str] | None:
    """Separates the unit left stuck to the quantity, when it recognises one.

    Returns `((minimum, maximum), canonical_unit)` or `None` if there is nothing to split off.
    The number is re-read from the numeric part alone: `parse_quantity("1 1/2 cup")` would fall
    through to its last attempt and return 1, not 1.5.

    Eyeball measures do not come through here: "una tazza" splits into ("una", "tazza"), but
    "tazza" is not a unit of `unita.yaml` — it lives in `vaghe.yaml` — so this function backs
    off and `_try_vague` handles it, as it should.
    """
    if not raw:
        return None
    m = _RE_QUANTITY_WITH_UNIT.match(_expand_unicode_fractions(str(raw)).strip())
    if not m:
        return None
    unit = tables.canonical_unit(m.group(2))
    if unit is None:
        return None
    number = parse_quantity(m.group(1))
    return (number, unit) if number else None


def parse_quantity(raw: str | None) -> tuple[float, float] | None:
    """Reads a raw quantity as `(minimum, maximum)`.

    Handles integers, Italian-style decimals ("1,5"), fractions ("3/4", "1 1/2"), unicode
    fractions ("½"), numbers as words ("due", "mezzo") and ranges ("2-3", "2 o 3"). Returns
    `None` when there is no readable number — which is not an error: "q.b." and "un pizzico"
    are not numbers and are dealt with elsewhere.
    """
    if raw is None:
        return None
    text = _expand_unicode_fractions(str(raw)).strip()
    if not text:
        return None

    if direct := _parse_scalar(text):
        return (direct, direct)

    # Range: accepted only if BOTH ends are numbers, otherwise "sale-pepe" or "un a due"
    # would be read as ranges that do not exist.
    parts = [p for p in _RANGE_SEPARATORS.split(text) if p.strip()]
    if len(parts) == 2:
        a, b = _parse_scalar(parts[0]), _parse_scalar(parts[1])
        if a is not None and b is not None:
            return (min(a, b), max(a, b))

    # An alphabetic tail ("1 1/4 cups", "2/3 lb") must not make the reading fall through to
    # the last attempt below: that one sees only the first digit and returns 1 instead of
    # 1.25, i.e. a fraction that vanishes silently. The numeric part alone is re-read, which
    # is exactly what `_split_off_unit` already knew how to do — but it is only consulted when
    # the unit is missing, and this error does not wait for that case.
    if m := _RE_QUANTITY_WITH_UNIT.match(text):
        if (from_the_head := parse_quantity(m.group(1))) is not None:
            return from_the_head

    # Last attempt: a number in the middle of other text ("circa 200"). We do not arrive here
    # with an alphabetic tail, because the case just above has already caught it.
    if m := re.search(r"\d+(?:[.,]\d+)?", text):
        value = float(m.group(0).replace(",", "."))
        return (value, value)
    return None


# --------------------------------------------------------------------------------------
# Rounding and formatting
# --------------------------------------------------------------------------------------


def round_for_kitchen(value: float, unit: str | None) -> float:
    """Rounding at the precision that actually matters in a kitchen.

    A kitchen scale reads grams, not milligrams: showing "119,9967 g" would be false
    precision. Above 100 g it goes in steps of 5, because nobody weighs 237 g of flour.
    Temperatures follow the oven's steps (5 °C / 25 °F).

    Anglo-Saxon units follow a different logic: they are not rounded to decimal steps but to
    **fractions**, because that is how measuring cups are made. A quarter cup exists as a
    physical object; 0.23 cup does not.
    """
    if unit == "°C":
        return float(round(value / 5) * 5)
    if unit == "°F":
        return float(round(value / 25) * 25)
    if unit in ("g", "ml"):
        if value < 10:
            return round(value * 2) / 2      # half-gram steps
        if value < 100:
            return float(round(value))
        return float(round(value / 5) * 5)
    if unit in ("cup", "tbsp", "tsp"):
        return _round_to_fraction(value)
    if unit in ("oz", "lb"):
        return round(value * 4) / 4          # quarter ounces
    return round(value, 2)


# The denominators that really exist on a measuring cup: eighths, thirds, quarters. A
# sixteenth of a cup is not a measure, it is a number.
_USEFUL_FRACTIONS = (1, 2, 3, 4, 8)


def _round_to_fraction(value: float) -> float:
    """To the nearest of the values expressible as a kitchen fraction.

    The fractions allowed are the ones a measuring cup can make: 1/8, 1/4, 1/3, 1/2, 2/3, 3/4.
    Above 3 units it moves to halves, because "3 1/8 cup" is a precision nobody actually
    measures.
    """
    if value >= 3:
        return round(value * 2) / 2
    candidates = {
        round(whole + num / den, 6)
        for den in _USEFUL_FRACTIONS
        for num in range(den)
        for whole in range(0, 4)
    }
    # Zero is excluded on purpose: a quantity that exists must not become "0 cup" as an effect
    # of the rounding. Below an eighth the value is kept as it is.
    candidates.discard(0.0)
    return min(candidates, key=lambda c: abs(c - value))


# Fractions written the way an Anglo-Saxon recipe book writes them.
_FRACTIONS_AS_TEXT = {
    0.125: "1/8", 0.25: "1/4", 0.333333: "1/3", 0.375: "3/8", 0.5: "1/2",
    0.625: "5/8", 0.666667: "2/3", 0.75: "3/4", 0.875: "7/8",
}


def format_number(value: float | None, system: str = System.METRIC) -> str:
    """The number as a recipe would write it, in the requested system.

    In metric: decimals with a comma, without pointless zeros — "1,5". In imperial:
    **fractions**, because "0,75 cup" is on no measuring cup while "3/4 cup" is, and mixed
    numbers are written as "1 1/2".
    """
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))

    if code_of(system) == System.IMPERIAL.value:
        whole = int(value)
        remainder = round(value - whole, 6)
        for exact, text in _FRACTIONS_AS_TEXT.items():
            if abs(remainder - exact) < 0.005:
                return f"{whole} {text}" if whole else text
        # No kitchen fraction comes close: better an honest decimal than an invented fraction
        # that then cannot be measured.
        return f"{value:.2f}".rstrip("0").rstrip(".")

    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


# --------------------------------------------------------------------------------------
# Normalising an ingredient
# --------------------------------------------------------------------------------------

def unit_for_weight(grams: float, system: str) -> tuple[float, str]:
    """The weight expressed in the requested system, at the right order of magnitude.

    Below the pound it uses ounces: "7 oz" is a measure an American kitchen carries out,
    "0,44 lb" is not.
    """
    if code_of(system) == System.METRIC.value:
        return grams, "g"
    return (grams / 453.59237, "lb") if grams >= 453.59237 else (grams / 28.349523125, "oz")


def unit_for_volume(ml: float, system: str, tables: Tables) -> tuple[float, str]:
    """The volume expressed in the requested system, at the right order of magnitude.

    The threshold is not arbitrary: it picks the largest unit that still gives a manageable
    number, as a recipe book would. 5 ml is a teaspoon, not two hundredths of a cup.
    """
    if code_of(system) == System.METRIC.value:
        return ml, "ml"
    if ml < tables.volume["tbsp"]:
        return ml / tables.volume["tsp"], "tsp"
    if ml < tables.volume["cup"] / 4:
        return ml / tables.volume["tbsp"], "tbsp"
    return ml / tables.volume["cup"], "cup"


def _resolve_contradictory_unit(
    quantity_raw: str | None, unit_raw: str | None, name: str, tables: Tables, language: str,
) -> tuple[str, str, str] | None:
    """The quantity carries a unit inside it that contradicts the one the model isolated.

    This happens when the reel writes the same dose two ways and the model mixes their pieces.
    Out of «1¼ cups (300 ml) water» came `quantita_raw="1¼ cups"` and `unita_raw="ml"`: the
    number of one representation and the unit of the other. The product was "1 ml" of water
    instead of 300, with provenance `dichiarato` — that is, a wrong number presented as
    certain, which is the failure this project exists to prevent.

    **The internal pair wins**, because it is the only one internally coherent: «1¼» and
    «cups» sit in the same piece of text, the «ml» comes from elsewhere in the sentence.
    Outside this case the policy does not change: if the model isolated the unit, its one is
    the good one.

    But guessing is not enough. The discrepancy **is declared**, because the source was
    ambiguous right there and whoever is cooking has to be able to know it: a declared gap is
    worth more than a silent number.

    Returns `(rewritten_quantity, rewritten_unit, warning)`, or `None` when there is nothing
    to resolve — which is by far the most frequent case.
    """
    if tables.canonical_unit(unit_raw) is None:
        return None      # no recognisable isolated unit: the engine deals with it
    m = _RE_QUANTITY_WITH_UNIT.match(_expand_unicode_fractions(str(quantity_raw or "")).strip())
    if not m:
        return None      # the quantity is only a number: no contradiction possible
    inner = tables.canonical_unit(m.group(2))
    if inner is None or inner == tables.canonical_unit(unit_raw):
        return None      # either it is not a unit, or the two say the same thing
    return m.group(1), m.group(2), message(
        language, "contradictory_unit",
        name=name, inside=m.group(2), outside=str(unit_raw).strip(),
    )


def _unit_in_brackets(unit_raw: str | None, tables: Tables) -> str | None:
    """The content of a "unit" that is in fact a word in brackets.

    Out of «1 melanzana bianca (facoltativa)» the model produces `unita_raw="(facoltativa)"`,
    and the ingredient came out as «1 (facoltativa) melanzana bianca». The rule that demotes a
    non-unit to a note did not fire, because it requires the number to be missing — and here
    the number is there.

    "No unit is written in brackets" looks like a sufficient criterion, and it is not: the
    model also writes `unita_raw="(g)"`, and `_key` already strips brackets, so before this
    check «200» + «(g)» converted perfectly well. Demoting it to a note turned it into a count
    of two hundred flours — a wrong number without even a gap. So we look **inside** the
    brackets: if it is a known unit, nothing is touched.
    """
    text = str(unit_raw or "").strip()
    if len(text) <= 2 or not (text.startswith("(") and text.endswith(")")):
        return None
    inside = text[1:-1].strip()
    if not inside or tables.canonical_unit(inside) is not None:
        return None
    return inside


_RE_TRAILING_BRACKETS = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def _trailing_measure(name: str, tables: Tables) -> tuple[str, str] | None:
    """The measure the model stuck at the end of the name instead of putting it in the field.

    It happens in two forms, both seen on real reels, and with the same outcome: the code saw
    no indication at all and declared «quantità non indicata nel reel» — a **false** gap,
    because the reel had indicated it perfectly well. A gap that lies is worth less than no gap
    at all, because it teaches you not to trust even the true ones, and the honesty of the
    whole product rests on that mechanism.

    1. **In brackets**, any known eyeball measure: «sale (un pizzico)» becomes a declared
       estimate instead of a hole. Brackets are a strong signal that the text annotates the
       quantity; a parenthetical that is not a measure — «crema di cocco (lattina di cocco
       parte sopra più grassa)» — does not appear in `vaghe.yaml` and stays where it is.
    2. **In the open**, only the «q.b.» family: «semi di sesamo q.b.». Here we stay deliberately
       strict, because without brackets the risk of stealing a word from the name is real.

    The comparison is **exact and anchored at the end**, never by containment: «pomodori poco
    maturi» must not become an open-ended quantity because a vague word appears in the middle.
    And the name cannot consist of the expression alone, or it would be left empty.

    Returns `(cleaned_name, measure)` or `None`.
    """
    text = str(name or "").strip()

    if m := _RE_TRAILING_BRACKETS.match(text):
        rest, inside = m.group(1).strip(), m.group(2).strip()
        # At least two words: «(un pizzico)» is a dose, «(noce)» is the kind of nut and
        # «(tazza)» the container. Many `vaghe.yaml` entries have single-word aliases — noce,
        # presa, punta, tazza, bicchiere, filo — which in brackets after a name almost always
        # qualify it rather than dose it.
        if rest and len(inside.split()) >= 2 and _key(inside) in tables.vague:
            return rest, inside

    words = text.split()
    for n in (3, 2, 1):          # "quanto basta", "a piacere", "q.b."
        if len(words) <= n:
            continue
        tail = " ".join(words[-n:])
        key = _without_dots(_key(tail))
        for expression, entry in tables.vague.items():
            if entry.get("without_quantity") and _without_dots(_key(expression)) == key:
                return " ".join(words[:-n]), tail
    return None


def normalise_ingredient(
    name: str,
    quantity_raw: str | None = None,
    unit_raw: str | None = None,
    notes: str | None = None,
    group: str | None = None,
    tables: Tables | None = None,
    system: str = System.METRIC,
    language: str = Language.IT,
) -> Ingredient:
    """Like `_normalise_ingredient`, but first it puts malformed inputs back in order.

    It sits outside the conversion engine and not inside it because this is a problem of
    **reading**, not of conversion: when a coherent pair arrives, the engine already does the
    right thing. Keeping it here leaves the most delicate part of the project untouched.
    """
    t = tables or load_tables()

    # A word in brackets that is NOT a known unit is a note about the ingredient.
    if (in_brackets := _unit_in_brackets(unit_raw, t)) is not None:
        notes, unit_raw = _merge_notes(notes, in_brackets), ""

    # A measure that ended up elsewhere is still an indication, and is to be read as such
    # rather than producing a gap that says something false. Only when there is no other
    # quantity: if the model has already isolated one, what sits in the name or in the notes
    # is a comment.
    #
    # The model has three ways of getting the field wrong, all three of them seen: inside the
    # name («semi di sesamo q.b.»), in brackets within the name («sale (un pizzico)») and —
    # when it really does not know where to put it — in the notes. The third was found by the
    # regression suite, not by a reel.
    if not str(quantity_raw or "").strip() and not str(unit_raw or "").strip():
        if moved := _trailing_measure(name, t):
            name, quantity_raw = moved
        elif (from_notes := str(notes or "").strip().strip("()").strip()) and _key(from_notes) in t.vague:
            quantity_raw, notes = from_notes, None

    warning: str | None = None
    if rewritten := _resolve_contradictory_unit(quantity_raw, unit_raw, name, t, language):
        quantity_raw, unit_raw, warning = rewritten

    ingredient = _normalise_ingredient(name, quantity_raw, unit_raw, notes, group,
                                       t, system, language)
    if not warning:
        return ingredient
    # Gaps do not replace one another: if the engine already had one (an unknown density, say)
    # both hold. `Ingredient` is frozen, so it is rebuilt rather than modified.
    return replace(
        ingredient,
        gap=f"{warning}; {ingredient.gap}" if ingredient.gap else warning,
    )


def _normalise_ingredient(
    name: str,
    quantity_raw: str | None = None,
    unit_raw: str | None = None,
    notes: str | None = None,
    group: str | None = None,
    tables: Tables | None = None,
    system: str = System.METRIC,
    language: str = Language.IT,
) -> Ingredient:
    """Brings a raw ingredient into the target system, or declares why that is not possible.

    `quantity_raw` and `unit_raw` are what the reel said or wrote, untouched by the LLM. All
    the conversion happens here.

    The two axes do different things and are to be kept apart. **`system` decides the
    numbers**: choosing metric or imperial changes the value, so it is settled here, at the
    conversion. **`language` decides the words**: unit labels and gap messages.

    The system applies to the **raw** quantity, not downstream of an intermediate conversion.
    That is why "1 cup of flour" stays "1 cup" for someone cooking in imperial rather than
    becoming 120 g and then coming back as 0.83 cup: a double rounding produces numbers no
    measuring cup can make.
    """
    t = tables or load_tables()
    name = (name or "").strip()
    original = " ".join(x for x in (str(quantity_raw or "").strip(), str(unit_raw or "").strip()) if x)

    # 1. No quantity in the reel.
    if not original:
        return Ingredient(
            name=name, notes=notes, group=group,
            quantity=Quantity(None, None, Provenance.ABSENT, ""),
            gap=message(language, "absent", name=name),
        )

    # 2. Expressions that express no quantity ("q.b.") or leave it open-ended ("qualche"):
    #    nothing is estimated, the wording is kept and flagged.
    if outcome := _try_indeterminate(name, original, quantity_raw, unit_raw, notes, group,
                                     t, language):
        return outcome

    number = parse_quantity(quantity_raw)
    unit = t.canonical_unit(unit_raw)

    # 2-bis. The model does not always separate number and unit: `quantita_raw` can arrive as
    #    "80g" or "1 1/2 cup" with `unita_raw` empty. Without this recovery the unit would be
    #    lost and the number would end up read as a count of pieces — "80g di maiale" became
    #    "80 maiale". It is recovered only when the unit is missing entirely: if the model
    #    isolated one, its one is the good one.
    if unit is None and not str(unit_raw or "").strip():
        if (split_off := _split_off_unit(quantity_raw, t)) is not None:
            number, unit = split_off

    # 3. Eyeball measures with a typical value ("un pizzico", "un filo d'olio").
    if outcome := _try_vague(name, original, number, unit_raw, quantity_raw, notes, group,
                             t, system, language):
        return outcome

    # 4. Unit not recognised.
    if unit is None and unit_raw:
        unit_text = str(unit_raw).strip()

        # 4a. Without a number in front of it, an unrecognised word is NOT a unit: it is an
        #     attribute of the ingredient that the model put in the wrong field ("Dashi in
        #     polvere" arrives as name="Dashi", unita_raw="polvere"). Treating it as a unit
        #     puts it in front of the name and produces "polvere Dashi". It becomes a note in
        #     brackets instead — which Mela reads as a comment — and the quantity stays
        #     honestly absent.
        if number is None:
            q = Quantity(None, None, Provenance.ABSENT, original)
            return Ingredient(
                name, q, _merge_notes(notes, unit_text), group,
                gap=message(language, "quality_not_unit", name=name, unit=unit_text),
            )

        # 4b. There is a number: the unknown unit is kept intact next to it, which is better
        #     than forcing it into a scheme it does not belong to.
        q = Quantity(
            number[0],
            unit_text,
            Provenance.DECLARED,
            original,
            value_max=number[1],
        )
        return Ingredient(name, q, notes, group,
                          gap=message(language, "unknown_unit", unit=unit_raw, name=name))

    # 5. No readable number.
    if number is None:
        q = Quantity(None, str(unit_raw or "").strip() or None, Provenance.ABSENT, original)
        return Ingredient(name, q, notes, group,
                          gap=message(language, "unreadable", original=original, name=name))

    minimum, maximum = number

    # 6. A count of pieces: not converted. "2 uova" stays "2 uova"; if `vaghe.yaml` knows a
    #    typical weight we add it as a comment, without replacing the count.
    if unit is None or unit in t.count:
        return _as_count(name, minimum, maximum, unit, unit_raw, original, notes,
                         group, t, system, language)

    # 7. Spoon measures. Never converted: everybody has a teaspoon at home, a precision scale
    #    not so much. Only the label is translated ("2 tbsp" → "2 cucchiai") and the
    #    equivalent goes in brackets, which Mela treats as a comment.
    if unit in t.spoon_measures:
        return _as_spoon_measure(name, minimum, maximum, unit, original, notes, group,
                                 t, system, language)

    # 8. Weight: exact conversion, no density in play.
    if unit in t.weight:
        grams_min, grams_max = minimum * t.weight[unit], maximum * t.weight[unit]
        val_min, u = unit_for_weight(grams_min, system)
        val_max, _ = unit_for_weight(grams_max, system)
        # "Declared" only if the starting unit is already the arriving one: otherwise a
        # conversion took place, and that has to be said.
        prov = Provenance.DECLARED if unit == u else Provenance.CONVERTED_UNIT
        return _finalise(name, val_min, val_max, u, prov, original, notes, group, system)

    # 9. Volume.
    if unit in t.volume:
        ml_min, ml_max = minimum * t.volume[unit], maximum * t.volume[unit]

        def as_volume(provenance: Provenance) -> Ingredient:
            val_min, u = unit_for_volume(ml_min, system, t)
            val_max, _ = unit_for_volume(ml_max, system, t)
            prov = Provenance.DECLARED if unit == u else provenance
            return _finalise(name, val_min, val_max, u, prov, original, notes, group, system)

        # 9a. Already executable in the requested system: "500 ml" for someone cooking in
        #     metric and "1 cup" for someone cooking in imperial are used exactly as they are.
        #     Converting them would be a net loss.
        if t.is_already_in_system(unit, system):
            return as_volume(Provenance.CONVERTED_UNIT)

        # 9b. Liquid: it stays a volume, only expressed in the target system. No density in
        #     play — nobody weighs milk, in any country.
        if t.is_liquid(name):
            return as_volume(Provenance.CONVERTED_UNIT)

        # 9c. Dry with a known density, and a metric destination: this is the case
        #     `densita.yaml` exists for. Towards imperial density is NOT crossed: a volume
        #     stays a volume, because "200 g of flour" rendered in cups would give 1.67 cup,
        #     i.e. a number no measuring cup can make. The source of the datum does not become
        #     a note for the user: it is documentation of the table, and it contains brackets
        #     that would confuse Mela's parser.
        if code_of(system) == System.METRIC.value and (found := t.density_for(name)) is not None:
            g_per_ml, _ = found
            return _finalise(name, ml_min * g_per_ml, ml_max * g_per_ml, "g",
                             Provenance.CONVERTED_DENSITY, original, notes, group, system)

        # 9d. Density unknown: the volume is kept and the gap is declared. Here we do NOT
        #     invent a plausible density.
        ingr = as_volume(Provenance.CONVERTED_UNIT)
        if code_of(system) == System.METRIC.value:
            return replace(ingr, gap=message(language, "unknown_density", name=name))
        return ingr

    # Defensive: a unit present in the aliases but in no table is a data error.
    q = Quantity(minimum, unit, Provenance.DECLARED, original, value_max=maximum)
    return Ingredient(name, q, notes, group,
                      gap=message(language, "unit_without_conversion", unit=unit))


def _merge_notes(*pieces: str | None) -> str | None:
    present = [p.strip() for p in pieces if p and p.strip()]
    return "; ".join(dict.fromkeys(present)) or None


def _finalise(
    name: str, value_min: float, value_max: float, unit: str, provenance: Provenance,
    original: str, notes: str | None, group: str | None,
    system: str = System.METRIC, language: str = Language.IT, tables: Tables | None = None,
) -> Ingredient:
    """Rounds to kitchen precision and builds the final ingredient."""
    q = Quantity(
        round_for_kitchen(value_min, unit), unit, provenance, original,
        value_max=round_for_kitchen(value_max, unit), system=code_of(system),
    )
    return Ingredient(name, q, notes, group)


def _as_spoon_measure(
    name: str, minimum: float, maximum: float, unit: str, original: str,
    notes: str | None, group: str | None, tables: Tables,
    system: str = System.METRIC, language: str = Language.IT,
) -> Ingredient:
    """Spoons and teaspoons stay as they are, with the equivalent in weight or volume in
    brackets.

    "1 teaspoon of baking powder" is an instruction you carry out; "4 g" calls for a scale few
    people have. Converting it would be a net loss of usability. The only thing touched is the
    label, if it arrives in English: "2 tbsp" → "2 cucchiai".
    """
    ml_min, ml_max = minimum * tables.volume[unit], maximum * tables.volume[unit]

    # The equivalent in brackets follows the target system: "≈ 25 g" says nothing to an
    # American, and "≈ 0,9 oz" says nothing to an Italian.
    if not tables.is_liquid(name) and (found := tables.density_for(name)) is not None:
        g_per_ml, _ = found
        eq_min, eq_unit = unit_for_weight(ml_min * g_per_ml, system)
        eq_max, _ = unit_for_weight(ml_max * g_per_ml, system)
    else:
        eq_min, eq_unit = unit_for_volume(ml_min, system, tables)
        eq_max, _ = unit_for_volume(ml_max, system, tables)
    eq_min, eq_max = round_for_kitchen(eq_min, eq_unit), round_for_kitchen(eq_max, eq_unit)

    eq_text = format_number(eq_min, system)
    if eq_max != eq_min:
        eq_text = f"{eq_text}-{format_number(eq_max, system)}"

    # The equivalent is only worth having if it adds something: for someone cooking in
    # imperial, "2 tbsp (≈ 2 tbsp)" is noise. It is shown when the equivalent's unit differs
    # from the quantity's.
    note = f"≈ {eq_text} {eq_unit}" if eq_unit != unit else None

    q = Quantity(
        minimum, tables.label(unit, maximum, language), Provenance.DECLARED, original,
        value_max=maximum, note=note, system=code_of(system),
    )
    return Ingredient(name, q, notes, group)


def _as_count(
    name: str, minimum: float, maximum: float, unit: str | None, unit_raw: str | None,
    original: str, notes: str | None, group: str | None, tables: Tables,
    system: str = System.METRIC, language: str = Language.IT,
) -> Ingredient:
    """Counted pieces. The count stays the primary datum; the typical weight, if known,
    becomes a comment in brackets."""
    raw = unit or (str(unit_raw).strip() if unit_raw else None)
    note = None
    if raw and (definition := tables.vague.get(_key(raw))):
        if (typical := _vague_value(definition, system)) is not None:
            typical_quantity, u = typical
            total = round_for_kitchen(typical_quantity * maximum, u)
            note = f"≈ {format_number(total, system)} {u}"
    label = tables.label(unit, maximum, language) if unit else raw
    q = Quantity(minimum, label, Provenance.COUNT, original,
                 value_max=maximum, note=note, system=code_of(system))
    return Ingredient(name, q, notes, group)


def _vague_value(definition: dict, system: str) -> tuple[float, str] | None:
    """The typical value of an eyeball measure, in the requested system.

    It is in the table and not calculated: a pinch is 0.5 g in metric and 1/8 tsp in imperial,
    and converting the first into the second would give 0.018 oz — a number nobody carries out
    (see the header of `vaghe.yaml`).
    """
    value = definition.get("value")
    if not isinstance(value, dict):
        return None
    per_system = value.get(code_of(system)) or value.get(System.METRIC.value)
    if not isinstance(per_system, dict) or per_system.get("quantity") is None:
        return None
    return float(per_system["quantity"]), per_system.get("unit", "g")


def _vague_note(definition: dict, value: float, unit: str, system: str, language: str) -> str:
    """The note explaining an estimate, composed from the actual value.

    It is not written in the table: written by hand it would depend on the language while the
    number depends on the system, and the two diverge. Composed here it cannot contradict the
    quantity it accompanies.
    """
    names = definition.get("name") or {}
    expression_name = names.get(code_of(language)) or names.get(Language.IT.value) or ""
    return f"{expression_name} ≈ {format_number(value, system)} {unit}".strip()


def _try_indeterminate(
    name: str, original: str, quantity_raw: str | None, unit_raw: str | None,
    notes: str | None, group: str | None, tables: Tables, language: str = Language.IT,
) -> Ingredient | None:
    """"q.b.", "qualche", "un po'": no number to extract, and that has to be said clearly.

    The match tolerates the expression being buried in a longer string: models sometimes
    produce unita_raw="burro q.b." instead of isolating the "q.b.". In that case the name stays
    the one in the `name` field and the ingredient becomes "burro q.b.".
    """
    for raw in (quantity_raw, unit_raw, original):
        if not raw:
            continue
        k = _key(str(raw)).rstrip(".")
        words = set(k.split())
        definition = tables.vague.get(k) or tables.vague.get(_key(str(raw)))
        # Exact match, or the expression appears as a token in the string ("q.b." inside
        # "burro q.b."). The comparison ignores dots, which make "q.b." hard to tokenise
        # reliably.
        if not definition:
            k_nd = _without_dots(k)
            for vague_key, entry in tables.vague.items():
                if entry.get("without_quantity") and _contains_expression(k_nd, _without_dots(vague_key)):
                    definition = entry
                    break
        if definition and definition.get("without_quantity"):
            # "q.b." in Italian, "to taste" in English: the rendering is in the table per
            # language.
            renderings = definition.get("rendering") or {}
            rendering = renderings.get(code_of(language)) or renderings.get(Language.IT.value) or "q.b."
            q = Quantity(None, rendering, Provenance.INDETERMINATE, original)
            return Ingredient(name, q, notes, group)
        if k in tables.indeterminate or (words & tables.indeterminate):
            q = Quantity(None, str(raw).strip(), Provenance.INDETERMINATE, original)
            return Ingredient(
                name, q, notes, group,
                gap=message(language, "indeterminate", original=str(raw).strip(), name=name),
            )
    return None


def _without_dots(text: str) -> str:
    """Normalises dots away for comparing abbreviations: "q.b." → "qb"."""
    return re.sub(r"\.", "", text)


def _contains_expression(text: str, expression: str) -> bool:
    """True if `expression` (already normalised) appears as a token sequence in `text`.
    Avoids substring false positives: "qb" must not fire inside "sqb"."""
    text_tokens = text.split()
    expression_tokens = expression.split()
    if not expression_tokens:
        return False
    for i in range(len(text_tokens) - len(expression_tokens) + 1):
        if text_tokens[i:i + len(expression_tokens)] == expression_tokens:
            return True
    return False


def _try_vague(
    name: str, original: str, number: tuple[float, float] | None, unit_raw: str | None,
    quantity_raw: str | None, notes: str | None, group: str | None, tables: Tables,
    system: str = System.METRIC, language: str = Language.IT,
) -> Ingredient | None:
    """Eyeball measures with a typical value. The result is marked `stimato:vaghe` and carries
    the reason in a note — it must never pass for certain data."""
    for raw in (unit_raw, quantity_raw, original):
        if not raw:
            continue
        definition = tables.vague.get(_key(str(raw)))

        # Captions write «1 presa di sale», «1 bel pizzico»: a numeral in front of the
        # expression. The exact match did not see it and the ingredient ended up as a count —
        # «1 sale», that is, one salt. It is retried on the tail alone; the multiplying factor
        # is already applied by `number` below, so «2 pizzichi» would be worth double without
        # adding anything else.
        if not definition and (m := _RE_QUANTITY_WITH_UNIT.match(_key(str(raw)))):
            definition = tables.vague.get(_key(m.group(2)))

        if not definition or definition.get("without_quantity"):
            continue

        # Multipliers ("un paio", "una dozzina"): they do not produce a weight, they multiply
        # a count. If there is no unit to multiply, they count as pieces.
        if (multiplier := definition.get("multiplier")) is not None:
            n = float(multiplier) * (number[0] if number else 1.0)
            q = Quantity(n, None, Provenance.COUNT, original)
            return Ingredient(name, q, notes, group)

        if (typical := _vague_value(definition, system)) is None:
            continue
        value, unit = typical
        count = number[1] if number else 1.0
        count_min = number[0] if number else 1.0
        q = Quantity(
            round_for_kitchen(value * count_min, unit),
            unit,
            Provenance.ESTIMATED_VAGUE,
            original,
            value_max=round_for_kitchen(value * count, unit),
            note=_vague_note(definition, value, unit, system, language),
            system=code_of(system),
        )
        return Ingredient(
            name, q, notes, group,
            gap=message(language, "vague_estimate", original=original, name=name),
        )
    return None


# --------------------------------------------------------------------------------------
# Temperatures in the free text of the method
# --------------------------------------------------------------------------------------

_RE_FAHRENHEIT = re.compile(r"(\d{2,3})\s*°?\s*F\b", re.IGNORECASE)
_RE_CELSIUS = re.compile(r"(\d{2,3})\s*°?\s*C\b", re.IGNORECASE)


def fahrenheit_to_celsius(degrees_f: float, rounding: int = 5) -> float:
    celsius = (degrees_f - 32.0) * 5.0 / 9.0
    return float(round(celsius / rounding) * rounding)


def celsius_to_fahrenheit(degrees_c: float, rounding: int = 25) -> float:
    """Towards Fahrenheit the rounding is to 25: American oven dials are calibrated that way
    (325, 350, 375), and a "347 °F" would match no position on them."""
    fahrenheit = degrees_c * 9.0 / 5.0 + 32.0
    return float(round(fahrenheit / rounding) * rounding)


def convert_temperatures_in_text(
    text: str, tables: Tables | None = None, system: str = System.METRIC,
) -> tuple[str, list[str]]:
    """Brings temperatures into the scale of the target system.

    An Anglo-Saxon reel says "bake at 350°F" and an Italian oven does not have that scale; an
    Italian one says "180 °C" and an American oven does not either. The conversion therefore
    goes both ways, according to who is reading.

    Returns the converted text and the list of substitutions made, because every change to the
    author's text is to be tracked and not applied on the quiet.
    """
    t = tables or load_tables()
    substitutions: list[str] = []
    towards_metric = code_of(system) == System.METRIC.value

    def _substitute(m: re.Match[str]) -> str:
        degrees = float(m.group(1))
        # Below a certain threshold it is almost never a cooking temperature ("cuoci 20 minuti
        # a fuoco medio" contains numbers that are not degrees): better not to touch it.
        if towards_metric and degrees < 100:
            return m.group(0)
        if not towards_metric and degrees < 40:
            return m.group(0)

        if towards_metric:
            converted, unit = fahrenheit_to_celsius(degrees, t.rounding_c), "°C"
        else:
            converted, unit = celsius_to_fahrenheit(degrees), "°F"
        rendered = f"{format_number(converted)} {unit}"
        substitutions.append(f"{m.group(0).strip()} → {rendered}")
        return rendered

    expression = _RE_FAHRENHEIT if towards_metric else _RE_CELSIUS
    return expression.sub(_substitute, text), substitutions
