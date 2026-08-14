"""A repeatable measurement of extraction + translation, over every language combination.

It exists because "the translation is unreliable" is not a number, and without a number no
change to the pipeline can be claimed as an improvement. Run it **before** a change and
**after**, on the same material:

    uv run python tools/benchmark-translation.py 2

It is not a gate and does not belong on `./check.sh`'s path: it prints numbers, it does not
pass or fail. The pass/fail half lives in `tests/test_modello.py`, which holds the outcomes
this measurement established. Reach for this one when touching `extract.py`'s prompts, the
translation pass, the glossary, or the default model.

**Every case here exists because something real got it wrong.** The material is authored — no
third-party text enters this repository (AGENTS.md §7) — but the *shapes* are taken from
reels that produced a defect, and each was added the day the defect was found:

  it            rich Italian prose. The easy case, and the one that made the first version of
                this file useless: it scored 100% and measured a problem that was not there.
  it-list       short, list-shaped, most ingredients with no amount. Translation towards
                English used to score **0%** here — not degraded, nothing at all.
  it-section    a named section holding ingredients, and a preparation paragraph that is NOT a
                section. A real reel lost a whole five-ingredient section from the list while
                still describing it in the method, and invented a section out of a method
                heading. The recipe knew; the shopping list did not.
                **It still fails, and it is meant to.** The section is lost and the group
                invented, on this material as on the reel it came from. Kept red on purpose:
                a case removed because it fails is a defect removed from view.
  en            plain English, with sections.
  en-bilingual  English followed by German, and amounts in Tbsp/Tsp. The hardest case the
                README names, and the one that produced the worst defect this project has
                seen: asked for Italian, the model reported **`2 Tbsp` as `2 cucchiaini`** —
                a threefold error, provenance `declared`. THE UNITS AXIS EXISTS FOR THIS.

The axes, in the order they matter:

  units      the unit the model reports must be the one the material used. This is the axis
             the whole project rests on (AGENTS.md §3): the code converts faithfully whatever
             unit it is given, so a unit changed before the code sees it is a wrong number
             presented as a right one, and nothing downstream can catch it.
  sections   every ingredient under a named section reaches the ingredient list, and no
             section is invented out of a method heading.
  language   how many of the terms that must change language actually did.
  amounts    the stated numbers survive.
"""
from __future__ import annotations

import json
import sys
import time

from reel2recipe import extract

# --------------------------------------------------------------------------------------
# The material and what each case demands of the pipeline
# --------------------------------------------------------------------------------------

