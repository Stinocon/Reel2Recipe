"""A gate on the local model's behaviour: does it honour the "invent nothing" rule?

Why it exists. Reel2Recipe's quality does not depend on our code alone: it also depends on how
far the local model honours the prompt. Trying a real reel turned up that
`qwen2.5:7b-instruct`, faced with a list of ingredients with no amounts ("Salsa: soia, mirin e
dashi"), **handed out plausible amounts** — "1 tazza" of soy sauce that nobody had ever
written. It is the worst possible failure for this project: an invented number the user does
not know is invented. It is the golden rule "invent nothing" (see docs/architettura.md) put to
the test against the model actually installed. The default model, `qwen2.5:14b`, does not do
it.

That defect was found by chance. This test makes sure luck is no longer required.

It does not run by default: it needs Ollama up and costs anything from tens of seconds to a
few minutes, so it is not on `./check.sh`'s path. It is launched deliberately, after touching
`extract.py`'s prompt or changing the default model:

    R2R_TEST_MODELLO=1 uv run pytest tests/test_modello.py -v

`R2R_MODELLO` tries a specific model instead of the default:

    R2R_TEST_MODELLO=1 R2R_MODELLO=qwen2.5:7b-instruct uv run pytest tests/test_modello.py -v

**Being opt-in has already cost something.** During the migration to English a mechanical
rename of the keyword arguments reached this file too, and it started calling
`extract_draft(transcript=…)` when the parameter did not yet exist. The suite could not
notice — this module is skipped without `R2R_TEST_MODELLO` — so the test that protects the
project's central promise sat uncallable for two commits. Run it in the same session you
touch it, even by accident.
"""

from __future__ import annotations

import os

import pytest

from reel2recipe import extract

# A caption built on purpose: one ingredient WITH its amount and three groups WITHOUT. It is
# the shape authors really write in, and it is the trap a small model falls into.
CAPTION = """\
Yaki Udon, pronti in 10 minuti netti!

🥣 INGREDIENTI:
Udon precotti
80g di Maiale (fettina grassa)
Verdure: Cipolla, Carote e Cavolo Cappuccio
Salsa: Soia, Mirin e Dashi in polvere

PROCEDIMENTO:
Taglia le verdure, rosola il maiale, aggiungi gli udon e la salsa. Salta tutto.
"""

# The ingredients that have NO amount at all in the caption. For each of them the model has to
# leave quantity and unit empty and declare the gap, not fill them in by intuition.
WITHOUT_AMOUNT = ("cipolla", "carote", "cavolo", "soia", "mirin", "dashi", "udon")


def _without_ollama() -> bool:
    return not extract.ollama_up()


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("R2R_TEST_MODELLO") != "1",
        reason="model gate: slow and needs Ollama. Enable it with R2R_TEST_MODELLO=1",
    ),
    pytest.mark.skipif(_without_ollama(), reason="Ollama is not answering"),
]


@pytest.fixture(scope="module")
def draft() -> dict:
    """One extraction for the whole module: it is the slow part."""
    return extract.extract_draft(
        caption=CAPTION,
        transcript="",
        title="Yaki Udon",
        model=os.environ.get("R2R_MODELLO"),
    ).draft


def _ingredients_without_amount(draft: dict) -> list[dict]:
    return [
        i for i in (draft.get("ingredienti") or [])
        if any(word in (i.get("nome") or "").lower() for word in WITHOUT_AMOUNT)
    ]


def test_it_does_not_invent_the_missing_amounts(draft):
    """The test that matters. A list with no amounts has to stay with no amounts.

    What is checked is the appearance of a **number**, which is the real damage: a plausible
    weight the cook does not know was invented. A word that ended up in `unita_raw` by mistake
    (the 14b sends "polvere" for "Dashi in polvere") is not this problem, and is already
    neutralised downstream by `units.py`, which renders it as a note in brackets rather than
    as a unit.

    If this goes red, the model in use is not reliable for the job: do not "fix" the test —
    change model or strengthen the prompt.
    """
    invented = [
        (i.get("nome"), i.get("quantita_raw"), i.get("unita_raw"))
        for i in _ingredients_without_amount(draft)
        if any(c.isdigit() for c in f"{i.get('quantita_raw') or ''} {i.get('unita_raw') or ''}")
    ]
    assert not invented, (
        "the model invented quantities for ingredients that had none in the caption: "
        f"{invented}. It is a violation of rule 2 of the prompt: invent nothing."
    )


