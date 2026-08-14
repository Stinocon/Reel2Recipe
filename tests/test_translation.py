"""The translation pass, tested without Ollama.

The model gate in `test_modello.py` answers "does the local model translate well?", which is
slow, opt-in and about the model. These tests answer the questions that are about **our code**
and that hold whatever the model does: what we send it, what we do with what comes back, and
what happens when it comes back wrong.

The most important one is the first: the amounts are not in the payload. Everything else here
protects a recipe from being lost; that one protects it from being silently wrong, which is
the failure this project exists to avoid (AGENTS.md §3, §4).
"""

from __future__ import annotations

import pytest

from reel2recipe import extract


def _draft() -> dict:
    return {
        "title": "Yaki Udon",
        "description": "Un salto in padella veloce.",
        "servings": "2 persone",
        "method": ["Taglia le verdure.", "Rosola il maiale."],
        "notes": ["Meglio con udon freschi."],
        "categories": ["Primi"],
        "gaps": ["quantità non indicata per «cipolla»"],
        "ingredients": [
            # In the glossary: the code settles this one and the model never sees the word.
            {"name": "Cipolla", "notes": "affettata", "group": "Verdure",
             "quantity_raw": "250", "unit_raw": "g"},
            # Not in the glossary: this is the half that still depends on the model, and the
            # half whose fate the failure-path tests below are about.
            {"name": "Guarnizione di casa mia", "notes": None, "group": None,
             "quantity_raw": "80", "unit_raw": "g"},
        ],
    }


# ----------------------------------------------------------------------------------
# What we send
# ----------------------------------------------------------------------------------


def test_no_amount_ever_enters_the_translation_payload():
    """The rule the whole design rests on: the model handles words, the code handles numbers.

    It is enforced by **not offering** the numbers rather than by asking the model to leave
    them alone. A prompt rule can be forgotten halfway through a long list; a field that is
    not in the payload cannot be reworded, rounded or converted.
    """
    texts, _ = extract._collect(_draft())
    joined = " ".join(texts)

    assert "250" not in joined and "80" not in joined, (
        f"an amount reached the translation payload: {texts}"
    )
    # And the unit with it: "g" as a whole word must not be in there either.
    assert " g " not in f" {joined} ", f"a unit reached the translation payload: {texts}"


def test_the_payload_carries_every_field_a_person_reads():
    """The opposite risk: translating so little that the card comes out half in each language.

    `gaps` is in the list on purpose. A gap is a sentence the user reads on the card, and an
    Italian gap under an English recipe is exactly the seam this pass exists to remove.
    """
    texts, _ = extract._collect(_draft())

    for expected in ("Yaki Udon", "Un salto in padella veloce.", "2 persone", "Cipolla",
                     "affettata", "Verdure", "Taglia le verdure.", "Meglio con udon freschi.",
                     "Primi", "quantità non indicata per «cipolla»"):
        assert expected in texts, f"«{expected}» is not being translated"


def test_the_answer_goes_back_where_it_came_from():
    """The paths are collected alongside the texts, so putting the answer back cannot drift
    out of step with what was asked."""
    draft = _draft()
    texts, paths = extract._collect(draft)
    back = extract._put_back(draft, paths, [t.upper() for t in texts])

    assert back["title"] == "YAKI UDON"
    assert back["ingredients"][0]["name"] == "CIPOLLA"
    assert back["ingredients"][0]["group"] == "VERDURE"
    assert back["method"][1] == "ROSOLA IL MAIALE."
    # And the fields that never travelled are untouched.
    assert back["ingredients"][0]["quantity_raw"] == "250"
    assert back["ingredients"][1]["unit_raw"] == "g"


# ----------------------------------------------------------------------------------
# What comes back
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("returned, expected", [
    ("1. Cooked udon noodles", "Cooked udon noodles"),
    ("12) Sauce", "Sauce"),
    ("Onion", "Onion"),
    ("180 °C for 25 minutes", "180 °C for 25 minutes"),
    ("2 eggs", "2 eggs"),
])
def test_the_echoed_list_number_is_stripped(returned, expected):
    """The model echoes the number it was given back into the text often enough that the
    prompt rule is not sufficient. Taking it off in code is not a guess: we prefixed it.

    The two last cases are the ones that must survive: a fragment that legitimately starts
    with a number is not an enumeration, and eating it would corrupt a real value.
    """
    assert extract._ENUMERATION.sub("", returned) == expected


