# Naming — the Italian → English migration

> **Transitional document.** It exists while the codebase is being moved from Italian to
> English, and it gets deleted when the move is finished. Until then it is the single place
> that decides what a thing is called, so that a rename spread over several sessions does not
> produce three names for the same concept.

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

1. **Done:** `asr.py` (the reference for how prose is handled), `percorsi.py` → `paths.py`,
   `audio.py`, `acquire.py` — all leaves — `store.py`, whose SQL schema stays Italian as
   *format* (the reason is in its docstring), `units.py`, the engine, and `recipe.py`, the
   model — the last together with `web/app.js` and `Library.list_`'s output keys, which read
   its fields and could not be left a commit behind.
2. **Next, once each:** `mela.py`, `documenti.py` → `documents.py`, `extract.py`,
   `pipeline.py`, `api.py`, `cli.py` (internals only — its public surface is already
   English). All of these were updated as *callers* when `units.py` and `recipe.py` moved;
   what is left is their own identifiers and prose.
3. **Last:** the `data/*.yaml` keys with their loader, then the test modules' own prose (see
   below), then `docs/`.

### What the two hard modules taught

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

`extract.py` carries an obligation the others do not: it holds the system prompts and the
JSON schema, so after touching it the model gate has to run —
`R2R_TEST_MODELLO=1 uv run pytest tests/test_modello.py`, roughly two minutes, and it needs
Ollama up. Renaming identifiers around the prompts does not change them, but the gate is
cheap next to the risk of finding out later.

## What must NOT be renamed

These are **format**, not code. They are keys in `data/*.yaml` and they are written inside
recipes already saved in the user's library, so renaming them would demand exactly the
destructive migration this migration is avoiding.

| stays as it is | where it lives |
|---|---|
| `"metrico"`, `"imperiale"` | `System` values, `data/vaghe.yaml` and `unita.yaml` keys, stored recipes |
| `"assente"`, `"dichiarato"`, `"convertito:unita"`, `"convertito:densita"`, `"conteggio"`, `"stimato:vaghe"`, `"indeterminato"` | `Provenance` values, stored recipes, `web/app.js` |
| `quantita_raw`, `unita_raw` | the JSON schema the local model answers with (`extract.py`) — changing it means re-running the model gate |
| `unita.yaml`, `densita.yaml`, `vaghe.yaml`, `ricette.db` | file names |
| the keys inside `data/*.yaml` | renamed in their own step, together with their loader |
| the SQL table and column names in `store.py` | written inside every database on disk; renaming them means `ALTER TABLE` over live data |
| the **nested** keys of an ingredient and its quantity — `nome`, `note`, `gruppo`, `lacuna`, `riga`, `quantita`, and inside it `valore`, `valore_max`, `unita`, `provenienza`, `testo_originale`, `nota`, `sistema`, `incerta` | inside every stored recipe and read by `web/app.js`; `to_dict()` writes them as string literals, which is precisely what let `Ingredient` and `Quantity` be renamed for free |
| the keys of the *draft* read by `from_draft` — `titolo`, `ingredienti`, `procedimento`, `porzioni`, `categorie`, `lacune`, `confidenza`, `descrizione`, `tempo_*_min` | the same JSON schema as `quantita_raw` above: it is `extract.py`'s output format, and it moves when `extract.py` does, with the model gate |

One row that did **not** stay: the keys of the dictionary `Library.list_` returns. They looked
like format and are not — nothing on disk is keyed that way, only `web/app.js` reads them — so
they moved to English in the same commit as `Recipe`'s fields and the frontend. `store.py`'s
docstring said so before the move; the SQL columns just above it are the part that is real
format, and those did stay.

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
| `creata_il` | `created_at` (chiave dell'elenco; la colonna SQL resta) |
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
