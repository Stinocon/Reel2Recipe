"""mela.py — export in Mela's format (the recipe app for iOS/macOS).

The format is documented publicly by its author at https://mela.recipes/fileformat/. Two
things matter more than the rest, and they are the reason this module exists instead of a
`json.dumps` scattered through the code:

1. `ingredients` and `instructions` are **strings separated by `\\n`**, not arrays. A line
   starting with `#` becomes a group heading ("# Per la crema").
2. Mela's parser already recognises quantities and units in Italian. So the right shape for
   an ingredient is the plain string "200 g farina 00": inventing a structure of our own and
   then recomposing it would make the result worse. Text in brackets is treated by Mela as a
   comment, and that is where the notes and the equivalents ("≈ 4 g") end up.

`.melarecipe` is a single JSON file; `.melarecipes` is a zip of `.melarecipe`, which is how
several recipes are imported in one go.
"""

from __future__ import annotations

import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .recipe import Recipe, free_path
from .units import text_from

# Headings and phrases for the export, per language. Few and stable: a dictionary here reads
# better than a translation mechanism for a handful of strings.
#
# The keys are English, the values are not: they are what the user reads, so the Italian ones
# stay Italian. It is the same split as `units.MESSAGES`.
TEXTS = {
    "it": {
        "to_check": "Da verificare",
        "source": "Fonte",
        "recipe_by": "Ricetta di {author}",
        "recipe_by_with_url": "Ricetta di {author} — {url}",
        "reorganised": "Trascritta e riorganizzata automaticamente con Reel2Recipe.",
    },
    "en": {
        "to_check": "To check",
        "source": "Source",
        "recipe_by": "Recipe by {author}",
        "recipe_by_with_url": "Recipe by {author} — {url}",
        "reorganised": "Transcribed and reorganised automatically with Reel2Recipe.",
    },
}


def text(language: str, key: str, **data) -> str:
    """A string of the export in the recipe's language, falling back to Italian."""
    return text_from(TEXTS, language, key, **data)

# Mela stores dates as seconds since 1 January 2001 UTC (Apple's reference epoch).
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Numbering at the head of a step: "1. ", "2) ", "3 - ". Three precautions, because this
# deletes text and deleting too much of it is silent: only at the start of a line, always
# followed by a space, and only if a word begins after it. The last one is there for
# "5 - 6 minuti di cottura", which without it would become "6 minuti di cottura" — a number
# changed without anybody noticing, which is the damage this project exists not to do
# (AGENTS.md §3).
_NUMBERING = re.compile(r"^\d{1,2}\s*[.)\-]\s+(?=[^\W\d_])")

SINGLE_EXTENSION = ".melarecipe"
MULTI_EXTENSION = ".melarecipes"


def _duration(minutes: int | None) -> str:
    """A duration as a recipe book writes it: "25 min", "1 h 30 min"."""
    if not minutes or minutes <= 0:
        return ""
    hours, rest = divmod(int(minutes), 60)
    if hours and rest:
        return f"{hours} h {rest} min"
    if hours:
        return f"{hours} h"
    return f"{rest} min"


def _identifier(recipe: Recipe) -> str:
    """Mela accepts a UUID or, for recipes imported from the web, the URL without its scheme.

    Using the URL when there is one is not a detail: it gives Mela a stable key, so
    re-importing the same recipe updates the existing one instead of duplicating it.
    """
    url = recipe.source.url if recipe.source else None
    if url:
        return re.sub(r"^https?://", "", url.strip()).rstrip("/")
    return str(uuid.uuid4())


def ingredient_lines(recipe: Recipe) -> list[str]:
    """Ingredients as lines of text, with group headings in the `# Title` form."""
    lines: list[str] = []
    groups = recipe.groups
    show_headings = len([g for g in groups if g]) > 0 and len(groups) > 1

    for group in groups:
        if show_headings and group:
            lines.append(f"# {group}")
        for ingredient in recipe.ingredients:
            if ingredient.group == group:
                lines.append(ingredient.mela_line(recipe.language))
    return lines