def _answering(payload: str):
    """A stand-in for Ollama that returns exactly `payload` as the model's message."""
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": payload}}
    return lambda *a, **k: Response()


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(extract, "choose_model", lambda *a, **k: "stub")
    return monkeypatch


def test_a_short_answer_keeps_the_recipe_and_declares_the_gap(offline):
    """A different number of lines makes the mapping back guesswork, and guessing here would
    put one ingredient's name onto another.

    So the original is kept whole and the failure is **declared**: an Italian recipe is worth
    far more than no recipe, and far more than a recipe whose ingredients have quietly swapped
    names. The user is told rather than left to notice.
    """
    offline.setattr(extract.httpx, "post", _answering('{"translations": ["only one"]}'))
    out = extract.translate_draft(_draft(), language="en")

    # The glossary ran before the call, so its work survives the failure: the ingredient it
    # knew is in English even though the model gave nothing usable.
    assert out["ingredients"][0]["name"] == "Onions"
    # The one it did not know keeps its original wording rather than a guess.
    assert out["ingredients"][1]["name"] == "Guarnizione di casa mia"
    assert out["ingredients"][0]["quantity_raw"] == "250"
    assert any("translation" in g for g in out["gaps"]), out["gaps"]


@pytest.mark.parametrize("payload", ["not json at all", "", '{"wrong_key": []}'])
def test_an_unusable_answer_never_costs_the_recipe(offline, payload):
    """Whatever comes back, the recipe survives it. The three shapes are the ones actually
    seen from a local model under load: prose instead of JSON, an empty body, and valid JSON
    with the wrong shape."""
    offline.setattr(extract.httpx, "post", _answering(payload))
    out = extract.translate_draft(_draft(), language="it")

    assert out["ingredients"][1]["name"] == "Guarnizione di casa mia"
    assert out["title"] == "Yaki Udon"
    assert any("traduzione" in g for g in out["gaps"]), out["gaps"]


def test_the_gap_is_declared_in_the_language_the_user_is_reading(offline):
    """The gap goes on the card, so it follows the recipe's language like every other gap."""
    offline.setattr(extract.httpx, "post", _answering("junk"))

    assert any("traduzione" in g for g in extract.translate_draft(_draft(), language="it")["gaps"])
    assert any("translation" in g for g in extract.translate_draft(_draft(), language="en")["gaps"])


def test_the_original_draft_is_never_mutated(offline):
    """The caller keeps a usable draft whatever happens in here: the pass works on a copy."""
    offline.setattr(extract.httpx, "post", _answering('{"translations": ["x"]}'))
    draft = _draft()
    extract.translate_draft(draft, language="en")

    assert draft["gaps"] == ["quantità non indicata per «cipolla»"]
    assert draft["title"] == "Yaki Udon"


def test_nothing_to_translate_costs_no_call(offline):
    """An empty draft must not reach the network at all."""
    def explode(*a, **k):
        raise AssertionError("the model was called with nothing to translate")
    offline.setattr(extract.httpx, "post", explode)

    assert extract.translate_draft({"ingredients": []}, language="en") == {"ingredients": []}


# ----------------------------------------------------------------------------------
# Whether to translate at all
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("Taglia le verdure a pezzetti, poi rosola il maiale con la salsa di soia.", "it"),
    ("Monta i tuorli con lo zucchero e aggiungi il mascarpone alla crema.", "it"),
    ("Cut the vegetables into pieces, then fry the pork with the soy sauce.", "en"),
    ("Whisk the eggs with the pecorino and plenty of black pepper until smooth.", "en"),
    # Too short to judge, and content words that belong to both languages. `None` is the
    # honest answer: the caller translates anyway, which is the safe direction.
    ("pasta pancetta pesto risotto", None),
    ("", None),
])
def test_the_language_detector_reads_function_words(text, expected):
    """It counts the words that cannot be the other language — `della`, `con`, `the`, `with` —
    and not the content words, because half a kitchen's vocabulary is the same in both."""
    assert extract.language_of(text) == expected


