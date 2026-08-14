"""test_web.py — structural guards on the frontend.

They do not execute JavaScript: the suite is pytest and the frontend has no toolchain (and
does not want one). What they check instead is the only thing verifiable by reading the files,
and that is exactly the class of defect that went unnoticed: **a control that is drawn and
nobody reads**, and **a word that exists in one language only**.

`index.html` declared `#opt-lingua` and `#opt-sistema`, the user saw them and used them, and
`app.js` never queried them — so every job came out in Italian metric. A control that does
nothing is worse than a missing one: the first teaches you not to trust the interface, the
second is at least honest.

The guards have grown since, and each new one was added the day something got past the suite:
the placeholders against the calls that fill them, the JSON keys against what the server
actually produces, the CSS classes against the stylesheet. Every one of them was verified by
breaking it on purpose.
"""

from __future__ import annotations

import re

import pytest

import ast
from pathlib import Path

from reel2recipe import api, documents, mela, pipeline, units
from reel2recipe.paths import REPO_ROOT

WEB_FOLDER = REPO_ROOT / "web"
INDEX = (WEB_FOLDER / "index.html").read_text(encoding="utf-8")
I18N = (WEB_FOLDER / "i18n.js").read_text(encoding="utf-8")

# Every module of the page, not just `app.js`: the language selector is wired up in
# `i18n.js`, and a guard looking at one file only would declare it dead by mistake.
MODULES = {p.name: p.read_text(encoding="utf-8") for p in sorted(WEB_FOLDER.glob("*.js"))}
JS = "\n".join(MODULES.values())

DEFINED_IDS = set(re.findall(r'id="([\w-]+)"', INDEX)) | set(re.findall(r'id="([\w-]+)"', JS))
USED_IDS = set(re.findall(r"""\$\$?\('#([\w-]+)'\)""", JS))


# --------------------------------------------------------------------------------------
# Controls drawn and controls read
# --------------------------------------------------------------------------------------


def test_every_option_control_is_read():
    """Every `#opt-…` that is drawn has to be queried by some module.

    It is the guard that would have caught the language defect: the menu existed from the
    start, the reading did not.
    """
    drawn = {i for i in set(re.findall(r'id="([\w-]+)"', INDEX)) if i.startswith("opt-")}
    assert drawn, "no option control found: the guard has come unplugged"
    unread = sorted(drawn - USED_IDS)
    assert not unread, (
        f"controls drawn in index.html but never read by the JavaScript: {unread}. "
        "A control that does nothing is to be wired up or removed."
    )


def test_no_selector_points_at_nothing():
    """The other way round: a `$('#wrong-id')` does not fail, it returns `null` — and the
    defect shows up much later, as a row that does not react."""
    undefined = sorted(USED_IDS - DEFINED_IDS)
    assert not undefined, f"the JavaScript queries ids nobody defines: {undefined}"


# --------------------------------------------------------------------------------------
# The catalogues: no half-translated language
# --------------------------------------------------------------------------------------


def _i18n_keys() -> dict[str, set[str]]:
    """The keys declared by each language in `i18n.js`.

    The file is read rather than executed: the two languages are two `it: { … }` and
    `en: { … }` blocks inside an object literal, and the keys sit at the start of a line with
    two levels of indentation. That is enough to answer the question that matters — *is there a
    key that exists on one side and not on the other?* — without dragging in a JavaScript
    interpreter.

    The cut is made at `export const LANGUAGES`, which is the first thing after the catalogue.
    During the migration that marker was renamed and the split silently stopped cutting
    anything: the guard kept passing on the whole file. Hence the assertion below that the
    marker was actually found.
    """
    assert "export const LANGUAGES" in I18N, (
        "the marker that closes the catalogue has changed name: the split is not cutting and "
        "the guard is reading more than it should"
    )
    catalogue = I18N.split("export const LANGUAGES")[0]
    per_language: dict[str, set[str]] = {}
    current_language = None
    for line in catalogue.splitlines():
        if heading := re.match(r"^  (\w+): \{$", line):
            current_language = heading.group(1)
            per_language[current_language] = set()
        elif current_language and (key := re.match(r"^    (\w+):", line)):
            per_language[current_language].add(key.group(1))
    return per_language


def test_i18n_declares_the_expected_languages():
    keys = _i18n_keys()
    assert set(keys) == {"it", "en"}, f"languages found in i18n.js: {sorted(keys)}"
    assert len(keys["it"]) > 50, "the catalogue looks empty: the guard is reading nothing"