def test_it_reports_the_amount_that_was_there(draft):
    """The mirror of the previous one: caution must not become blindness. The pork's 80 g are
    written down, and they have to come out — raw, not converted."""
    pork = [i for i in (draft.get("ingredienti") or []) if "maiale" in (i.get("nome") or "").lower()]
    assert pork, "the pork has vanished from the extraction"
    raw = f"{pork[0].get('quantita_raw') or ''} {pork[0].get('unita_raw') or ''}".lower()
    assert "80" in raw, f"the stated amount was not reported: {raw!r}"
    # The model must not convert: 80 g do not become cups, ounces or anything else (§3).
    assert not any(u in raw for u in ("cup", "oz", "once")), f"the model converted: {raw!r}"


def test_it_declares_the_gaps(draft):
    """Inventing nothing is not enough: the hole also has to be declared, or the user does not
    know it is there."""
    assert (draft.get("lacune") or []), "no gap declared despite three groups without amounts"


def test_it_recognises_the_groups_written_with_a_colon(draft):
    """"Verdure:", "Salsa:" are how captions really group things. Less critical than the
    previous ones — a missed group is a degradation, not a danger."""
    groups = {(i.get("gruppo") or "").strip().lower() for i in (draft.get("ingredienti") or [])}
    assert {"verdure", "salsa"} & groups, f"no group recognised: {groups}"


# ----------------------------------------------------------------------------------
# The model's output language
# ----------------------------------------------------------------------------------

# Material in English, to check the translation towards Italian — the reliable direction. The
# opposite direction (long IT input → EN output) is a known limit of qwen2.5:14b, which stays
# anchored to Italian: that is the model's reliability, not the code's, and it is not gated.
CAPTION_EN = """\
Quick Carbonara!
INGREDIENTS:
200g spaghetti
2 eggs
100g pancetta
Sauce: pecorino, black pepper
METHOD: Fry the pancetta, mix the eggs with pecorino, combine off the heat.
"""


@pytest.fixture(scope="module")
def italian_draft_from_english() -> dict:
    return extract.extract_draft(
        caption=CAPTION_EN, transcript="", title="Carbonara",
        model=os.environ.get("R2R_MODELLO"), language="it",
    ).draft


def test_it_translates_towards_italian(italian_draft_from_english):
    """An English reel asked for in Italian has to come out in Italian: it is the case of the
    Italian user watching an American video, the commonest one for this project."""
    names = " ".join((i.get("nome") or "").lower()
                     for i in (italian_draft_from_english.get("ingredienti") or []))
    # At least one clearly translated term: "eggs" -> "uova", "black pepper" -> "pepe".
    assert "uova" in names or "pepe" in names, f"names not translated into Italian: {names}"


# ----------------------------------------------------------------------------------
# The four defects found on real reels
# ----------------------------------------------------------------------------------
#
# Six extractions on real material (09/08/2026) produced four defects. We had found them only
# because somebody was watching: no test covered `extract.py`'s prompt and schema, so a future
# change putting `porzioni` back among the optional fields, or weakening the instruction about
# `null`, would have turned nothing red.
#
# The caption below is **synthetic**, written on purpose: it reproduces the four patterns
# without bringing third-party material into the repo (see docs/legale.md). The checks look at
# the RESULT of the whole chain, not at the model's internal choices: the same amount may
# arrive as "1¼"+"cups" or as "300"+"ml" and either is fine — what must not happen is that it
# becomes one millilitre.