def test_the_same_language_never_pays_for_a_translation_pass():
    """An Italian reel wanted in Italian is the common case, and the one that must not get
    slower. It is also the user's own framing: there is no translation question there."""
    italian = "Taglia le verdure a pezzetti e rosola il maiale con la salsa di soia."
    assert extract.needs_translation(italian, {}, "it") is False

    english = "Cut the vegetables into pieces and fry the pork with the soy sauce."
    assert extract.needs_translation(english, {}, "en") is False


def test_a_different_language_always_does():
    italian = "Taglia le verdure a pezzetti e rosola il maiale con la salsa di soia."
    assert extract.needs_translation(italian, {}, "en") is True

    english = "Cut the vegetables into pieces and fry the pork with the soy sauce."
    assert extract.needs_translation(english, {}, "it") is True


def test_a_draft_translated_only_halfway_still_triggers_the_pass():
    """The reason the decision is made on the material and not on the draft.

    The model often translates the ingredient names and leaves the group headings behind. A
    draft that is 90% English reads as "already translated" to any whole-text check, and the
    Italian headings would ship. Asking the material instead makes the answer independent of
    how well the first pass happened to do.
    """
    english_material = "Fry the pancetta until crisp and whisk the eggs with the pecorino."
    half_translated = {
        "method": ["Frigg the pancetta until crisp."],
        "ingredients": [{"name": "Uova", "group": "Salsa"}],
    }
    assert extract.needs_translation(english_material, half_translated, "it") is True


def test_material_too_short_to_judge_falls_back_to_the_draft():
    """A three-word caption with no transcript gives the detector nothing. The draft is the
    fallback, and if that is unreadable too the answer is "translate": a needless pass costs
    seconds, a skipped one costs a recipe in the wrong language."""
    assert extract.needs_translation("Pasta!", {"method": []}, "en") is True

    already_english = {"method": ["Cut the vegetables into pieces and fry the pork with it."]}
    assert extract.needs_translation("Pasta!", already_english, "en") is False


def test_an_empty_fragment_does_not_delete_the_original(offline):
    """The model sometimes drops a line and returns "" in its place, with the right count.

    The count check does not catch that, and taking the empty string would delete an
    ingredient's name outright — leaving a row on the card with an amount and nothing to put
    it against. One word left in the source language is a far smaller harm.
    """
    draft = _draft()
    texts, _ = extract._collect(draft)
    answer = [""] * len(texts)
    answer[0] = "Yaki Udon"          # only the title comes back
    offline.setattr(extract.httpx, "post",
                    _answering('{"translations": %s}' % __import__("json").dumps(answer)))

    out = extract.translate_draft(draft, language="en")
    assert out["ingredients"][1]["name"] == "Guarnizione di casa mia", (
        "an empty answer deleted the name"
    )
    # The heading was settled by the glossary before the call, so it is English regardless of
    # what the model did or did not return.
    assert out["ingredients"][0]["group"] == "Vegetables"
    assert out["method"] == ["Taglia le verdure.", "Rosola il maiale."]


