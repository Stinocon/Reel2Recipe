"""Tests for the export to Mela and for the draft → recipe step.

The real proof is still opening a `.melarecipe` in Mela on iOS (see the README). These tests
protect the two things that break silently: the `\\n` separators between the ingredient and
method lines, and the `#` format of the group headings.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from reel2recipe.mela import (
    read_melarecipe,
    ingredient_lines,
    write_melarecipe,
    write_melarecipes,
    to_melarecipe,
)
from reel2recipe.recipe import Source, Recipe, from_draft


DRAFT = {
    "title": "Tiramisù al pistacchio",
    "servings": "6 persone",
    "prep_time_min": 25,
    "cook_time_min": 0,
    "ingredients": [
        {"quantity_raw": "250", "unit_raw": "g", "name": "mascarpone", "group": "Per la crema"},
        {"quantity_raw": "3", "unit_raw": None, "name": "uova", "group": "Per la crema"},
        {"quantity_raw": "1", "unit_raw": "cup", "name": "zucchero semolato", "group": "Per la crema"},
        {"quantity_raw": "200", "unit_raw": "g", "name": "savoiardi", "group": "Per la base"},
        {"quantity_raw": "q.b.", "unit_raw": None, "name": "cacao amaro", "group": "Per la base"},
    ],
    "method": [
        "Monta i tuorli con lo zucchero fino a ottenere un composto chiaro.",
        "Inforna a 350°F per 20 minuti.",
    ],
    "notes": ["Riposa in frigo almeno 4 ore."],
    "categories": ["Dolci", "Senza cottura"],
    "confidence": {"ingredients": "alta", "method": "media"},
    "gaps": [],
}


@pytest.fixture
def recipe() -> Recipe:
    return from_draft(
        DRAFT,
        source=Source.now(
            url="https://www.instagram.com/reel/ABC123/",
            author="cucina_test",
            platform="instagram",
        ),
    )


# ----------------------------------------------------------------------------------
# Draft → recipe
# ----------------------------------------------------------------------------------


def test_the_draft_normalises_the_quantities(recipe):
    """The cup of sugar must have become 200 g by going through units.py."""
    zucchero = next(i for i in recipe.ingredients if i.name == "zucchero semolato")
    assert (zucchero.quantity.value, zucchero.quantity.unit) == (200.0, "g")


def test_the_draft_converts_the_temperatures(recipe):
    """350°F in the method has to become 175 °C, and the substitution has to be tracked.

    The trace is checked on the substitution itself ("350°F → 175 °C") and not on a word of
    the sentence introducing it: that one depends on language and system, whereas the fact
    that a change to the author's text is declared does not.
    """
    assert any("175 °C" in p for p in recipe.method)
    assert not any("350" in p and "F" in p for p in recipe.method)
    assert any("350°F" in n and "175 °C" in n for n in recipe.notes)


def test_the_draft_gathers_the_gaps(recipe):
    """The cocoa's "q.b." is not a gap, but the recipe has to be able to say it has
    uncertainties."""
    assert recipe.has_uncertainties


def test_total_time(recipe):
    assert recipe.total_time_min() == 25


def test_the_model_round_trips(recipe):
    """Recipe → dict → Recipe without losing quantities or provenances."""
    rebuilt = Recipe.from_dict(json.loads(recipe.to_json()))
    assert rebuilt.title == recipe.title
    assert len(rebuilt.ingredients) == len(recipe.ingredients)
    for a, b in zip(recipe.ingredients, rebuilt.ingredients):
        assert a.mela_line() == b.mela_line()
        assert a.quantity.provenance is b.quantity.provenance


# ----------------------------------------------------------------------------------
# The Mela format
# ----------------------------------------------------------------------------------


def test_the_ingredients_are_a_newline_separated_string(recipe):
    """The easiest mistake to make: Mela wants a string, not an array."""
    d = to_melarecipe(recipe)
    assert isinstance(d["ingredients"], str)
    assert "\n" in d["ingredients"]
    assert isinstance(d["instructions"], str)


def test_groups_become_hash_headings(recipe):
    lines = ingredient_lines(recipe)
    assert "# Per la crema" in lines
    assert "# Per la base" in lines
    # The heading has to come before its ingredients.
    assert lines.index("# Per la crema") < lines.index("250 g mascarpone")


def test_a_single_group_produces_no_heading():
    """With only one group (or none), the heading is noise."""
    r = from_draft({
        "title": "Pasta al burro",
        "ingredients": [{"quantity_raw": "100", "unit_raw": "g", "name": "burro"}],
        "method": ["Sciogli il burro."],
    })
    assert not any(line.startswith("#") for line in ingredient_lines(r))


def test_qb_rendered_the_italian_way(recipe):
    d = to_melarecipe(recipe)
    assert "cacao amaro q.b." in d["ingredients"]


def test_the_method_is_not_numbered(recipe):
    """Mela adds the numbering: adding it here produced "1 1. Monta i tuorli…".

    Seen on the first recipe actually opened in the app; not deducible from the format.
    """
    d = to_melarecipe(recipe)
    assert d["instructions"].startswith("Monta i tuorli")
    assert "1. " not in d["instructions"]


def test_numbering_already_present_is_stripped(recipe):
    """The same duplication by the other road: a step arriving already numbered from the
    model."""
    recipe.method = ["1. Monta i tuorli.", "2) Inforna.", "3 - Sforna."]
    lines = to_melarecipe(recipe)["instructions"].split("\n")
    assert lines == ["Monta i tuorli.", "Inforna.", "Sforna."]


def test_a_step_starting_with_a_digit_stays_whole(recipe):
    """A leading digit is not always a list label: here it is the quantity.

    The third case is the one that forces the criterion to be strict: "5 - 6 minuti" has the
    shape of a numbering, but removing "5 - " would silently change a cooking time.
    """
    recipe.method = [
        "200 g di farina in una ciotola.",
        "180 °C per 20 minuti.",
        "5 - 6 minuti di cottura, finché non è dorato.",
    ]
    lines = to_melarecipe(recipe)["instructions"].split("\n")
    assert lines == [
        "200 g di farina in una ciotola.",
        "180 °C per 20 minuti.",
        "5 - 6 minuti di cottura, finché non è dorato.",
    ]


def test_required_fields_and_types(recipe):
    d = to_melarecipe(recipe)
    for key in ("id", "title", "text", "images", "categories", "yield", "prepTime",
                "cookTime", "totalTime", "ingredients", "instructions", "notes",
                "nutrition", "link", "favorite", "wantToCook", "date"):
        assert key in d, f"field missing from the .melarecipe: {key}"
    assert isinstance(d["images"], list)
    assert isinstance(d["categories"], list)
    assert isinstance(d["favorite"], bool)
    assert isinstance(d["date"], float)


def test_the_identifier_comes_from_the_url(recipe):
    """With a URL, the id is the URL without its scheme: it gives Mela a stable key for
    updates."""
    assert to_melarecipe(recipe)["id"] == "www.instagram.com/reel/ABC123"


def test_the_link_is_filled_in_for_attribution(recipe):
    """Crediting the original author is not optional."""
    d = to_melarecipe(recipe)
    assert d["link"] == "https://www.instagram.com/reel/ABC123/"
    assert "cucina_test" in d["notes"]


def test_readable_durations():
    r = from_draft({"title": "X", "prep_time_min": 90, "cook_time_min": 45})
    d = to_melarecipe(r)
    assert d["prepTime"] == "1 h 30 min"
    assert d["cookTime"] == "45 min"
    assert d["totalTime"] == "2 h 15 min"


def test_categories_without_commas():
    """Mela does not allow commas in category names: they would be split on import."""
    r = from_draft({"title": "X", "categories": ["Dolci, freddi"]})
    assert "," not in to_melarecipe(r)["categories"][0]


def test_the_gaps_end_up_in_the_notes():
    """An estimate must never pass for certain data: it goes into the recipe."""
    r = from_draft({
        "title": "Test",
        "ingredients": [{"quantity_raw": "1", "unit_raw": "cup", "name": "gorgonzola"}],
    })
    notes = to_melarecipe(r)["notes"]
    assert "Da verificare" in notes
    assert "densità sconosciuta" in notes


# ----------------------------------------------------------------------------------
# Writing to disk
# ----------------------------------------------------------------------------------


def test_writing_and_reading_back(recipe, tmp_path):
    path = write_melarecipe(recipe, tmp_path)
    assert path.suffix == ".melarecipe"
    reread = read_melarecipe(path)
    assert reread["title"] == "Tiramisù al pistacchio"
    assert "250 g mascarpone" in reread["ingredients"]


def test_it_does_not_overwrite_earlier_exports(recipe, tmp_path):
    first = write_melarecipe(recipe, tmp_path)
    second = write_melarecipe(recipe, tmp_path)
    assert first != second
    assert first.exists() and second.exists()


def test_the_multiple_export_is_a_zip(recipe, tmp_path):
    path = write_melarecipes([recipe, recipe], tmp_path / "arretrato")
    assert path.suffix == ".melarecipes"
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert len(names) == 2, "duplicate names must be disambiguated, not overwritten"
        assert all(n.endswith(".melarecipe") for n in names)
        assert json.loads(z.read(names[0]))["title"] == "Tiramisù al pistacchio"
