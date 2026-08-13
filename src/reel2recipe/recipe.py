"""recipe.py — the model of a recipe, and the step from the LLM's draft to the finished thing.

The LLM produces a *draft*: text extracted from the reel, with the quantities raw, exactly as
they were spoken or written. Here the draft becomes a `Recipe`: the quantities go through
`units.py` and turn into metric measures with their provenance, Fahrenheit temperatures become
Celsius, and everything that could not be determined ends up in `gaps` instead of disappearing.

The rule governing this module: **a declared gap is worth more than an invented number**.
Whoever is cooking can deal with "quantity not given"; they cannot deal with a wrong weight
they do not know is wrong.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .units import (
    UNCERTAIN_PROVENANCES,
    Ingredient,
    Language,
    Provenance,
    Quantity,
    System,
    Tables,
    code_of,
    convert_temperatures_in_text,
    load_tables,
    normalise_ingredient,
    text_from,
)


# --------------------------------------------------------------------------------------
# The compatibility net over the stored keys
# --------------------------------------------------------------------------------------

# `Recipe.to_dict()` starts from `asdict(self)`, so `Recipe`'s own fields **are** the JSON keys
# the recipe is stored under: renaming them renames every recipe already saved in the user's
# library. This map is what keeps those readable, and it has no expiry date — a personal
# library is not migrated destructively, and a recipe saved months ago has to keep opening.
# Old rows are rewritten in English only when that recipe is next saved, which happens by
# itself because `to_dict()` always emits the new spelling: lazy, non-destructive, and with no
# moment where the library is half migrated.
#
# Only the top level needs this. The nested ingredient and quantity dictionaries are built by
# `to_dict()` from string literals, so their keys were deliberately left in Italian and have
# never changed — the rename of `Ingredient` and `Quantity` did not touch a single stored file.
LEGACY_KEYS: dict[str, str] = {
    # Recipe
    "title": "titolo",
    "ingredients": "ingredienti",
    "method": "procedimento",
    "description": "descrizione",
    "servings": "porzioni",
    "prep_time_min": "tempo_preparazione_min",
    "cook_time_min": "tempo_cottura_min",
    "notes": "note",
    "categories": "categorie",
    "source": "fonte",
    "gaps": "lacune",
    "confidence": "confidenza",
    "images": "immagini",
    "transcript": "trascrizione",
    "language": "lingua",
    "system": "sistema",
    "total_time_min": "tempo_totale_min",
    "has_uncertainties": "ha_incertezze",
    # Source
    "author": "autore",
    "platform": "piattaforma",
    "original_title": "titolo_originale",
    "acquired_at": "acquisita_il",
}


def stored_field(d: dict, name: str, default=None):
    """A field of a stored recipe, read under its English name or the Italian one it had before.

    It lives here and not in `store.py` because the map of the keys is one thing and must have
    one place: `store.py` reads the stored JSON directly as well, without going through
    `from_dict`, to build the library listing. Two copies of the same map would diverge at the
    first field anybody adds.
    """
    if name in d:
        return d[name]
    return d.get(LEGACY_KEYS.get(name, name), default)


def free_path(folder: Path | str, base: str, extension: str) -> Path:
    """A path that does not exist yet, adding `-2`, `-3`… when needed.

    An export must never silently overwrite yesterday's: the only person who would notice is
    the one who goes looking for the old file and finds it gone. The folder is created.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{base}{extension}"
    n = 2
    while path.exists():
        path = folder / f"{base}-{n}{extension}"
        n += 1
    return path


@dataclass
class Source:
    """Where the recipe comes from. Always to be filled in when known: crediting the original
    author is not an optional extra, it is the correct way to use their work."""

    url: str | None = None
    author: str | None = None
    platform: str | None = None
    original_title: str | None = None
    acquired_at: str | None = None

    @staticmethod
    def now(**kwargs) -> "Source":
        return Source(acquired_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), **kwargs)

    @staticmethod
    def from_dict(d: dict) -> "Source":
        """Reads both spellings, like `Recipe.from_dict` and for the same reason.

        This used to be `Source(**d)`, which worked only because the field names and the stored
        keys were the same word. After the rename that splat would raise `TypeError` on every
        recipe saved before the migration — and it would do so while *loading the library*,
        i.e. the one operation that must never fail.
        """
        return Source(
            url=d.get("url"),
            author=stored_field(d, "author"),
            platform=stored_field(d, "platform"),
            original_title=stored_field(d, "original_title"),
            acquired_at=stored_field(d, "acquired_at"),
        )