def test_a_repeated_fragment_is_sent_once_and_answered_once(offline):
    """A group heading occurs once per ingredient, and asking three times invites three
    answers. "Sauce" coming back as "Salsa" on one row and "Sugo" on the next splits one group
    into two on the card: a structural defect produced by a translation.

    So identical fragments are sent once and the single answer is used at every occurrence —
    which makes the consistency a property of the code rather than of the model's mood.
    """
    import json as _json
    sent = {}

    def capture(*a, **k):
        sent["body"] = k["json"]["messages"][1]["content"]
        lines = sent["body"].splitlines()
        class Response:
            def raise_for_status(self): pass
            def json(self):
                answer = [f"T{n}" for n in range(len(lines))]
                return {"message": {"content": _json.dumps({"translations": answer})}}
        return Response()

    offline.setattr(extract.httpx, "post", capture)
    # Headings the glossary does NOT know, on purpose: the ones it knows never reach the
    # model, so they could not test what happens to a repeated fragment that does.
    draft = {
        "ingredients": [
            {"name": "Pecorino", "group": "For my mother's sauce",
             "quantity_raw": "50", "unit_raw": "g"},
            {"name": "Pepper", "group": "For my mother's sauce",
             "quantity_raw": "", "unit_raw": ""},
            {"name": "Parsley", "group": "For the fancy bit",
             "quantity_raw": "", "unit_raw": ""},
        ],
    }
    out = extract.translate_draft(draft, language="it")

    assert sent["body"].count("For my mother's sauce") == 1, (
        f"the repeated heading was sent more than once:\n{sent['body']}"
    )
    groups = [i["group"] for i in out["ingredients"]]
    assert groups[0] == groups[1], f"one group came back as two: {groups}"
    assert groups[2] != groups[0], f"two groups collapsed into one: {groups}"


# ----------------------------------------------------------------------------------
# The glossary: what the code settles before the model is asked
# ----------------------------------------------------------------------------------


def test_a_name_the_glossary_knows_never_reaches_the_model(offline):
    """The reason this file exists at all.

    `maiale` came back from qwen2.5:14b as "bacon" and `cavolo cappuccio` as "chinese
    broccoli" — not a clumsy translation but a **different ingredient**, stated with
    confidence and invisible on the card. A name the table knows is therefore settled in code
    and is not in the payload: you cannot mistranslate what you were not asked about.
    """
    sent = {}

    def capture(*a, **k):
        sent["body"] = k["json"]["messages"][1]["content"]
        class Response:
            def raise_for_status(self): pass
            def json(self):
                import json as j
                n = len(sent["body"].splitlines())
                return {"message": {"content": j.dumps({"translations": ["x"] * n})}}
        return Response()

    offline.setattr(extract.httpx, "post", capture)
    draft = {"ingredients": [
        {"name": "Cavolo Cappuccio", "quantity_raw": "", "unit_raw": ""},
        {"name": "Maiale", "quantity_raw": "80", "unit_raw": "g"},
    ]}
    out = extract.translate_draft(draft, language="en")

    assert [i["name"] for i in out["ingredients"]] == ["Cabbage", "Pork"]
    # Both names were in the table, so there was nothing left to ask about and the model was
    # not called at all. A draft of known ingredients is translated without a network round
    # trip — which is the strongest form of "the model cannot get this wrong".
    assert "body" not in sent, (
        f"the model was called although the glossary had settled everything:\n{sent['body']}"
    )


def test_a_known_name_is_kept_out_of_the_payload_when_the_model_is_still_needed(offline):
    """The same, when there *is* something else to translate: the settled name must not travel
    with it. Sending it would hand the model the finished answer and a chance to undo it."""
    sent = {}

    def capture(*a, **k):
        sent["body"] = k["json"]["messages"][1]["content"]
        class Response:
            def raise_for_status(self): pass
            def json(self):
                import json as j
                n = len([l for l in sent["body"].splitlines() if l and l[0].isdigit()])
                return {"message": {"content": j.dumps({"translations": ["x"] * n})}}
        return Response()

    offline.setattr(extract.httpx, "post", capture)
    draft = {
        "method": ["Taglia le verdure."],
        "ingredients": [{"name": "Cavolo Cappuccio", "quantity_raw": "", "unit_raw": ""}],
    }
    out = extract.translate_draft(draft, language="en")

    assert out["ingredients"][0]["name"] == "Cabbage"
    assert "Cavolo" not in sent["body"], (
        f"a name the glossary had settled was still sent:\n{sent['body']}"
    )
    assert "Taglia le verdure." in sent["body"], "the method should still have been sent"