AMBIGUOUS_CAPTION = """\
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
def ambiguous_recipe():
    """One extraction, carried all the way down the chain: it is the result that counts."""
    from reel2recipe.recipe import Source, from_draft

    draft = extract.extract_draft(
        caption=AMBIGUOUS_CAPTION, transcript="", title="Torta di mele",
        model=os.environ.get("R2R_MODELLO"),
    ).draft
    return draft, from_draft(draft, source=Source.now(url=None, author="test"))


def _ingredient(recipe, word):
    for i in recipe.ingredients:
        if word in i.name.lower():
            return i
    return None


def test_an_amount_written_twice_does_not_become_one_millilitre(ambiguous_recipe):
    """The worst defect found: "1¼ cups (300 ml)" produced "1 ml" of water, declared as
    certain. It does not matter which of the two representations the model picks — both have
    to lead to the same place."""
    _, recipe = ambiguous_recipe
    milk = _ingredient(recipe, "latte")
    assert milk, "the milk has vanished from the extraction"
    assert milk.quantity.unit == "ml", f"the milk is not a volume: {milk.mela_line()!r}"
    assert 250 <= milk.quantity.value <= 350, (
        f"the milk should have stayed around 300 ml, it came out as {milk.mela_line()!r}"
    )


def test_servings_and_cooking_time_cannot_be_omitted(ambiguous_recipe):
    """They were optional in the schema and the model omitted them ALWAYS, even when the source
    stated them. If this goes red again, look at `required` in extract.py before the prompt."""
    _, recipe = ambiguous_recipe
    assert recipe.servings and "6" in recipe.servings, f"servings: {recipe.servings!r}"
    assert recipe.cook_time_min == 40, f"cooking time: {recipe.cook_time_min!r}"


def test_the_preparation_time_is_not_invented(ambiguous_recipe):
    """The caption states only the cooking time. Made required, the field was filled with a
    plausible number — and by splitting a cooking range across the two fields."""
    _, recipe = ambiguous_recipe
    assert recipe.prep_time_min is None, (
        f"prep time invented: {recipe.prep_time_min!r} (the source does not state it)"
    )


def _raw(draft: dict, word: str) -> dict | None:
    for i in draft.get("ingredienti") or []:
        if word in (i.get("nome") or "").lower():
            return i
    return None


@pytest.mark.parametrize("word, expression", [("sale", "q.b"), ("cannella", "pizzico")])
def test_a_vague_measure_received_does_not_become_a_false_gap(ambiguous_recipe, word, expression):
    """The model puts "q.b." and "un pizzico" more or less wherever it likes — in the name, in
    brackets within the name, in the notes — and the code saw no indication at all: it declared
    "quantity not given in the reel", which is false. A gap that lies is worth less than no gap.

    The check concerns **what we can control**: if the expression arrived in any field at all,
    it has to become an open-ended quantity or an estimate. When the model **loses it on the
    way** — it happens, and it is its defect, not ours — there is nothing to recover, and
    asserting it would make this gate flaky instead of informative. In that case the test skips
    while saying why, so the information is not lost.
    """
    from reel2recipe.units import Provenance

    draft, recipe = ambiguous_recipe
    raw = _raw(draft, word)
    assert raw, f"«{word}» has vanished from the extraction"

    fields = " ".join(str(raw.get(c) or "") for c in ("nome", "quantita_raw", "unita_raw", "note"))
    # The dots are stripped from BOTH sides: "q.b." is impossible to tokenise reliably, and
    # normalising only the text being searched for produced a false skip.
    if expression.replace(".", "") not in fields.lower().replace(".", ""):
        pytest.skip(
            f"the model did not report «{expression}» for «{word}» in any field "
            f"({fields!r}): that is a loss by the model, not a defect of the normalisation"
        )

    ingr = _ingredient(recipe, word)
    assert ingr and ingr.quantity.provenance in {
        Provenance.INDETERMINATE, Provenance.ESTIMATED_VAGUE
    }, (
        f"«{word}»: the model had reported the indication ({fields!r}) but it came out as "
        f"{ingr.quantity.provenance.value} ({ingr.mela_line()!r})"
    )


def test_a_word_in_brackets_does_not_become_a_unit(ambiguous_recipe):
    """"1 mela grande (facoltativa)" gave "1 (facoltativa) mela"."""
    _, recipe = ambiguous_recipe
    apple = _ingredient(recipe, "mela")
    assert apple, "the apple has vanished from the extraction"
    assert not (apple.quantity.unit or "").startswith("("), (
        f"a bracket was mistaken for a unit: {apple.mela_line()!r}"
    )