@dataclass
class Recipe:
    title: str
    ingredients: list[Ingredient] = field(default_factory=list)
    method: list[str] = field(default_factory=list)
    description: str | None = None
    servings: str | None = None
    prep_time_min: int | None = None
    cook_time_min: int | None = None
    notes: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    source: Source | None = None
    gaps: list[str] = field(default_factory=list)
    confidence: dict[str, str] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)   # base64, without the data: header
    transcript: str | None = None                     # kept for manual review
    # The two axes the recipe was produced with. The system is the one the quantities are
    # expressed in and cannot be changed without reconverting; the language is the one the
    # model wrote names and method in, and changing it calls for a fresh extraction.
    language: str = Language.IT.value
    system: str = System.METRIC.value

    # ---- properties the interface needs -------------------------------------------

    @property
    def has_uncertainties(self) -> bool:
        return bool(self.gaps) or any(
            i.quantity.provenance in UNCERTAIN_PROVENANCES for i in self.ingredients
        )

    @property
    def groups(self) -> list[str | None]:
        """Ingredient groups in the order they appear ("Per la base", "Per la crema")."""
        seen: list[str | None] = []
        for i in self.ingredients:
            if i.group not in seen:
                seen.append(i.group)
        return seen

    def total_time_min(self) -> int | None:
        parts = [t for t in (self.prep_time_min, self.cook_time_min) if t]
        return sum(parts) if parts else None

    def file_name(self) -> str:
        """A readable, safe file name derived from the title.

        It lives here and not in the export modules because every format has to call the same
        recipe the same thing: `yaki-udon.melarecipe`, `yaki-udon.md`, `yaki-udon.pdf` are the
        same thing in three outfits.
        """
        base = unicodedata.normalize("NFKD", self.title)
        base = base.encode("ascii", "ignore").decode("ascii")
        base = re.sub(r"[^\w\s-]", "", base).strip()
        base = re.sub(r"[\s_]+", "-", base).lower()
        return (base or "ricetta")[:60]

    # ---- serialisation ------------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        # The ingredient dictionaries are rebuilt by hand rather than left to `asdict`, and the
        # keys are Italian string literals on purpose: they are *format*, written inside every
        # recipe in the library and read by `web/app.js`. Keeping them decoupled from the Python
        # attribute names is what let `Ingredient` and `Quantity` be renamed without a migration.
        d["ingredients"] = [
            {
                "nome": i.name,
                "note": i.notes,
                "gruppo": i.group,
                "lacuna": i.gap,
                "riga": i.mela_line(),
                "quantita": {
                    "valore": i.quantity.value,
                    "valore_max": i.quantity.value_max,
                    "unita": i.quantity.unit,
                    "provenienza": i.quantity.provenance.value,
                    "testo_originale": i.quantity.original_text,
                    "nota": i.quantity.note,
                    "sistema": i.quantity.system,
                    "incerta": i.quantity.provenance in UNCERTAIN_PROVENANCES,
                },
            }
            for i in self.ingredients
        ]
        d["total_time_min"] = self.total_time_min()
        d["has_uncertainties"] = self.has_uncertainties
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @staticmethod
    def from_dict(d: dict) -> "Recipe":
        """Rebuilds a recipe from its stored form, in either spelling.

        `stored_field` is what makes a recipe saved before the migration keep opening. It is not
        a transitional courtesy to be removed later: the library is the user's, it is not
        rewritten in bulk, and a row saved once may sit there for years.
        """
        ingredients = []
        for i in stored_field(d, "ingredients", []) or []:
            q = i.get("quantita") or {}
            ingredients.append(
                Ingredient(
                    name=i.get("nome", ""),
                    notes=i.get("note"),
                    group=i.get("gruppo"),
                    gap=i.get("lacuna"),
                    quantity=Quantity(
                        value=q.get("valore"),
                        unit=q.get("unita"),
                        provenance=Provenance(q.get("provenienza", "assente")),
                        original_text=q.get("testo_originale", ""),
                        value_max=q.get("valore_max"),
                        note=q.get("nota"),
                        system=q.get("sistema", System.METRIC.value),
                    ),
                )
            )
        raw_source = stored_field(d, "source")
        return Recipe(
            title=stored_field(d, "title", "Senza titolo"),
            ingredients=ingredients,
            method=list(stored_field(d, "method") or []),
            description=stored_field(d, "description"),
            servings=stored_field(d, "servings"),
            prep_time_min=stored_field(d, "prep_time_min"),
            cook_time_min=stored_field(d, "cook_time_min"),
            notes=list(stored_field(d, "notes") or []),
            categories=list(stored_field(d, "categories") or []),
            source=Source.from_dict(raw_source) if raw_source else None,
            gaps=list(stored_field(d, "gaps") or []),
            confidence=dict(stored_field(d, "confidence") or {}),
            images=list(stored_field(d, "images") or []),
            transcript=stored_field(d, "transcript"),
            language=stored_field(d, "language", Language.IT.value),
            system=stored_field(d, "system", System.METRIC.value),
        )


