"""Tests for the Markdown and PDF export.

These formats exist for anyone without Mela, so they have to stand on their own: the complete
recipe, the groups, the source, and above all **the uncertainties**. The test that matters
more than all the others is `test_the_gaps_end_up_in_the_export`: a clean PDF that hides the
estimates would be prettier and more dangerous than one that declares them.
"""

from __future__ import annotations

import pytest

from reel2recipe.documents import (
    DocumentError,
    _pdf_text,
    _xml_safe,
    write_markdown,
    write_pdf,
    to_markdown,
)
from reel2recipe.recipe import Source, Recipe, from_draft, free_path

DRAFT = {
    "title": "Tiramisù al pistacchio",
    "servings": "6 persone",
    "prep_time_min": 25,
    "ingredients": [
        {"quantity_raw": "250", "unit_raw": "g", "name": "ricotta", "group": "Per la crema"},
        {"quantity_raw": "1", "unit_raw": "cup", "name": "zucchero semolato", "group": "Per la crema"},
        {"quantity_raw": "200", "unit_raw": "g", "name": "savoiardi", "group": "Per la base"},
        {"quantity_raw": "un pizzico", "unit_raw": None, "name": "sale", "group": "Per la base"},
    ],
    "method": ["Monta i tuorli con lo zucchero.", "Componi a strati."],
    "notes": ["Riposa in frigo almeno 4 ore."],
    "confidence": {"ingredients": "alta", "method": "alta"},
    "gaps": ["Il reel non diceva quante uova."],
}


@pytest.fixture
def recipe() -> Recipe:
    return from_draft(DRAFT, source=Source.now(
        url="https://www.instagram.com/reel/ABC123/", author="cucina_test",
    ))


@pytest.fixture
def simple() -> Recipe:
    return from_draft(
        {"title": "Pasta al burro",
         "ingredients": [{"quantity_raw": "100", "unit_raw": "g", "name": "burro"}],
         "method": ["Sciogli il burro."], "confidence": {}, "gaps": []},
    )


# ----------------------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------------------


def test_markdown_has_the_complete_recipe(recipe):
    md = to_markdown(recipe)
    assert md.startswith("# Tiramisù al pistacchio")
    assert "## Ingredienti" in md and "## Procedimento" in md
    assert "- 250 g ricotta" in md
    assert "1. Monta i tuorli con lo zucchero." in md
    assert "2. Componi a strati." in md


def test_markdown_nests_the_groups_under_the_ingredients(recipe):
    """The groups are a part of the ingredients, not a section on a par with the method: they
    belong at a lower heading level."""
    md = to_markdown(recipe)
    assert "### Per la crema" in md
    assert "### Per la base" in md
    assert "## Per la crema" not in md.replace("### Per la crema", "")


def test_markdown_without_groups_invents_no_headings(simple):
    md = to_markdown(simple)
    assert "###" not in md
    assert "- 100 g burro" in md


def test_markdown_cites_the_source(recipe):
    """The method is reworded in our own words: without the pointer back to the original the
    attribution to the author would be lost (docs/legal.md)."""
    md = to_markdown(recipe)
    assert "## Fonte" in md
    assert "cucina_test" in md
    assert "https://www.instagram.com/reel/ABC123/" in md


def test_the_summary_carries_servings_and_times(recipe):
    assert "6 persone" in to_markdown(recipe)
    assert "preparazione 25 min" in to_markdown(recipe)


def test_the_gaps_end_up_in_the_export(recipe):
    """The test that matters. Whoever prints the recipe and takes it into the kitchen has to
    see both what the reel did not say and which numbers are estimates of ours, not data."""
    md = to_markdown(recipe)
    assert "## Da verificare" in md
    assert "Il reel non diceva quante uova." in md
    # "un pizzico" became 0.5 g: a number produced by us, and it has to be said.
    assert "stima" in md and "sale" in md


def test_write_markdown_does_not_overwrite(recipe, tmp_path):
    first = write_markdown(recipe, tmp_path)
    second = write_markdown(recipe, tmp_path)
    assert first != second and first.exists() and second.exists()
    assert first.read_text(encoding="utf-8").startswith("# Tiramisù")


# ----------------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------------


def test_the_pdf_is_a_valid_pdf(recipe, tmp_path):
    pytest.importorskip("reportlab", reason="the PDF export needs the «doc» extra")
    path = write_pdf(recipe, tmp_path)
    assert path.suffix == ".pdf"
    assert path.read_bytes().startswith(b"%PDF")


