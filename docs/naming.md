# Naming — the Italian → English migration

> **Finished, and now a record.** The codebase moved from Italian to English in stages, and
> the last of them closed the categories this document once listed as permanent exemptions:
> the SQL schema, the keys and values stored inside a recipe, the element ids and CSS classes,
> the model's JSON schema, and the add-on's runtime log. What is left in Italian is small,
> deliberate, and listed below.
>
> The parts worth keeping are not the inventory. They are **why a script cannot do this**,
> **the ways a rename hides**, and **the compatibility net**, which is permanent and grew with
> every stage. Each was paid for with a real defect.

## Why there is no script for this

A word-boundary rename was tried and reverted. It fails for a structural reason, not a
tuning one: **identifiers and prose are in the same language here**. `note`, `riga`, `nome`,
`valore` are field names *and* ordinary Italian words inside the comments that explain the
*why*. A lexical tool cannot tell the two apart, and the attempt produced

    "transcript dell'audio, in locale"        (asr.py docstring)
    "una line che non reagisce"               (test_web.py)
    "i nomi degli ingredients"                (asr.py)

on top of 28 failing tests. The correct method is to **rewrite one module at a time**,
identifiers and comments together. That is not extra work compared to a script: the comments
have to be rewritten into English anyway, and the script was only trying to dodge work that
is mandatory.

The last stage proved it again, in the one file where the temptation was strongest. A token
substitution over `extract.py` — whose schema field names are `nome`, `note`, `gruppo`, and
whose Italian system prompt is made of sentences containing exactly those words — produced

    "Il name dell'ingrediente"
    "i nomi degli ingredients"
    "le notes e i nomi dei gruppi"

*inside the prompt the model reads*. Reverted, and the prompt rewritten by hand. What did
work mechanically, and is the general form of the answer, is a substitution that is
**position-aware**: not "this word anywhere" but "this word in a slot that holds an
identifier" — a JSON key, an HTML attribute, a CSS selector, a `classList` argument. The
frontend rename went that way and the diff proves it: of the 41 lines it changed in
`index.html`, every one differs only inside `id`/`class`/`for`/`data-icon`, and none of the
Italian prose on the page moved.

## Method, per module

1. Rewrite the module: identifiers, comments, docstrings. Keep every *reason* the comments
   record — the point of this codebase is that comments explain why, and a translation that
   loses the reasoning is worse than the Italian it replaced.
2. Update every caller, plus the tests that name it.
3. `./check.sh` green **before** moving to the next module. Never leave a half-renamed tree.
4. Follow the order below, and update it when working on it teaches you something.

### Order — revised after the first four modules, and again after the two hard ones

The first version of this list said "leaves first, core last", which is right for *risk* and
wrong for *churn*: every module that touches `Recipe` would have been opened twice, once for
its own identifiers and again when `recipe.py`'s fields moved. Doing `units.py` and
`recipe.py` **before** their consumers avoided that second pass, and it worked — the
consumers came out of those two commits already updated as callers.

The one prediction that did not survive is the estimate of where the difficulty sits.
`units.py` was billed as the dangerous one because it is the conversion engine and 1270 lines;
it was in fact mechanical, and a 131k-case differential run against the old module found zero
differences. `recipe.py` is a third of the size and was the one that drew blood, because its
field names are also the JSON keys on disk and the *format boundary* runs through the middle
of it. **Size predicts effort; contact with stored data predicts risk.** They are not the same
axis, and the second one is what to plan around.

1. **Done — every module in `src/reel2recipe/`.** In order: `asr.py`, `percorsi.py` →
   `paths.py`, `audio.py`, `acquire.py`, `store.py`, `units.py`, `recipe.py`, `mela.py`,
   `documenti.py` → `documents.py`, `extract.py`, `pipeline.py`, `api.py`, `cli.py`. The
   protocol surfaces moved with the only thing that reads them, `web/app.js`: `Recipe`'s JSON
   keys, `Library.list_`'s output keys, the pipeline's stage names, the SSE payload and
   `CookRequest`'s fields.
2. **Done since:** the `data/*.yaml` keys with their loader, and the frontend —
   `web/i18n.js`'s catalogue keys and placeholders, `web/app.js`'s identifiers and prose, and
   `icone.js` → `icons.js`.