def test_a_name_the_glossary_knows_only_in_part_is_pinned_not_replaced(offline):
    """"Maiale (fettina grassa)" carries something the table does not: the cut.

    Replacing the whole name with "pork" would drop it, so the name goes to the model — but
    the term the table is sure of goes with it as a fixed translation. The model renders the
    modifier and does not get to reconsider the ingredient.
    """
    sent = {}

    def capture(*a, **k):
        sent["body"] = k["json"]["messages"][1]["content"]
        class Response:
            def raise_for_status(self): pass
            def json(self):
                import json as j
                n = len([l for l in sent["body"].splitlines() if l and l[0].isdigit()])
                return {"message": {"content": j.dumps({"translations": ["x"] * n})}}
        return Response()

    offline.setattr(extract.httpx, "post", capture)
    draft = {"ingredients": [{"name": "Maiale (fettina grassa)",
                              "quantity_raw": "80", "unit_raw": "g"}]}
    extract.translate_draft(draft, language="en")

    assert "Maiale (fettina grassa)" in sent["body"], "the modifier was dropped"
    assert "maiale -> pork" in sent["body"].lower(), (
        f"the known term was not pinned:\n{sent['body']}"
    )


@pytest.mark.parametrize("name, quantity, expected", [
    ("uova", None, "eggs"),
    ("uovo", "1", "egg"),
    ("uova", "3", "eggs"),
    ("carote", None, "carrots"),
    ("carota", "1", "carrot"),
    # A mass noun has no plural and needs none, whatever the amount says.
    ("farina", "250", "flour"),
    ("sale", None, "salt"),
])
def test_the_glossary_agrees_with_the_number(name, quantity, expected):
    """"2 uovo" and "3 carrot" make a card look machine-made, and the number is right there in
    `quantity_raw`. No amount takes the plural too: a bare list line is a list of kinds."""
    from reel2recipe.units import load_tables
    found = load_tables().ingredient_name(name, "en", quantity)
    assert found is not None, f"«{name}» is not in the glossary"
    assert found[0] == expected


def test_the_glossary_does_not_reach_past_what_it_knows():
    """An ingredient the table has never heard of returns nothing, and the model handles it.

    This is the same contract as an unknown density: the table answers for what it holds and
    says nothing about the rest. A glossary that guessed would be the defect it exists to stop.
    """
    from reel2recipe.units import load_tables
    assert load_tables().ingredient_name("guarnizione di casa mia", "en") is None


def test_the_longest_entry_wins():
    """"cavolo nero" is not a kind of "cavolo": it is a different vegetable, and the shorter
    entry must not swallow it. Same rule as the density lookup."""
    from reel2recipe.units import load_tables
    tables = load_tables()
    assert tables.ingredient_name("cavolo nero", "en")[0] == "cavolo nero"
    assert tables.ingredient_name("cavolo cappuccio", "en")[0] == "cabbage"


def test_a_group_heading_the_glossary_knows_never_reaches_the_model(offline):
    """The last thing the measurement showed the model getting wrong.

    From English into Italian it rendered "Sauce" as "Salsa" and left "Garnish" in English —
    on the same card, so one recipe came out half in each language. A heading is a short,
    closed vocabulary: there is no reason to ask.
    """
    sent = {}

    def capture(*a, **k):
        sent["body"] = k["json"]["messages"][1]["content"]
        class Response:
            def raise_for_status(self): pass
            def json(self):
                import json as j
                n = len([l for l in sent["body"].splitlines() if l and l[0].isdigit()])
                return {"message": {"content": j.dumps({"translations": ["x"] * n})}}
        return Response()

    offline.setattr(extract.httpx, "post", capture)
    draft = {
        "method": ["Fry the pancetta."],
        "ingredients": [
            {"name": "Pecorino", "group": "Sauce", "quantity_raw": "", "unit_raw": ""},
            {"name": "Parsley", "group": "Garnish", "quantity_raw": "", "unit_raw": ""},
        ],
    }
    out = extract.translate_draft(draft, language="it")

    assert [i["group"] for i in out["ingredients"]] == ["Per la salsa", "Per guarnire"]
    assert "Sauce" not in sent["body"] and "Garnish" not in sent["body"], (
        f"a heading the glossary knows was still sent:\n{sent['body']}"
    )