CASES: dict[str, dict] = {
    "it": {
        "language": "it",
        "title": "Tiramisu della nonna",
        "caption": """\
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
""",
        "amounts": ["250", "100", "200", "3"],
        "units": ["g"],
        # Both languages: the output is translated, so looking for the Italian word alone
        # reported the section as lost when it was there under its English name.
        "sections": {"base": ["savoiardi", "ladyfinger", "sponge"],
                     "copertura": ["cacao", "cocoa"]},
        "terms": {"en": [("mascarpone", ["mascarpone"]), ("uova", ["egg", "eggs"]),
                         ("zucchero", ["sugar"]), ("cacao", ["cocoa", "cacao"]),
                         ("caffe", ["coffee"])]},
        "group_words": {"it": ["base", "copertura"], "en": ["base", "topping", "coating"]},
    },
    "it-list": {
        "language": "it",
        "title": "Yaki Udon",
        "caption": """\
Yaki Udon, pronti in 10 minuti netti!

INGREDIENTI:
Udon precotti
80g di Maiale (fettina grassa)
Verdure: Cipolla, Carote e Cavolo Cappuccio
Salsa: Soia, Mirin e Dashi in polvere

PROCEDIMENTO:
Taglia le verdure, rosola il maiale, aggiungi gli udon e la salsa. Salta tutto.
""",
        "amounts": ["80"],
        "units": [],
        "sections": {"verdur": ["cipoll", "onion"], "salsa|sauce": ["soia", "soy"]},
        "terms": {"en": [("maiale", ["pork"]), ("cipolla", ["onion"]),
                         ("carote", ["carrot", "carrots"]), ("cavolo", ["cabbage"]),
                         ("soia", ["soy"]), ("verdure", ["vegetable", "vegetables"])]},
        "group_words": {"it": ["verdur", "salsa"], "en": ["vegetable", "sauce"]},
    },
    "it-section": {
        "language": "it",
        "title": "Burger ripieni",
        # A named section, a preparation paragraph that only looks like one, a method line
        # naming the section's own ingredients again — and a **transcript**, which is what
        # finally made it fail the way the real reel does.
        #
        # The first version of this case was shorter, and it **passed** while the real reel it
        # was drawn from kept failing: a benchmark easier than the thing it stands for measures
        # nothing, which is the same lesson the very first version of this file taught. Made
        # faithful — the full ingredient list, the promotional opening, and above all the
        # "Per la salsa: mescola yogurt, maionese..." line in the method — it reproduces.
        "caption": """\
BURGER RIPIENI FACILI in friggitrice ad aria o forno

Viralissimi nel web, questi panini sono assurdi, con un ripieno che conquista morso dopo
morso! Ecco la mia versione semplificata per chi non vuole fare l'impasto.

INGREDIENTI (6 burger):
1 rotolo di pasta per pizza
6 hamburger di manzo
12 fette di formaggio
2 cipolle piccole
3 cetrioli sottaceto
1 tuorlo
1 pizzico di sale
Mezzo cucchiaino di zucchero
Semi di sesamo q.b.
Olio q.b.

Salsa burger:
2 cucchiai yogurt greco
3 cucchiai maionese
2 cucchiai ketchup
Paprika affumicata q.b.

Per le cipolle caramellate: scalda un filo di olio, aggiungi le cipolle tagliate ad anelli
e rosolale per 2 minuti; aggiungi sale e zucchero e cuoci per altri 5 minuti.
Intanto cuoci gli hamburger a 180 gradi per 15 minuti, girandoli a meta cottura.
Per la salsa: mescola yogurt greco, maionese, ketchup e paprika.
Taglia la pasta in 6 parti, farcisci con formaggio, hamburger e salsa, richiudi e cuoci.
""",
        # The spoken half. It narrates the assembly and names "salsa" as one component rather
        # than as a set of ingredients — and that is the whole difference: with the caption
        # alone the section survives about half the time, with the speech added it never does,
        # and the model invents "cipolle caramellate" out of the method paragraph every time.
        #
        # The prompt already says the caption wins when the two disagree. It evidently wins on
        # **values** and not on **structure**, which is the shape of the next fix and not of
        # this one.
        "transcript": (
            "Scommetto che non sai che se metti la pasta per pizza su una ciotola, riempi con "
            "formaggio, hamburger, salsa, cetrioli e cipolla caramellata, richiudi e cuoci in "
            "friggitrice ad aria, ottieni dei burger ripieni veramente pazzeschi."
        ),
        "amounts": ["6", "12", "3", "2"],
        "units": ["cucchiai"],
        "sections": {"salsa": ["yogurt", "yoghurt", "maionese", "mayo", "ketchup"]},
        "terms": {"en": [("maionese", ["mayonnaise", "mayo"]), ("cipolle", ["onion", "onions"]),
                         ("zucchero", ["sugar"]), ("sale", ["salt"])]},
        "group_words": {"it": ["salsa"], "en": ["sauce"]},
        # Headings that must NOT appear: they are method paragraphs, not sections.
        "not_sections": ["caramellat"],
    },
    "en": {
        "language": "en",
        "title": "Weeknight Carbonara",
        "caption": """\
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
""",
        "amounts": ["200", "100", "2"],
        "units": ["g"],
        "sections": {"sauce|salsa": ["pecorino"], "garnish|guarni": ["parsley", "prezzemolo"]},
        "terms": {"it": [("spaghetti", ["spaghetti"]), ("eggs", ["uovo", "uova"]),
                         ("pancetta", ["pancetta"]), ("pecorino", ["pecorino"]),
                         ("black pepper", ["pepe"]), ("parsley", ["prezzemolo"])]},
        "group_words": {"en": ["sauce", "garnish"], "it": ["salsa", "guarni"]},
    },
    "en-bilingual": {
        "language": "en",
        "title": "Overnight Oats",
        # English then German, and amounts in spoons. This is the shape that produced
        # `2 Tbsp` -> `2 cucchiaini`: a threefold error, reported as declared.
        "caption": """\
OVERNIGHT OATS
Prep breakfast for a week in 15 minutes with these jars!
RECIPE (5 jars, 15min prep time):
-200g oats or spelt flakes
-2 Tbsp peanut butter
-5 Tbsp vanilla protein powder
-a pinch of salt
-550ml plant milk
Mix well and set aside.
Fruit part:
-300g frozen berries
-2 Tsp ground flax seeds
Heat the berries and stir in the flax seeds. Layer and refrigerate.
-
OVERNIGHT OATS. Bereite Fruehstueck fuer eine Woche in 15 Minuten vor!
REZEPT (5 Glaeser): -200g Haferflocken -2 EL Erdnussmus -5 EL Proteinpulver
-eine Prise Salz -550ml Pflanzenmilch. Fruchtteil: -300g TK-Beeren -2 TL Leinsamen.
""",
        "amounts": ["200", "550", "300", "2", "5"],
        # The heart of it. `tbsp` must survive as a tablespoon and not become a teaspoon,
        # whatever language the recipe comes out in.
        "units": ["tbsp", "tsp"],
        "sections": {"fruit|frutta|frutt": ["berries", "frutti", "bosco", "fragole"]},
        "terms": {"it": [("oats", ["avena", "fiocchi"]), ("peanut butter", ["arachidi"]),
                         ("salt", ["sale"]), ("plant milk", ["latte"]),
                         ("flax seeds", ["lino"]), ("berries", ["frutti di bosco", "bosco"])]},
        "group_words": {"en": ["fruit"], "it": ["frutt"]},
    },
}