# --------------------------------------------------------------------------------------
# From the LLM's draft to the normalised recipe
# --------------------------------------------------------------------------------------


def _int_or_none(value) -> int | None:
    try:
        n = int(float(value))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def from_draft(
    draft: dict,
    source: Source | None = None,
    images: list[str] | None = None,
    transcript: str | None = None,
    tables: Tables | None = None,
    language: str = Language.IT,
    system: str = System.METRIC,
) -> Recipe:
    """Turns the JSON draft produced by `extract.py` into a normalised `Recipe`.

    All the quantity conversion happens here: the draft arrives with the raw values ("1",
    "cup") and comes out with the metric ones and their provenance. Gaps that emerge during
    the conversion are added to the ones the LLM already declared.

    The draft's own keys stay Italian, and are read as such below: they are the JSON schema the
    local model answers with (`extract.py`), and changing them means re-running the model gate.
    They are the input format, not this module's names.
    """
    t = tables or load_tables()

    ingredients: list[Ingredient] = []
    gaps: list[str] = list(draft.get("lacune") or [])

    for raw in draft.get("ingredienti") or []:
        name = (raw.get("nome") or "").strip()
        if not name:
            continue
        ingredient = normalise_ingredient(
            name=name,
            quantity_raw=raw.get("quantita_raw"),
            unit_raw=raw.get("unita_raw"),
            notes=(raw.get("note") or None),
            group=(raw.get("gruppo") or None),
            tables=t,
            system=system,
            language=language,
        )
        ingredients.append(ingredient)
        if ingredient.gap:
            gaps.append(ingredient.gap)

    # Fahrenheit temperatures in the method have to be brought to Celsius: an Italian oven does
    # not have that scale. Every substitution is tracked among the notes.
    method: list[str] = []
    temperature_notes: list[str] = []
    for step in draft.get("procedimento") or []:
        text = str(step).strip()
        if not text:
            continue
        converted, substitutions = convert_temperatures_in_text(text, t, system)
        method.append(converted)
        temperature_notes.extend(substitutions)

    notes = list(draft.get("note") or [])
    if temperature_notes:
        # The direction depends on the system: towards metric you arrive at Celsius, towards
        # imperial at Fahrenheit. Saying it the wrong way round would be worse than not saying it.
        headings = {
            "it": {"metrico": "Temperature convertite in Celsius: ",
                   "imperiale": "Temperature convertite in Fahrenheit: "},
            "en": {"metrico": "Temperatures converted to Celsius: ",
                   "imperiale": "Temperatures converted to Fahrenheit: "},
        }
        notes.append(text_from(headings, language, code_of(system))
                     + ", ".join(dict.fromkeys(temperature_notes)))

    return Recipe(
        language=code_of(language),
        system=code_of(system),
        title=(draft.get("titolo") or "Ricetta senza titolo").strip(),
        ingredients=ingredients,
        method=method,
        description=(draft.get("descrizione") or None),
        servings=(draft.get("porzioni") or None),
        prep_time_min=_int_or_none(draft.get("tempo_preparazione_min")),
        cook_time_min=_int_or_none(draft.get("tempo_cottura_min")),
        notes=notes,
        categories=[c for c in (draft.get("categorie") or []) if c],
        source=source,
        gaps=list(dict.fromkeys(gaps)),
        confidence=dict(draft.get("confidenza") or {}),
        images=list(images or []),
        transcript=transcript,
    )