3. **Done since, one migration each.** The categories this list used to call permanent: the
   URL paths and query parameters; the SQL table and columns (`_migrate_italian_schema`); the
   nested keys of a stored recipe and the values of `Provenance` and `System` (`LEGACY_KEYS`,
   `LEGACY_PROVENANCES`, `LEGACY_SYSTEMS`); the element ids, CSS class names, custom
   properties and icon names, all three files at once; and `extract.py`'s schema field names,
   with the model gate run before and after on the same input.
4. **The one that was worth deferring.** The ids and classes waited because they live across
   `index.html`, `app.js` and `style.css` at once and a missed one unstyles the page in
   silence. Waiting was right, but not because the step was impossible: it was cheap once
   `tests/test_web.py` held the ids in both directions and the classes against the stylesheet.
   **Defer a rename until its guard exists, then take it** — not "defer it indefinitely".
   The guard earned its place immediately, catching `app.js` querying `#edit-ingredients`
   while its own templates still wrote `id="mod-ingredienti"`.
5. **Done last:** the test modules' own prose — all ten of them, with the model gate re-run
   for `test_modello.py` — and `docs/architettura.md` → `docs/architecture.md`.
6. **Done since, and the reasoning corrected.** `docs/legal.md` and `docs/terms-of-use.md`
   were once left Italian-with-an-English-summary, on the ground that two published legal
   versions can diverge. The risk is real; refusing to translate is not the answer to it, it
   is only a way of not having the problem by not having the document. Both now exist in full
   in both languages, with a **prevalence clause** naming the Italian authoritative — which is
   what bilingual legal texts do, and it turns a possible divergence from an ambiguity into a
   defined resolution.

### What the hard modules taught

The aborted attempt at `units.py` predicted three things. Two were spent immediately — the
`MESSAGES` keys and the three colliding `note`s were mapped up front and cost nothing. The
third turned out to be the axis the whole `recipe.py` step turned on, and it held exactly:

**The JSON keys and the Python attributes are decoupled in one half and welded in the other.**
`Recipe.to_dict()` builds the ingredient and quantity dictionaries with **string literals**
(`"nome"`, `"quantita"`, `"valore"`), so `Quantity` and `Ingredient` were renamed in full
without touching a single stored recipe. But the top level starts from `asdict(self)`, so
**`Recipe`'s own fields map straight onto JSON keys** — renaming `titolo` really does rename it
on disk. So the net went in exactly where it was needed and nowhere else.

That reading was right about the mechanism and wrong about the conclusion drawn from it. The
decoupling was read as a reason the nested keys should *stay* Italian; it was only ever a
reason they were cheap to leave. When they moved a release later, the literals changed on one
side and `LEGACY_KEYS` grew on the other, and the whole thing cost one commit. **A property
that makes something cheap to postpone is not an argument for postponing it for ever.**

Two things the field rename cost that the module rename did not, both worth knowing before
`extract.py`:

**A blanket regex over identifiers will hit prose and SQL, and the tests will not tell you.**
`\bRicetta\b → Recipe` silently rewrote four user-facing Italian strings — `"Ricetta non
trovata."`, the `"Fonte"` heading of every exported document, `"Ricetta di {autore}"` — and
`\.titolo\b → .title` rewrote the column list of a `SELECT`. The suite stayed green for three
of the four, because no test asserted on those strings. What caught them was reading the diff.
Budget for that reading; it is not optional on a module whose identifiers are ordinary words.

**A frontend with no toolchain needs a guard, not a review.** `app.js` reads the JSON by
attribute, so `ricetta.titolo` against a renamed payload yields `undefined` and the card draws
itself anyway, with an empty title — no error, nowhere. `tests/test_web.py` now compares the
keys `app.js` reads against the keys `to_dict()` and `Library.list_` actually produce. Both
guards were checked by breaking them on purpose, per the rule already in that file: a guard
that has stopped firing is worse than no guard.

And the method gained one rule from `units.py`: **rewriting a module is also the closest
reading it will ever get.** That pass turned up a line in `_key` that claimed to normalise
apostrophes and replaced the ASCII one with itself, with a real consequence on the output. It
went into its own commit *before* the rename, so the translation commit changed no behaviour.
Keep that split: a rename that also fixes something is a rename nobody can review.

### The five ways a rename hides

The migration produced six real defects across its stages, and every one of them was invisible
to `./check.sh`. They fall into five kinds, and the countermeasure for each is now in the repo
rather than in someone's memory. The first three were enough to learn the
shape; the last two were found later, and only by sweeping the whole artefact rather than the
diff.