def _units_of(draft: dict) -> str:
    """Both raw fields, because the model does not reliably separate the two.

    `units.py` documents it: `quantity_raw` arrives as "80g" or "1 1/2 cup" with `unit_raw`
    empty often enough that the recovery step exists. Reading only `unit_raw` scored a
    faithful "200 g" as a lost unit — a scorer that measures the wrong field reports defects
    that are not there, which is how a benchmark starts costing more than it gives.
    """
    return " ".join(f"{i.get('quantity_raw') or ''} {i.get('unit_raw') or ''}"
                    for i in (draft.get("ingredients") or [])).lower()


def _names_of(draft: dict) -> str:
    return " ".join(str(i.get("name") or "") for i in (draft.get("ingredients") or [])).lower()


def _all_text(draft: dict) -> str:
    parts = [str(draft.get(k) or "") for k in ("title", "description", "servings")]
    for i in draft.get("ingredients") or []:
        parts += [str(i.get(k) or "") for k in ("name", "notes", "group")]
    parts += [str(s) for s in (draft.get("method") or [])]
    parts += [str(s) for s in (draft.get("notes") or [])]
    return " ".join(parts).lower()


def score(draft: dict, case: dict, target: str) -> dict:
    text, names = _all_text(draft), _names_of(draft)
    units = _units_of(draft)
    groups = {(i.get("group") or "").strip().lower() for i in (draft.get("ingredients") or [])}
    groups.discard("")

    # Units: the axis the project rests on. A unit that changed before the code saw it is a
    # wrong number that no later stage can catch.
    wanted_units = case.get("units") or []
    units_kept = sum(1 for u in wanted_units if u in units)

    # Sections: every ingredient under a named heading has to be in the list.
    sections = case.get("sections") or {}
    listed = 0
    for members in sections.values():
        if any(m in names for m in members):
            listed += 1

    invented = [g for g in groups
                if any(bad in g for bad in (case.get("not_sections") or []))]

    pairs = (case.get("terms") or {}).get(target, [])
    missed = [src for src, ok in pairs if not any(a in text for a in ok)]
    language = (len(pairs) - len(missed)) / len(pairs) if pairs else None

    raw = " ".join(f"{i.get('quantity_raw') or ''} {i.get('unit_raw') or ''}"
                   for i in (draft.get("ingredients") or []))
    amounts = sum(1 for a in case["amounts"] if a in raw)

    return {
        "units_kept": units_kept, "units_wanted": len(wanted_units),
        "sections_listed": listed, "sections_wanted": len(sections),
        "invented": invented,
        "language": language, "missed": missed,
        "amounts": amounts, "amounts_wanted": len(case["amounts"]),
        "n": len(draft.get("ingredients") or []),
    }


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    results = []
    for _ in range(rounds):
        for name, case in CASES.items():
            for target in ("it", "en"):
                started = time.time()
                draft = extract.extract_draft(caption=case["caption"],
                                              transcript=case.get("transcript", ""),
                                              title=case["title"], language=target).draft
                if extract.needs_translation(case["caption"], draft, target):
                    draft = extract.translate_draft(draft, language=target)
                s = score(draft, case, target)
                s.update(case=name, target=target, seconds=round(time.time() - started, 1))
                results.append(s)
                lang = " n/a" if s["language"] is None else f"{s['language']:>4.0%}"
                print(f"  {name:13}->{target}  units={s['units_kept']}/{s['units_wanted']}"
                      f"  sections={s['sections_listed']}/{s['sections_wanted']}"
                      f"  lang={lang}  amounts={s['amounts']}/{s['amounts_wanted']}"
                      f"  ingr={s['n']}  {s['seconds']}s"
                      + (f"  INVENTATI:{s['invented']}" if s["invented"] else "")
                      + (f"  missed:{','.join(s['missed'])}" if s["missed"] else ""))
    print()
    def pct(rows, a, b):
        want = sum(r[b] for r in rows)
        return "n/a" if not want else f"{sum(r[a] for r in rows) / want:.0%}"
    for name in CASES:
        for target in ("it", "en"):
            rows = [r for r in results if r["case"] == name and r["target"] == target]
            langs = [r["language"] for r in rows if r["language"] is not None]
            print(f"{name:13}->{target}  units={pct(rows,'units_kept','units_wanted'):>4}"
                  f"  sections={pct(rows,'sections_listed','sections_wanted'):>4}"
                  f"  lang={'n/a' if not langs else f'{sum(langs)/len(langs):.0%}':>4}"
                  f"  amounts={pct(rows,'amounts','amounts_wanted'):>4}"
                  f"  invented={sum(len(r['invented']) for r in rows)}")
    print(json.dumps(results), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
