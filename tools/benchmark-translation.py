"""A repeatable measurement of extraction + translation, in every language combination.

It exists because "the translation is unreliable" is not a number, and without a number no
change to the pipeline can be claimed as an improvement. Run it **before** a change and
**after**, on the same material:

    uv run python tools/benchmark-translation.py 2

It is not a gate and does not belong on `./check.sh`'s path: it prints numbers, it does not
pass or fail. The pass/fail half lives in `tests/test_modello.py`, which holds the outcomes
this measurement established. Reach for this one when touching `extract.py`'s prompts, the
translation pass, or the default model — the three things that move these numbers.

It is also the reason the two-pass split exists at all. The first version of this file scored
100% on both directions and measured a problem that was not there: the caption it used was
rich prose, and the failure only appears on **list-shaped** captions. Adding `CAPTION_IT_LIST`
turned a vague complaint into 0%, which is a thing you can fix and then show fixed.

What it scores, per case:

  language   how many of the terms that MUST change language actually did. Each term carries
             the forms that count as correct, so "eggs" -> "uova" passes and "eggs" fails.
             This is the axis the two-pass change is meant to move.
  amounts    the stated amounts are still there and still raw. This is the axis that must NOT
             move: it is the project's central promise, and a translation change that improves
             the words while disturbing the numbers is a regression, not a win.
  groups     the ingredient groups survived, and their names are in the target language.

Usage:  uv run python benchmark.py [runs]
"""
from __future__ import annotations

import json
import sys
import time

from reel2recipe import extract

# --------------------------------------------------------------------------------------
# Material. Written in the shape captions really have — amounts inline, groups by colon,
# promotional noise — but authored here, so no third-party text enters the repo.
# --------------------------------------------------------------------------------------

CAPTION_IT = """\
Tiramisu della nonna, pronto in 20 minuti!

INGREDIENTI:
250 g mascarpone
3 uova
100 g zucchero semolato
Per la base: 200 g savoiardi, caffe' amaro q.b.
Per la copertura: cacao amaro

PROCEDIMENTO:
Monta i tuorli con lo zucchero, aggiungi il mascarpone. Bagna i savoiardi nel caffe'.
Alterna gli strati e spolvera di cacao. Riposa in frigo un'ora.
"""

CAPTION_EN = """\
Weeknight Carbonara, 15 minutes flat!

INGREDIENTS:
200 g spaghetti
2 eggs
100 g pancetta
Sauce: pecorino cheese, black pepper
For the garnish: fresh parsley

METHOD:
Fry the pancetta until crisp. Whisk the eggs with the pecorino and plenty of pepper.
Drain the pasta, combine off the heat so the eggs do not scramble.
"""

# The terms that have to change language, with what counts as a correct rendering. Kept small
# and unambiguous on purpose: a word with three plausible translations measures the scorer's
# taste rather than the model's behaviour.
TERMS = {
    ("it", "en"): [           # Italian material asked for in English
        ("mascarpone", ["mascarpone"]),                 # stays: it is the ingredient's name
        ("uova", ["egg", "eggs"]),
        ("zucchero", ["sugar"]),
        ("savoiardi", ["ladyfinger", "ladyfingers", "savoiardi", "sponge finger"]),
        ("cacao", ["cocoa", "cacao"]),
        ("caffe", ["coffee"]),
    ],
    # The list-shaped Italian caption, asked for in English. This is the case that used to
    # score 0%.
    #
    # `cavolo` is the interesting row: the model renders "cavolo cappuccio" as "cabbage only
    # sometimes, and otherwise leaves it in Italian. It is scored as a **miss**, and that is
    # deliberate — it did not change language. But the alternative is worse and was what
    # happened before the prompt forbade it: "chinese broccoli", a different vegetable stated
    # with confidence. A miss here means a legible Italian word on an English card; the score
    # this row does not give is the price of not buying the wrong thing.
    ("it-list", "en"): [
        ("maiale", ["pork"]),
        ("cipolla", ["onion"]),
        ("carote", ["carrot", "carrots"]),
        ("cavolo", ["cabbage"]),
        ("soia", ["soy"]),
        ("verdure", ["vegetable", "vegetables"]),
    ],
    ("en", "it"): [           # English material asked for in Italian
        ("spaghetti", ["spaghetti"]),
        ("eggs", ["uovo", "uova"]),
        ("pancetta", ["pancetta"]),
        ("pecorino", ["pecorino"]),
        ("black pepper", ["pepe"]),
        ("parsley", ["prezzemolo"]),
    ],
}

# Groups: the label the pipeline should produce, in the target language.
#
# These are matched as substrings, and they have to track what `data/ingredients.yaml`
# actually emits — not what seems a reasonable translation. "For the garnish" comes out as
# "Per guarnire", and a list expecting "guarnizione" scored it a miss and reported a defect
# that was not there. A benchmark that under-reports is as misleading as one that over-reports.
GROUPS = {
    ("it-list", "it"): ["verdure", "salsa"],
    ("it-list", "en"): ["vegetable", "vegetables", "sauce"],
    ("it", "it"): ["base", "copertura"],
    ("it", "en"): ["base", "topping", "coating", "cover"],
    ("en", "en"): ["sauce", "garnish"],
    ("en", "it"): ["salsa", "sugo", "guarnire", "guarnizione", "decorazione"],
}