**1. Tests that do not run.** `extract.py` carries an obligation the others do not: it holds
the system prompts and the JSON schema, so after touching it the model gate has to run —
`R2R_TEST_MODELLO=1 uv run pytest tests/test_modello.py`, roughly two minutes, and it needs
Ollama up. That gate is opt-in, and a mechanical kwarg rename during the `recipe.py` step
had made `tests/test_modello.py` call `estrai_bozza(transcript=…)` — a parameter that did not
exist. The test that protects the project's central promise sat uncallable for two commits.
**An opt-in test is not covered by the net; run it in the same session you touch it, even
by accident.**

**2. Code no test reaches.** `text(lingua, "pronta", titolo=…)` became `title=…` while the
sentence still said `{titolo}`. `str.format` raises `KeyError`, so every successful job would
have died on its last progress message — and reaching that line needs Ollama and a real file.
`tests/test_web.py` now compares, by AST, the keyword arguments of every `text(...)` call
against the placeholders its sentence declares. The neighbouring guard compared placeholders
*between languages*; this one compares them with *whoever fills them*, which is a different
question.

**3. Wiring only the running product exercises.** `serve_command` imports `create_app` inside
the function, so the stale name survived every test and died on the first real start. And the
export's `?formato=` query parameter, renamed to `format_` in the Python signature — which in
FastAPI *is* the query name — made all three formats silently return a `.melarecipe`. No
error, a wrong file, visible only on opening it. Both were found by restarting the server and
running a real reel end to end. `tests/test_api.py` now covers the export formats; for the
rest, **restart the thing and use it** is the only guard there is.

**4. A guard with a written-down exemption.** The one that cost the most this time, because
it was not an oversight: `test_every_key_the_page_reads_exists_in_the_server_json` covered
`recipe.X` and said, in its own docstring, that the nested accesses "stay out because their
keys are Italian by choice". Under that exemption `to_dict()` wrote `riga` and `gruppo` while
`app.js` read `ing.row` and `i.group` — so every ingredient line in the recipe card rendered
from `undefined`, and the groups disappeared. A card with blank rows, raising nothing, for a
release. The same shape had already produced four dead `t()` keys, which survived because
every guard looked at `t('literal')` and all four sat inside a ternary.

**An exemption written into a guard is a defect waiting for the exemption to expire.** Both
were found by sweeping the whole artefact rather than the part being changed, and neither
would have been found by the suite. When an exemption's reason goes away, the guard has to be
widened in the same commit — not the next time somebody happens to read it.

**5. An assertion that passes on nothing.** The most dangerous of the five, and the closest
call: almost every assertion in `tests/test_modello.py` is of the form "the model did **not**
invent an amount", which passes for free over an empty list. Renaming the schema's fields made
`draft.get("ingredienti")` return `None`, and the gate would have gone **green while checking
nothing** — on the test that protects the project's central promise. Four of those reads were
inside f-strings with single quotes and survived the first pass. `_reading_something()` now
stops hard if the key is not the one the schema writes. **A negative assertion needs a
positive one beside it, saying it found something to assert about.**

And the one that was not this migration's fault but was found by it: `"Libreria vuota."` had
been `"Library vuota."` since the `store.py` step, and `tests/test_api.py` asserted the broken
string — a test locking a defect in place. Which is the argument for the string-literal diff:
extracting every literal from `src/` before and after, and reading the difference. It caught
four Italian sentences a regex had walked into, a non-breaking space lost by a hand-rewrite,
and a help line that had started advertising a database file that does not exist.

## What is still Italian, and why

The list used to be long and is now short. Every row that left it did so with a migration and
tests, not with a decision that the exemption had stopped mattering — the record of what each
one cost is in the git history and in the modules themselves.