def test_i18n_has_no_half_translated_language():
    """A key present in one language only is not a visible error: the fallback to Italian
    covers it, and whoever is reading in English finds an Italian sentence in the middle of the
    page with nothing flagging it."""
    keys = _i18n_keys()
    assert not (keys["it"] - keys["en"]), (
        f"keys with no English translation: {sorted(keys['it'] - keys['en'])}"
    )
    assert not (keys["en"] - keys["it"]), (
        f"English keys with no Italian counterpart: {sorted(keys['en'] - keys['it'])}"
    )


def test_every_markup_key_exists_in_the_catalogue():
    """A `data-i18n` that does not find its key raises nothing: `t()` falls back to the key
    itself, and `lbl_measures` appears on screen where "Misure" should be."""
    keys = _i18n_keys()["it"]
    used = set(re.findall(r'data-i18n(?:-\w+)?="([\w-]+)"', INDEX))
    assert used, "no data-i18n attribute in the markup: the guard has come unplugged"
    assert not (used - keys), f"keys used in the markup and absent from the catalogue: {sorted(used - keys)}"


def test_every_key_app_js_asks_for_exists_in_the_catalogue():
    """The same rule as the markup guard above, for the keys that are only in the JavaScript.

    The markup guard did not cover them, and the gap cost four dead keys: the catalogue's keys
    were renamed to English and `stato_nessun_modello`, `stato_ollama_spento`, `opzioni_apri`
    and `opzioni_chiudi` were left behind in `app.js`. `t()` falls back to the key itself, so
    the options button read `opzioni_apri` on its first click and the status label read
    `stato_ollama_spento` — which is the line you get exactly when Ollama is down and you most
    need to read it.

    They survived because every existing guard looked at `t('literal')`, and all four sit
    inside a ternary — `t(cond ? 'a' : 'b')`. So this one collects **every** quoted key-shaped
    literal inside a `t(...)` call, both branches included.
    """
    keys = _i18n_keys()["it"]
    used = {
        literal
        for call in re.findall(r"\bt\(([^()]*)\)", MODULES["app.js"])
        for literal in re.findall(r"'([a-z][a-z_0-9]*)'", call)
    }
    assert len(used) > 30, "the guard is reading almost no keys: it has come unplugged"
    assert not (used - keys), (
        f"keys app.js asks for and absent from the catalogue: {sorted(used - keys)}"
    )


@pytest.mark.parametrize("module, catalogue", [("pipeline", pipeline.TEXTS), ("api", api.TEXTS)])
def test_the_python_catalogues_are_complete(module, catalogue):
    """The same rule for the strings born in the server: progress, warnings and API errors.
    The fallback to Italian is there, but it exists to break nothing — not to make a missing
    translation acceptable."""
    assert set(catalogue) == {"it", "en"}, f"{module}.TEXTS: languages {sorted(catalogue)}"
    missing = set(catalogue["it"]) - set(catalogue["en"])
    assert not missing, f"{module}.TEXTS, keys with no English translation: {sorted(missing)}"
    extra = set(catalogue["en"]) - set(catalogue["it"])
    assert not extra, f"{module}.TEXTS, orphan English keys: {sorted(extra)}"


@pytest.mark.parametrize("module, catalogue", [("pipeline", pipeline.TEXTS), ("api", api.TEXTS)])
def test_the_placeholders_match_between_languages(module, catalogue):
    """A `{title}` that vanishes in the English translation gives no error: it gives a
    sentence missing the piece that made it useful. An *invented* placeholder, on the other
    hand, explodes — and it does so in front of the user, halfway through a job."""
    for key, italian_text in catalogue["it"].items():
        expected = set(re.findall(r"\{(\w+)\}", italian_text))
        found = set(re.findall(r"\{(\w+)\}", catalogue["en"][key]))
        assert expected == found, (
            f"{module}.TEXTS['{key}']: placeholders it={sorted(expected)} en={sorted(found)}"
        )


# --------------------------------------------------------------------------------------
# The contract between the server JSON and the keys the page reads
# --------------------------------------------------------------------------------------


