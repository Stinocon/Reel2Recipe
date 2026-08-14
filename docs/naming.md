# Naming — the Italian → English migration

> **Transitional document, now mostly a record.** It existed while the codebase was moved from
> Italian to English. The move is done: `src/`, `tests/`, `web/`, the `data/` keys and
> `docs/architecture.md` are all English. What survives here is worth keeping until it is no
> longer true — the table of what must *not* be renamed, which is a live constraint on future
> work, and the account of how a rename hides, which cost four real defects to learn.

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
2. **Left in Italian on purpose**, each with its reason in the module that holds it:
   `extract.py`'s prompts, schema and delimiters (the model contract); the URL paths and the
   export's `?formato=` (external surface — the rule is *add a synonym*, as the CLI does with
   `--porta`); the nested ingredient keys, the draft's keys and the file names (format);
   every user-facing Italian string. The SQL columns were on this list and came off it — see
   the table below.
3. **Done since:** the `data/*.yaml` keys with their loader (the tables live in the repo, so
   nothing on a user's disk is keyed that way), and the frontend — `web/i18n.js`'s catalogue
   keys and placeholders, `web/app.js`'s identifiers and prose, and `icone.js` → `icons.js`
   with its `data-icon` attributes.
4. **Deliberately left:** the element **ids** and the **CSS class names**. They live across
   three files at once — `index.html`, `app.js` and `style.css` — so moving them is a step of
   its own with no readability gain for the JavaScript, and a missed class breaks the styling
   silently. `tests/test_web.py` now guards ids in both directions and classes against
   `style.css`, so the step is safe to take later if it is ever worth taking.
5. **Done last:** the test modules' own prose — all ten of them, with the model gate re-run
   for `test_modello.py` — and `docs/architettura.md` → `docs/architecture.md`.
6. **Deliberately left in Italian:** `docs/legale.md` and `docs/condizioni-uso.md`. They are
   authoritative in Italian and carry a non-binding English summary; translating them in full
   would put two published legal versions in circulation, which is a real problem rather than
   a stylistic one (the rule predates this migration).

### What the hard modules taught

The aborted attempt at `units.py` predicted three things. Two were spent immediately — the
`MESSAGES` keys and the three colliding `note`s were mapped up front and cost nothing. The
third turned out to be the axis the whole `recipe.py` step turned on, and it held exactly:

**The JSON keys and the Python attributes are decoupled in one half and welded in the other.**
`Recipe.to_dict()` builds the ingredient and quantity dictionaries with **string literals**
(`"nome"`, `"quantita"`, `"valore"`), so `Quantity` and `Ingredient` were renamed in full
without touching a single stored recipe. But the top level starts from `asdict(self)`, so
**`Recipe`'s own fields map straight onto JSON keys** — renaming `titolo` really does rename it
on disk. So the net went in exactly where it was needed and nowhere else: `stored_field` reads
both spellings at the top level, the nested objects got nothing, and the split is now covered
by three tests in `tests/test_store.py` built on a hand-written pre-migration recipe.

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

### The three ways a rename hides

By the end, the migration had produced four real defects and every one of them was invisible
to `./check.sh`. They fall into three kinds, and the countermeasure for each is now in the
repo rather than in someone's memory.

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

And the one that was not this migration's fault but was found by it: `"Libreria vuota."` had
been `"Library vuota."` since the `store.py` step, and `tests/test_api.py` asserted the broken
string — a test locking a defect in place. Which is the argument for the string-literal diff:
extracting every literal from `src/` before and after, and reading the difference. It caught
four Italian sentences a regex had walked into, a non-breaking space lost by a hand-rewrite,
and a help line that had started advertising a database file that does not exist.

## What must NOT be renamed

These are **format**, not code. They are keys in `data/*.yaml` and they are written inside
recipes already saved in the user's library, so renaming them would demand exactly the
destructive migration this migration is avoiding.

| stays as it is | where it lives |
|---|---|
| ~~`"metrico"`, `"imperiale"`~~ | **moved since**, to `"metric"`/`"imperial"`. `data/` lives in the repo so its keys were free; the stored recipes needed `LEGACY_SYSTEMS` and `system_from_stored` in `units.py` |
| ~~`"assente"`, `"dichiarato"`, …~~ | **moved since**, to `"absent"`, `"declared"`, `"converted:unit"`, `"converted:density"`, `"count"`, `"estimated:vague"`, `"indeterminate"`. The net is `LEGACY_PROVENANCES` and `provenance_from_stored`, which falls back to `absent` rather than raising: `Provenance("dichiarato")` on the new enum raises `ValueError` **inside `from_dict`**, i.e. while the library is opening |
| ~~`quantita_raw`, `unita_raw`~~ | **moved since**, with the rest of the schema. They were never on disk — a draft lives between the model and `from_draft` — so the cost was the model gate, not a migration |
| `unita.yaml`, `densita.yaml`, `vaghe.yaml`, `ricette.db` | file names |
| the keys inside `data/*.yaml` | renamed in their own step, together with their loader |
| ~~the SQL table and column names in `store.py`~~ | **moved since.** They really were format, and the way out was the `ALTER TABLE` this table was avoiding — done once, in place, by `_migrate_italian_schema`. The lesson is narrower than "never rename format": a rename over stored data needs a migration and the tests to prove it, not a permanent exemption |
| ~~the **nested** keys of an ingredient and its quantity~~ | **moved since.** They are `name`, `notes`, `group`, `gap`, `line`, `quantity`, and inside it `value`, `value_max`, `unit`, `provenance`, `original_text`, `note`, `system`, `uncertain`. `LEGACY_KEYS` grew to cover them; being built from string literals was what let them stay, never a reason they had to |
| ~~the keys of the *draft* read by `from_draft`~~ | **moved since**, to `title`, `ingredients`, `method`, `servings`, `categories`, `gaps`, `confidence`, `description`, `prep_time_min`, `cook_time_min`. The prompt **prose** around them stayed in its own language and was rewritten by hand, not substituted |

One row that did **not** stay: the keys of the dictionary `Library.list_` returns. They looked
like format and are not — nothing on disk is keyed that way, only `web/app.js` reads them — so
they moved to English in the same commit as `Recipe`'s fields and the frontend. `store.py`'s
docstring said so before the move; the SQL columns just above it *were* real format, and they
stayed for one more release — until they got the migration that being real format calls for.

The Python *names* around them change; the strings do not. Where a value is user-facing, add
the English spelling as a synonym rather than replacing it — as the CLI does with `--porta`
and `--lingua`.

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