| stays as it is | where it lives | why |
|---|---|---|
| `unita.yaml`, `densita.yaml`, `vaghe.yaml`, `ricette.db` | file names | `ricette.db` is a file on the user's disk; the three tables are in the repo and could move cheaply, but renaming them buys nothing the contents did not already buy |
| the kitchen vocabulary in `data/*.yaml` | `cucchiaio`, `farina 00`, `q.b.` | it is **data**, not naming: it is what the model writes and what the lookup matches against. The English aliases sit next to it, not instead of it |
| the injection patterns in `tools/check-injection.sh` | the incoming boundary | they detect attempts written in Italian; translating them would be translating the thing being looked for |
| the prompt **prose** and the delimiters in `extract.py` | the model contract | a local model follows the language it is spoken to in, so the Italian prompt is Italian and the English one English. The delimiters are a security boundary tuned as it is (`.claude/rules/input-non-fidato.md`). The schema's **field names** are English: they are structure |
| the CLI's Italian option names and values | `--porta`, `--lingua`, `elimina`, `metrico` | *synonyms*, never the only spelling, for anyone with them in a script. `output_axes` normalises the values so nothing downstream sees them |
| the add-on's three configuration keys | `modello_llm`, `scarica_modello`, `file_cookie` | Home Assistant has them saved in the user's add-on configuration. Renaming them silently resets the chosen model and the cookie path to the defaults, and no migration inside the add-on can prevent that |
| every user-facing Italian string | the catalogues | they are read, not called. They live next to their English counterpart and `test_web.py` refuses a half-translated language |

The rule the departures taught, and it is narrower than the one this section used to state:
**a rename over stored data needs a migration and the tests to prove it, not a permanent
exemption.** "It is format" is a statement about the cost, not a veto. What made each of them
safe was the same three things — read the stored shape rather than a version stamp, keep the
old spelling readable for good, and rewrite lazily so the library is never half migrated.

One row that never belonged here at all: the keys of the dictionary `Library.list_` returns.
They looked like format and are not — nothing on disk is keyed that way, only `web/app.js`
reads them — so they moved a whole release before the SQL columns beside them did.

## The compatibility net — in place, and permanent

`Recipe.from_dict` reads **both** spellings, for good. The library stores each recipe as a JSON
blob with the field names of the day, so an Italian-keyed recipe saved months ago has to keep
loading. Old rows are rewritten in English only when that recipe is next saved — lazy,
non-destructive, and with no moment where the library is half migrated.

It is **not** a transitional courtesy to be deleted once "everyone has migrated": there is no
everyone, the library is one user's, and a row written once may sit untouched for years.

The map lives in `recipe.py` as `LEGACY_KEYS`, read through `stored_field(d, name)`, and it is
deliberately the only copy — `store.py` also reads the stored blob directly, without going
through `from_dict`, to build the library listing, and a second copy of the map would diverge
at the first field anyone adds. That second path is the one that fails quietly: not an
exception, just a library of cards with no servings, no times and no cover. `Source` needed the
net too, and more sharply: it used to be rebuilt with `Source(**d)`, and that splat would raise
`TypeError` on every pre-migration recipe — while opening the library, which is the one
operation that must never fail.

**It grew twice, and the second time it stopped being only about keys.** `LEGACY_KEYS` now
covers the nested ingredient and quantity dictionaries as well as the top level, and it is
flat although the recipe is not — which works only while the English names stay unique across
levels, so `test_store.py` asserts that no two levels ever claim the same one.

The values needed a net of their own, and they fail harder than the keys do. A stored quantity
carries `"provenienza": "dichiarato"`, and `Provenance("dichiarato")` on the current enum
raises `ValueError` **inside `from_dict`** — while the library is opening. A missing key gives
`None` and a blank field; a missing *value* gives no library at all. Hence `LEGACY_PROVENANCES`
and `LEGACY_SYSTEMS` in `units.py`, read through `provenance_from_stored` and
`system_from_stored`, both of which **fall back rather than raise**: an unreadable provenance
becomes `absent`, which is in `UNCERTAIN_PROVENANCES`, so the honest answer to "I cannot tell
where this number came from" is also the one that makes the interface flag it for review.

The SQL schema is the one part that is *not* a net but a migration: `_migrate_italian_schema`
renames the table and columns once, in place, and then there is nothing left to be compatible
with. It reads `sqlite_master` rather than a `user_version` stamp, because a version number is
a second source of truth that can disagree with the thing it describes — restore a backup, copy
a file between machines, and it lies.

## Vocabulary

Decided once, used everywhere. Add a row rather than inventing a synonym.

### Types

| Italian | English |
|---|---|
| `Ricetta` | `Recipe` |
| `Ingrediente` | `Ingredient` |
| `Quantita` | `Quantity` |
| `Fonte` | `Source` |
| `Provenienza` | `Provenance` |
| `Lingua` | `Language` |
| `Sistema` | `System` |
| `Tabelle` | `Tables` |
| `Catalogo` | `Catalogue` |
| `Libreria` | `Library` |
| `Trascrizione` | `Transcript` |
| `Media` | `Media` (unchanged) |
| `Esito` | `Outcome` |
| `Lavoro` | `Job` |
| `RegistroLavori` | `JobRegistry` |
| `Errore…` | `…Error` (`ErroreTrascrizione` → `TranscriptionError`) |