def _sample_recipe():
    """A real recipe, built by the pipeline rather than written by hand: the keys have to be
    the ones the server actually produces, not the ones we remember."""
    from reel2recipe.recipe import Source, from_draft

    return from_draft(
        {"title": "Torta di mele", "servings": "6 persone",
         "ingredients": [{"name": "farina 00", "quantity_raw": "1", "unit_raw": "cup",
                          "group": "Per l'impasto"}],
         "method": ["Inforna a 180 °C."], "categories": ["Dolci"],
         "prep_time_min": 20, "cook_time_min": 45, "gaps": []},
        source=Source.now(url="https://x/y", author="nonna", platform="instagram"),
        images=["Zm90bw=="],
    )


def test_every_key_the_page_reads_exists_in_the_server_json():
    """The guard that would have caught the rename of `Recipe`'s fields in one go.

    `app.js` reads the JSON by attribute: `recipe.titolo` on an object that no longer has that
    field raises nothing, returns `undefined`, and the card draws itself anyway — with an empty
    title. It is the same family of mute defect as the guards above, and on a frontend with no
    toolchain there is nothing else that could notice.

    It used to look at `recipe.X` only, and exempt the nested accesses on the stated ground
    that "their keys are Italian by choice and do not follow the Python names". The exemption
    is what the defect grew in: `to_dict()` wrote `riga` and `gruppo`, `app.js` read `ing.row`
    and `i.group`, and every ingredient line in the card rendered from `undefined` — a card
    with its groups gone and its rows blank, raising nothing. Now that the nested keys are
    English too there is no ground left for the exemption, so the guard covers them.
    """
    recipe = _sample_recipe().to_dict()
    # `id` is added by the API after the save, not by `to_dict()`.
    available = set(recipe) | {"id"}

    read_keys = set(re.findall(r"\b(?:current)?[Rr]ecipe\.(\w+)", MODULES["app.js"]))
    assert read_keys, "no `recipe.` access in app.js: the guard has come unplugged"

    missing = sorted(read_keys - available)
    assert not missing, (
        f"app.js reads keys the server does not produce: {missing}. "
        f"The server produces: {sorted(available)}"
    )


def test_every_nested_ingredient_key_the_page_reads_exists():
    """The level below, which is where the mute failure actually happened.

    `ing.row` against a dictionary carrying `line` yields `undefined`, `esc(undefined)` draws
    an empty row, and the card looks like a recipe whose ingredients have no text. Nothing
    raises, no test on the Python side can see it, and the page has no toolchain that would.

    The ingredient variables are named by convention in `app.js` — `i` inside a `map`, `ing`
    inside the render loop — so those are the two the guard follows, and it asserts it found
    something under each rather than trusting that it did.
    """
    ingredient = _sample_recipe().to_dict()["ingredients"][0]
    available = set(ingredient)
    quantity_available = set(ingredient["quantity"])

    source = MODULES["app.js"]
    read_keys = set(re.findall(r"\b(?:ing|i)\.(\w+)", source)) - {"quantity"}
    quantity_keys = set(re.findall(r"\b(?:ing|i)\.quantity\??\.(\w+)", source))

    assert read_keys, "no ingredient access in app.js: the guard has come unplugged"
    assert quantity_keys, "no quantity access in app.js: the guard has come unplugged"

    assert not (read_keys - available), (
        f"app.js reads ingredient keys that `to_dict()` does not write: "
        f"{sorted(read_keys - available)}. It writes: {sorted(available)}"
    )
    assert not (quantity_keys - quantity_available), (
        f"app.js reads quantity keys that `to_dict()` does not write: "
        f"{sorted(quantity_keys - quantity_available)}. It writes: {sorted(quantity_available)}"
    )


def test_every_library_card_key_exists_in_the_listing(tmp_path):
    """The same for the library cards, which come from `Library.list_` and not from
    `to_dict()`: a second shape, with keys of its own, and therefore a second way of drifting
    away from the frontend in silence."""
    from reel2recipe.store import Library

    with Library(tmp_path / "guard.db") as library:
        library.save(_sample_recipe())
        available = set(library.list_()[0])

    # The cards are drawn inside `entries.map((v) => …)`: every access is on `v`.
    read_keys = set(re.findall(r"\bv\.(\w+)", MODULES["app.js"]))
    assert read_keys, "no `v.` access in app.js: the guard has come unplugged"

    missing = sorted(read_keys - available)
    assert not missing, (
        f"app.js reads card keys that `Library.list_` does not produce: {missing}. "
        f"The listing produces: {sorted(available)}"
    )