def test_pdf_and_markdown_share_the_same_base_name(recipe, tmp_path):
    """Three outfits of the same recipe have to be called the same thing, or finding them
    again in the export folder becomes a riddle."""
    pytest.importorskip("reportlab", reason="the PDF export needs the «doc» extra")
    assert write_pdf(recipe, tmp_path).stem == write_markdown(recipe, tmp_path).stem


def test_without_reportlab_the_error_says_what_to_do(recipe, tmp_path, monkeypatch):
    """If the extra is missing, the message has to name the command and the alternative, not
    stop at an ImportError."""
    import builtins

    real_import = builtins.__import__

    def import_refusing_reportlab(name, *args, **kwargs):
        if name.startswith("reportlab"):
            raise ImportError("simulation: reportlab not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_refusing_reportlab)
    with pytest.raises(DocumentError) as e:
        write_pdf(recipe, tmp_path)
    assert "uv sync --extra doc" in str(e.value)
    assert "markdown" in str(e.value).lower()


@pytest.mark.parametrize(
    "before, after",
    [
        ("≈ 4 g", "~ 4 g"),          # the symbol we produce most often
        ("perché", "perché"),         # accents are in Latin-1 and stay
        ("buono 🇯🇵📍 davvero", "buono davvero"),   # emoji vanish without leaving double spaces
        ("2–3 cucchiai", "2-3 cucchiai"),
    ],
)
def test_pdf_text_reduces_only_what_cannot_be_drawn(before, after):
    assert _pdf_text(before) == after


def test_xml_safe_protects_the_paragraphs():
    """reportlab reads paragraphs as mini-XML: an ingredient containing "&" would blow up the
    export instead of printing an ampersand."""
    assert _xml_safe("sale & pepe <tutto>") == "sale &amp; pepe &lt;tutto&gt;"


# ----------------------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------------------


def test_free_path_does_not_tread_on_an_earlier_export(tmp_path):
    first = free_path(tmp_path, "ricetta", ".md")
    first.write_text("first", encoding="utf-8")
    second = free_path(tmp_path, "ricetta", ".md")
    assert second.name == "ricetta-2.md"
    assert first.read_text(encoding="utf-8") == "first"


def test_the_file_name_is_readable_and_safe():
    assert from_draft({"title": "Tiramisù al pistacchio!", "ingredients": [],
                     "method": [], "confidence": {}, "gaps": []}).file_name() \
        == "tiramisu-al-pistacchio"


@pytest.mark.parametrize("language, expected", [("it", "ricetta"), ("en", "recipe")])
def test_the_file_name_falls_back_in_the_recipes_own_language(language, expected):
    """A title in a non-Latin script leaves nothing to derive a name from, and the fallback is
    the one word here we choose rather than derive. An English library should not acquire an
    Italian file in it."""
    recipe = from_draft({"title": "日本語", "ingredients": [], "method": [],
                         "confidence": {}, "gaps": []}, language=language)
    assert recipe.file_name() == expected


def test_the_english_export_translates_the_wrapper(tmp_path):
    """The wrapper — sections, attribution, footer — follows the recipe's language.

    The ingredient names do not: those come from the extraction and are not re-translated
    downstream (that would take a fresh extraction). What is checked here is what the CODE
    controls: the headings.
    """
    from reel2recipe.units import Language, System
    r = from_draft(
        {"title": "Pancakes",
         "ingredients": [{"quantity_raw": "1", "unit_raw": "cup", "name": "flour"}],
         "method": ["Mix everything."], "confidence": {},
         "gaps": ["the reel did not say how many eggs"]},
        source=Source.now(url="https://x/y", author="baker"),
        language=Language.EN, system=System.IMPERIAL,
    )
    md = to_markdown(r)
    assert "## Ingredients" in md and "## Method" in md
    assert "## To check" in md and "## Source" in md
    assert "Recipe by baker" in md
    # And the imperial system: 1 cup of flour stays 1 cup, not 120 g.
    assert "1 cup flour" in md
    # No Italian heading has survived.
    assert "Ingredienti" not in md and "Procedimento" not in md


def test_the_italian_export_stays_italian(recipe):
    """The default must not be disturbed by the multilingual work: ask for nothing, get
    everything in Italian."""
    md = to_markdown(recipe)
    assert "## Ingredienti" in md and "## Procedimento" in md
    assert "Ingredients" not in md