### Recipe fields — these are also JSON keys

Migrated, with `LEGACY_KEYS` reading the left column for good.

| Italian | English |
|---|---|
| `titolo` | `title` |
| `ingredienti` | `ingredients` |
| `procedimento` | `method` |
| `descrizione` | `description` |
| `porzioni` | `servings` |
| `tempo_preparazione_min` | `prep_time_min` |
| `tempo_cottura_min` | `cook_time_min` |
| `tempo_totale_min` | `total_time_min` |
| `note` | `notes` |
| `categorie` | `categories` |
| `fonte` | `source` |
| `lacune` / `lacuna` | `gaps` / `gap` |
| `confidenza` | `confidence` |
| `immagini` | `images` |
| `trascrizione` | `transcript` |
| `lingua` | `language` |
| `sistema` | `system` |
| `ha_incertezze` | `has_uncertainties` |
| `gruppo` / `gruppi` | `group` / `groups` |
| `nome` | `name` |
| `riga` | `line` |
| `quantita` | `quantity` |
| `valore` / `valore_max` | `value` / `value_max` |
| `unita` | `unit` |
| `nota` | `note` |
| `testo_originale` | `original_text` |
| `provenienza` | `provenance` |
| `incerta` | `uncertain` |
| `autore` | `author` |
| `piattaforma` | `platform` |
| `titolo_originale` | `original_title` |
| `acquisita_il` | `acquired_at` |

### Recurring verbs and words

| Italian | English |
|---|---|
| `carica_` | `load_` |
| `scrivi_` | `write_` |
| `leggi` | `read` |
| `salva` | `save` |
| `elimina` | `delete` |
| `elenca` | `list_` (bare `list` shadows the builtin) |
| `cerca` | `search` |
| `converti` | `convert` |
| `normalizza` | `normalise` (en-GB, as the rest of the prose) |
| `arrotonda` | `round_` |
| `formatta` | `format_` |
| `percorso` / `percorsi` | `path` / `paths` |
| `cartella` | `folder` |
| `testo` | `text` |
| `messaggio` | `message` |
| `avvertenza` | `warning` |
| `avanzamento` | `progress` |
| `sorgente` | `source` (the CLI argument) |
| `didascalia` | `caption` |
| `densita` | `density` |
| `vaghe` | `vague` |
| `etichette` | `labels` |
| `predefinito` | `default` |
| `disponibili` | `available` |
| `nome_file` | `file_name` |
| `percorso_libero` | `free_path` |
| `da_bozza` | `from_draft` |
| `adesso` (costruttore) | `now` |
| `n_ingredienti` | `n_ingredients` (chiave dell'elenco) |
| `copertina` | `cover` (chiave dell'elenco) |
| `creata_il` | `created_at` (chiave dell'elenco e, dalla migrazione dello schema, anche la colonna SQL) |
| `sigla` | `code_of` |
| `testo_da` | `text_from` |
| `conteggio` | `count` |
| `destinazione` | `target` |
| `misure_a_cucchiaio` | `spoon_measures` |
| `scorpora_` | `split_off_` |
| `prova_` | `try_` |
| `confeziona` | `finalise` |
| `e_…` (predicato) | `is_…` (`e_liquido` → `is_liquid`) |
| `come_…` (ramo di esito) | `as_…` (`_come_conteggio` → `_as_count`) |
| `riga_mela` | `mela_line` |

### Prose

Comments and docstrings in **English**, keeping the register they have in Italian: they
explain the *why*, in plain words, and they name the real incident when there was one. British
spelling, to match the interface catalogue and the READMEs.

**The test modules are a separate step, declared here so it is not forgotten.** When a module
is migrated, its tests are updated as *callers* — the names they import, the attributes they
read, the keyword arguments they pass — and nothing more. Their own function names and
docstrings stay Italian for now. That is deliberate, not an oversight: those docstrings carry
the incident behind each regression ("visto su un reel vero"), which is exactly the reasoning
this migration must not lose, and translating them is careful prose work rather than a rename.
Doing it inside the module's own commit would mix a mechanical change with a judgement-heavy
one in the same diff. The tests get one pass of their own, at the end, together with `docs/`.