@pytest.mark.parametrize("module, catalogue, source", [
    ("pipeline", pipeline.TEXTS, pipeline.__file__),
    ("api", api.TEXTS, api.__file__),
    ("mela", mela.TEXTS, mela.__file__),
    ("documents", documents.TEXTS, documents.__file__),
    ("units", units.MESSAGES, units.__file__),
])
def test_every_call_passes_the_placeholders_the_sentence_asks_for(module, catalogue, source):
    """The names passed to `text(...)` have to be the ones the sentence expects.

    The guard above compares the placeholders **between the two languages**; this one compares
    the placeholders with **whoever fills them**, which is a different question and which let a
    real defect through: during the migration a mechanical rename turned
    `text(language, "ready_recipe", titolo=…)` into `title=…` while the sentence still said
    `{titolo}`. `str.format` raises `KeyError`, so every successful job would have exploded on
    its last message — but no test saw it, because reaching that line needs Ollama and a real
    file. The defect survived two commits.

    The source is read rather than executed: what matters is the call as written, not the one a
    test happens to walk through.
    """
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    per_key: dict[str, set[str]] = {
        key: set(re.findall(r"\{(\w+)\}", frase))
        for key, frase in catalogue["it"].items()
    }

    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        nome = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if nome not in ("text", "message"):
            continue
        key_node = node.args[1]
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            continue                      # computed key: not checkable from here
        key = key_node.value
        assert key in per_key, f"{module}: `{key}` does not exist in the catalogue"
        passed = {kw.arg for kw in node.keywords if kw.arg}
        expected = per_key[key]
        assert passed == expected, (
            f"{module}, key `{key}` (line {node.lineno}): the sentence asks for "
            f"{sorted(expected)}, the call passes {sorted(passed)}"
        )
        checked += 1

    assert checked, f"{module}: no call found, the guard has come unplugged"


def test_every_t_call_passes_the_placeholders_the_sentence_asks_for():
    """The same guard as the Python side, for the side without a toolchain.

    `t('minutes', { quanti: … })` against a sentence saying `{how_many}` raises nothing: `t()`
    substitutes what it finds and leaves the rest literal, so "{how_many} min" appears on
    screen. It really happened during the migration, when the catalogue's keys and placeholders
    moved to English and the call sites did not.

    The source is read, as in the other guards here: no JavaScript interpreter, only the
    `t('key', { a: …, b: … })` shape, which is the only one used in `app.js`.
    """
    catalogue = _i18n_keys()
    texts = MODULES["i18n.js"]

    # The placeholders each key declares, read from the Italian block.
    per_key: dict[str, set[str]] = {}
    current_key = None
    for line in texts.split("export const LANGUAGES")[0].splitlines():
        if heading := re.match(r"^    (\w+):", line):
            current_key = heading.group(1)
            per_key.setdefault(current_key, set())
        if current_key:
            per_key[current_key].update(re.findall(r"\{(\w+)\}", line))

    checked = 0
    for key, body in re.findall(r"t\('(\w+)',\s*\{([^}]*)\}", MODULES["app.js"]):
        assert key in catalogue["it"], f"`{key}` does not exist in the catalogue"
        passed = set(re.findall(r"(\w+)\s*:", body)) | {
            n for n in re.findall(r"^\s*(\w+)\s*$", body)   # shorthand form { search }
        }
        expected = per_key.get(key, set())
        assert passed == expected, (
            f"t('{key}'): the sentence asks for {sorted(expected)}, the call passes {sorted(passed)}"
        )
        checked += 1

    assert checked, "no `t(key, {…})` call found: the guard has come unplugged"


# Classes present in the markup but with no rule in `style.css`. They do no damage — an unused
# hook breaks nothing — but they already existed before the migration, and naming them here is
# more honest than loosening the guard until it stops firing at all.
CLASSES_WITHOUT_STYLE = {"btn-cook-text", "stage-text", "library"}