# The amounts stated in the caption. They must survive unconverted, whatever the language.
AMOUNTS = {"it": ["250", "100", "200", "3"], "it-list": ["80"], "en": ["200", "100", "2"]}

# The caption that actually breaks it. Short, list-shaped, most ingredients with no amount at
# all. The tiramisu one above translates cleanly every time; this one translates nothing —
# not the names, not the groups, not even the method. The failure is not gradual, it is
# all-or-nothing, and which way it goes depends on the material. A benchmark built only on
# the material that works would have measured a problem that does not exist.
CAPTION_IT_LIST = """\
Yaki Udon, pronti in 10 minuti netti!

INGREDIENTI:
Udon precotti
80g di Maiale (fettina grassa)
Verdure: Cipolla, Carote e Cavolo Cappuccio
Salsa: Soia, Mirin e Dashi in polvere

PROCEDIMENTO:
Taglia le verdure, rosola il maiale, aggiungi gli udon e la salsa. Salta tutto.
"""

CAPTIONS = {"it": CAPTION_IT, "it-list": CAPTION_IT_LIST, "en": CAPTION_EN}
TITLES = {"it": "Tiramisu della nonna", "it-list": "Yaki Udon", "en": "Weeknight Carbonara"}
# Which real language each caption is in, for scoring: "it-list" is Italian material.
LANGUAGE_OF = {"it": "it", "it-list": "it", "en": "en"}


def _text_of(draft: dict) -> str:
    """Every text field of the draft, lowercased, as one string."""
    parts = [str(draft.get(k) or "") for k in ("title", "description", "servings")]
    for i in draft.get("ingredients") or []:
        parts += [str(i.get(k) or "") for k in ("name", "notes", "group")]
    parts += [str(s) for s in (draft.get("method") or [])]
    parts += [str(s) for s in (draft.get("notes") or [])]
    return " ".join(parts).lower()


def score(draft: dict, source: str, target: str) -> dict:
    text = _text_of(draft)
    names = " ".join(str(i.get("name") or "") for i in (draft.get("ingredients") or [])).lower()

    if LANGUAGE_OF[source] == target:
        language = None          # nothing has to change language: the axis does not apply
        missed: list[str] = []
    else:
        # Searched across every text field, not just the names: a term like "verdure" is a
        # group heading, and scoring it against the ingredient names only would mark a correct
        # translation as a miss.
        pairs = TERMS[(source, target)]
        hits = [src for src, accepted in pairs if any(a in text for a in accepted)]
        missed = [src for src, accepted in pairs if not any(a in text for a in accepted)]
        language = len(hits) / len(pairs)

    wanted = GROUPS[(source, target)]
    groups = {str(i.get("group") or "").lower() for i in (draft.get("ingredients") or [])}
    groups_ok = sum(1 for g in groups if g and any(w in g for w in wanted))

    raw = " ".join(
        f"{i.get('quantity_raw') or ''} {i.get('unit_raw') or ''}"
        for i in (draft.get("ingredients") or [])
    )
    amounts_found = sum(1 for a in AMOUNTS[source] if a in raw)

    return {
        "language": language,
        "missed": missed,
        "groups_found": groups_ok,
        "groups_expected": 2,
        "amounts_found": amounts_found,
        "amounts_expected": len(AMOUNTS[source]),
        "n_ingredients": len(draft.get("ingredients") or []),
        "gaps": len(draft.get("gaps") or []),
    }


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    results = []
    for run in range(runs):
        for source in ("it", "it-list", "en"):
            for target in ("it", "en"):
                started = time.time()
                draft = extract.extract_draft(
                    caption=CAPTIONS[source], transcript="", title=TITLES[source],
                    language=target,
                ).draft
                # The same decision the pipeline makes, from the same function.
                if extract.needs_translation(CAPTIONS[source], draft, target):
                    draft = extract.translate_draft(draft, language=target)
                s = score(draft, source, target)
                s.update(run=run, source=source, target=target,
                         seconds=round(time.time() - started, 1))
                results.append(s)
                lang = "n/a " if s["language"] is None else f"{s['language']:.0%}"
                print(f"  {source}->{target}  language={lang}  "
                      f"groups={s['groups_found']}/2  amounts={s['amounts_found']}/{s['amounts_expected']}  "
                      f"ingr={s['n_ingredients']}  {s['seconds']}s"
                      + (f"   missed: {', '.join(s['missed'])}" if s["missed"] else ""))
    print()
    for source, target in (("it", "it"), ("it-list", "it"), ("en", "en"),
                           ("en", "it"), ("it", "en"), ("it-list", "en")):
        rows = [r for r in results if r["source"] == source and r["target"] == target]
        langs = [r["language"] for r in rows if r["language"] is not None]
        amounts = sum(r["amounts_found"] for r in rows) / sum(r["amounts_expected"] for r in rows)
        groups = sum(r["groups_found"] for r in rows) / (2 * len(rows))
        label = f"{source}->{target}"
        lang = "n/a" if not langs else f"{sum(langs)/len(langs):.0%}"
        print(f"{label:8} language={lang:>5}  groups={groups:.0%}  amounts={amounts:.0%}")
    print(json.dumps(results), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
