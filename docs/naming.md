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

### Order — revised after the first four modules

The first version of this list said "leaves first, core last", and that is right for *risk*
but wrong for *churn*: every module that touches `Recipe` has to be opened twice, once for
its own identifiers and again when `recipe.py`'s fields are renamed. Converting `units.py`
and `recipe.py` **before** their consumers avoids the second pass.

The two are not swapped blindly, though. `units.py` is the conversion engine — the most
delicate code in the project (`AGENTS.md §3`) — and it is 1270 lines. It wants a session
that starts on it, not the tail of one that has been doing something else all day.

1. **Done:** `asr.py` (the reference for how prose is handled), `percorsi.py` → `paths.py`,
   `audio.py`, `acquire.py` — all leaves — and `store.py`, whose SQL schema and listing keys
   stay Italian as *format* (the reason is in its docstring).
2. **Next, on a fresh session:** `units.py`, then `recipe.py`. Highest risk, and everything
   downstream depends on the names they settle. `recipe.py` is where the compatibility net
   for `from_dict` goes in, in the same commit as the field renames.
3. **Then, once each:** `mela.py`, `documenti.py` → `documents.py`, `extract.py`,
   `pipeline.py`, `api.py`, `cli.py` (internals only — its public surface is already
   English). Every one of these reads `Recipe`'s fields, which is why they come after it and
   not before: converting one now buys a second pass over the same file for nothing.
4. **Last:** `web/app.js` in the same commit as the `Recipe` field renames it reads, then
   the `data/*.yaml` keys with their loader, then `docs/`.

### What an aborted attempt at `units.py` taught

It was tried at the end of a long session and reverted at roughly 60%. Three findings, so
the next attempt does not pay for them again.

**1. The JSON keys and the Python attributes are decoupled in one half and welded in the
other.** `Recipe.to_dict()` builds the ingredient and quantity dictionaries with **string
literals** (`"nome"`, `"quantita"`, `"valore"`), so `Quantity` and `Ingredient` can be
renamed freely without touching a single stored recipe. But the top level starts from
`asdict(self)`, so **`Recipe`'s own fields map straight onto JSON keys** — renaming `titolo`
really does rename it on disk. The compatibility net in `from_dict` is needed for the top
level only; the nested objects need nothing.

**2. Renaming the `MESSAGES` keys breaks every call site inside `units.py` at once**, and
the failures surface one test at a time rather than all together, which makes it look like
progress when it is a queue. Rename the catalogue keys and their `message(...)` call sites in
the same pass, or leave the keys alone.

**3. `note` is three different things** and they collide: `Quantity.note` (singular, the
conversion note), `Ingredient.notes` (the ingredient's own notes) and the `note` parameter
threaded through `normalise_ingredient` into `_normalise_ingredient`. A blanket rename gets
two of the three and leaves an `UnboundLocalError` in the middle of the engine. Map the three
explicitly before starting.

And the practical lesson, which was predicted and then confirmed: **`units.py` needs a
session that starts on it.** Not because it is hard in itself, but because the cascade
through its consumers is long, and a session with little budget left ends with a broken tree
and nothing to show. Reverting cost nothing because everything else was committed — keep
that property.

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
| `"metrico"`, `"imperiale"` | `Sistema` values, `data/vaghe.yaml` and `unita.yaml` keys, stored recipes |
| `"assente"`, `"dichiarato"`, `"convertito:unita"`, `"convertito:densita"`, `"conteggio"`, `"stimato:vaghe"`, `"indeterminato"` | `Provenienza` values, stored recipes, `web/app.js` |
| `quantita_raw`, `unita_raw` | the JSON schema the local model answers with (`extract.py`) — changing it means re-running the model gate |
| `unita.yaml`, `densita.yaml`, `vaghe.yaml`, `ricette.db` | file names |
| the keys inside `data/*.yaml` | renamed in their own step, together with their loader |
| the SQL table and column names in `store.py` | written inside every database on disk; renaming them means `ALTER TABLE` over live data |

The Python *names* around them change; the strings do not. Where a value is user-facing, add
the English spelling as a synonym rather than replacing it — as the CLI does with `--porta`
and `--lingua`.

## The compatibility net, before any field rename

`Recipe.from_dict` must read **both** spellings, for good. The library stores each recipe as
a JSON blob with the field names of the day, so an Italian-keyed recipe saved months ago has
to keep loading. Old rows are rewritten in English only when that recipe is next saved —
lazy, non-destructive, and with no moment where the library is half-migrated.

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
| `Libreria` | `Library` |
| `Trascrizione` | `Transcript` |
| `Media` | `Media` (unchanged) |
| `Esito` | `Outcome` |
| `Lavoro` | `Job` |
| `RegistroLavori` | `JobRegistry` |
| `Errore…` | `…Error` (`ErroreTrascrizione` → `TranscriptionError`) |

### Recipe fields — these are also JSON keys

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
| `sigla` | `code_of` |
| `testo_da` | `text_from` |

### Prose

Comments and docstrings in **English**, keeping the register they have in Italian: they
explain the *why*, in plain words, and they name the real incident when there was one. British
spelling, to match the interface catalogue and the READMEs.