def test_every_custom_property_resolves():
    """A `var(--crema)` whose definition is now `--cream` does not fail: CSS drops the whole
    declaration and the element renders with no colour at all.

    It is the same silent class as a misspelt selector, one level down, and it is precisely
    how the rename of the palette would have gone wrong — seventeen colours, radii and shadows
    that the page reads by name. The check runs both ways: an undefined property is a broken
    rule, and a defined one nobody reads is a leftover from a rename that only did half the
    file.
    """
    stylesheet = (WEB_FOLDER / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*(--[\w-]+)\s*:", stylesheet, re.M))
    used = set(re.findall(r"var\(\s*(--[\w-]+)", stylesheet))

    assert defined and used, "no custom property found: the guard has come unplugged"
    assert not (used - defined), (
        f"custom properties read but never defined: {sorted(used - defined)}"
    )
    assert not (defined - used), (
        f"custom properties defined but never read: {sorted(defined - used)}"
    )


def test_the_frontend_knows_every_stage_the_pipeline_emits():
    """`app.js`'s STAGES table is a contract with `pipeline.STAGES`, and it said so in a
    comment while nothing checked it.

    A stage the server emits and the page does not know draws no row: the bar simply skips it,
    and the user watches a step happen with nothing to show for it. The other direction is a
    dead row that never lights up. Adding the translation stage is what made this worth
    holding — it was the first new stage in a while, and it had to be added in three places at
    once (`pipeline.STAGES`, the two Python catalogues, `app.js` and `i18n.js`).
    """
    from reel2recipe.pipeline import STAGES

    declared = re.findall(r"^  (\w+): \{ icon", MODULES["app.js"], re.M)
    assert declared, "no stage found in app.js: the guard has come unplugged"

    assert set(declared) == set(STAGES), (
        f"the page and the pipeline disagree about the stages. "
        f"Only in pipeline.py: {sorted(set(STAGES) - set(declared))}. "
        f"Only in app.js: {sorted(set(declared) - set(STAGES))}"
    )


def test_every_icon_asked_for_exists_in_the_catalogue():
    """An icon name with no entry draws nothing, and nothing is what you see.

    `icons.js` is looked up by key; a key that is not there yields no path data and the
    element renders empty. No error, no console warning — the same silence as a misspelt class.

    This guard exists because the rename of the icon names missed a whole shape. It caught
    `icon('scarica')` and the `data-icon` attributes, and walked straight past
    `{ icon: 'scarica', key: 'stage_acquisition' }` in the STAGES table — so **five of the six
    icons on the progress bar were broken**, which is the one part of the interface the user
    watches while waiting. So this looks at every form a name can take, not the one that was
    convenient to grep for.
    """
    icons = MODULES["icons.js"]
    defined = set(re.findall(r"^  ([a-z][\w-]*): '", icons, re.M))
    used = (set(re.findall(r"\bicon\(\s*'([\w-]+)'", MODULES["app.js"]))
            | set(re.findall(r"\bicon:\s*'([\w-]+)'", MODULES["app.js"]))
            | set(re.findall(r'data-icon="([\w-]+)"', INDEX)))

    assert defined, "no icon defined: the guard has come unplugged"
    assert len(used) > 10, "the guard is reading almost no icon names: it has come unplugged"
    assert not (used - defined), (
        f"icons asked for and absent from the catalogue: {sorted(used - defined)}. "
        f"The catalogue holds: {sorted(defined)}"
    )


def test_every_used_class_has_a_rule_in_the_stylesheet():
    """A misspelt class raises nothing: the element draws itself unstyled.

    It is the defect the frontend makes invisible — no toolchain, no compiler — and an earlier
    rename of `app.js`'s identifiers fell straight into it: `'fase'` had become `'stage'`,
    `scheda-copertina` had become `card-cover`, and `style.css` went on defining the earlier
    names. The page would have worked and been unreadable.

    The class names have since moved to English across all three files at once. That step was
    deferred exactly this long because it *is* three files at once, and this guard plus
    `test_no_selector_points_at_nothing` are what made it safe to take: between them they hold
    the ids against both directions and the classes against the stylesheet, so a name left
    behind in any one of the three turns something red instead of quietly unstyling the page.
    """
    stylesheet = (WEB_FOLDER / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"\.([a-z][\w-]*)", stylesheet))

    used: set[str] = set()
    for source in (MODULES["app.js"], INDEX):
        for m in re.finditer(r"""class="([a-z][\w -]*)\"""", source):
            used |= set(m.group(1).split())
        for m in re.finditer(r"""className\s*=\s*'([a-z][\w -]*)'""", source):
            used |= set(m.group(1).split())
        for m in re.finditer(r"""classList\.(?:add|remove|toggle)\('([\w-]+)'\)""", source):
            used.add(m.group(1))
        for m in re.finditer(r"""querySelector(?:All)?\('\.([\w-]+)""", source):
            used.add(m.group(1))

    assert used, "no class found: the guard has come unplugged"
    orphans = sorted(used - defined - CLASSES_WITHOUT_STYLE)
    assert not orphans, f"classes used with no rule in style.css: {orphans}"