def method_lines(recipe: Recipe) -> list[str]:
    """Steps without numbering: Mela adds that itself.

    This used to write "1. ", on the assumption that explicit numbering would survive the
    import better than implicit numbering. The first recipe actually opened in Mela proved
    otherwise: Mela numbers the lines by itself and the result was "1 1. Frullare il tofu…".
    The assumption was not testable until the app had seen it, and it fell at the first look.

    A step that arrives already numbered from the model is cleaned up, otherwise the same
    duplication comes back by another road.
    """
    return [_NUMBERING.sub("", step.strip()) for step in recipe.method]


def note_lines(recipe: Recipe) -> list[str]:
    """Notes, warnings about the conversions, and the attribution.

    The gaps end up here and are not hidden: whoever opens the recipe in the kitchen has to
    know which quantities are estimates of ours and which ones the reel did not state at all.
    """
    lines: list[str] = list(recipe.notes)
    language = recipe.language

    if recipe.gaps:
        lines.append("")
        lines.append("# " + text(language, "to_check"))
        lines.extend(f"* {g}" for g in recipe.gaps)

    if recipe.source and (recipe.source.url or recipe.source.author):
        lines.append("")
        lines.append("# " + text(language, "source"))
        author = recipe.source.author
        url = recipe.source.url
        if author and url:
            lines.append(text(language, "recipe_by_with_url", author=author, url=url))
        elif author:
            lines.append(text(language, "recipe_by", author=author))
        elif url:
            lines.append(url)
        lines.append(text(language, "reorganised"))

    return lines


def to_melarecipe(recipe: Recipe) -> dict:
    """Builds the `.melarecipe` dictionary. The keys and types follow the documented format:
    all strings except `images` (array), `favorite`/`wantToCook` (bool) and `date` (float)."""
    return {
        "id": _identifier(recipe),
        "title": recipe.title,
        "text": recipe.description or "",
        "images": list(recipe.images),
        # Mela does not allow commas in category names: we substitute them rather than
        # producing categories that break apart on import.
        "categories": [c.replace(",", " ").strip() for c in recipe.categories if c.strip()],
        "yield": recipe.servings or "",
        "prepTime": _duration(recipe.prep_time_min),
        "cookTime": _duration(recipe.cook_time_min),
        "totalTime": _duration(recipe.total_time_min()),
        "ingredients": "\n".join(ingredient_lines(recipe)),
        "instructions": "\n".join(method_lines(recipe)),
        "notes": "\n".join(note_lines(recipe)).strip(),
        "nutrition": "",
        "link": (recipe.source.url if recipe.source else "") or "",
        "favorite": False,
        "wantToCook": False,
        "date": (datetime.now(timezone.utc) - _APPLE_EPOCH).total_seconds(),
    }


def write_melarecipe(recipe: Recipe, folder: Path | str) -> Path:
    """Writes a single recipe as `.melarecipe`. Returns the path created."""
    path = free_path(folder, recipe.file_name(), SINGLE_EXTENSION)
    path.write_text(
        json.dumps(to_melarecipe(recipe), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def write_melarecipes(recipes: list[Recipe], path: Path | str) -> Path:
    """Writes several recipes into a single `.melarecipes` (a zip of `.melarecipe`), which is
    how a batch of recipes is imported into Mela in one go."""
    path = Path(path)
    if path.suffix != MULTI_EXTENSION:
        path = path.with_suffix(MULTI_EXTENSION)
    path.parent.mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for recipe in recipes:
            base = recipe.file_name()
            name, n = f"{base}{SINGLE_EXTENSION}", 2
            while name in used:
                name = f"{base}-{n}{SINGLE_EXTENSION}"
                n += 1
            used.add(name)
            z.writestr(
                name,
                json.dumps(to_melarecipe(recipe), ensure_ascii=False, indent=2),
            )
    return path


def read_melarecipe(path: Path | str) -> dict:
    """Reads a `.melarecipe` back. Used by the round-trip tests and to re-import an export."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