@pytest.mark.parametrize("original, expected", [
    ("Cipolla", "Onions"),
    ("cipolla", "onions"),
    ("CIPOLLA", "Onions"),
])
def test_the_glossary_keeps_the_capitalisation_it_was_given(offline, original, expected):
    """The table holds one spelling, lower case; the model capitalises as it sees fit.

    Emitting both untouched gave a card reading "Cooked udon / onions / Soy sauce" — the seam
    between the deterministic half of the translation and the model's half, visible to anyone
    and explainable to no one.
    """
    offline.setattr(extract.httpx, "post", _answering('{"translations": []}'))
    draft = {"ingredients": [{"name": original, "quantity_raw": "", "unit_raw": ""}]}
    out = extract.translate_draft(draft, language="en")
    assert out["ingredients"][0]["name"] == expected


# ----------------------------------------------------------------------------------
# The words a model writes when it means nothing
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("written", ["null", "None", "NULL", "n/a", "nessuno", "  none  "])
def test_a_word_meaning_nothing_becomes_nothing(written):
    """Seen on qwen2.5:14b: `servings` came back as the string "null".

    The schema types it as a string and tells the model that a missing yield is the empty
    string — but `prep_time_min` sits right next to it accepting a real `null`, and the model
    sometimes reaches for the word. `from_draft` does `draft.get("servings") or None`, and
    "null" is truthy, so it reached the card: a recipe announcing it serves "null".

    It is a small thing that makes the whole card untrustworthy, which is the category this
    project cares about most.
    """
    cleaned = extract._clean_up({"title": "X", "servings": written, "method": [], "notes": [],
                                 "ingredients": []})
    assert cleaned["servings"] is None


@pytest.mark.parametrize("kept", ["q.b.", "2 persone", "Nessuno di questi", "None pizza"])
def test_a_real_value_that_merely_contains_such_a_word_survives(kept):
    """Matched whole and case-insensitively, never as a substring. "q.b." is a real answer,
    and a phrase that happens to start with "nessuno" is a phrase, not an absence."""
    cleaned = extract._clean_up({"title": "X", "servings": kept, "method": [], "notes": [],
                                 "ingredients": []})
    assert cleaned["servings"] == kept


def test_a_group_heading_is_normalised_even_when_nothing_is_translated():
    """The path with no translation to hide behind.

    The model writes the same section as `base` on one run and `Per la base` on the next, and
    both are right enough that nothing flags them — two recipes in one library, headed
    differently for the same thing. `translate_draft` already settles it, but only runs when
    the material is not already in the language asked for, so an Italian reel wanted in
    Italian never got normalised at all.
    """
    from reel2recipe.recipe import from_draft

    draft = {"title": "Tiramisu", "method": ["Monta i tuorli."], "ingredients": [
        {"name": "savoiardi", "group": "base", "quantity_raw": "200", "unit_raw": "g"},
        {"name": "cacao", "group": "copertura", "quantity_raw": "", "unit_raw": ""},
    ]}
    assert [i.group for i in from_draft(draft, language="it").ingredients] == \
           ["Per la base", "Per la copertura"]


def test_a_heading_the_table_does_not_know_is_left_alone():
    """There is no house style to impose on "Per la crema al limone", and inventing one would
    be a worse defect than the inconsistency it fixed."""
    from reel2recipe.recipe import from_draft

    draft = {"title": "T", "method": ["x"], "ingredients": [
        {"name": "crema", "group": "Per la crema al limone", "quantity_raw": "", "unit_raw": ""},
    ]}
    assert from_draft(draft, language="it").ingredients[0].group == "Per la crema al limone"


def test_an_ingredient_with_no_group_stays_without_one():
    """Normalising must not turn "no section" into a section."""
    from reel2recipe.recipe import from_draft

    draft = {"title": "T", "method": ["x"], "ingredients": [
        {"name": "farina", "group": "", "quantity_raw": "500", "unit_raw": "g"},
        {"name": "sale", "quantity_raw": "10", "unit_raw": "g"},
    ]}
    assert [i.group for i in from_draft(draft, language="it").ingredients] == [None, None]
