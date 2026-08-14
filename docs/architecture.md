# Architecture

The *why* behind the choices. For the *what* there is the [README](../README.md); for the
legal side there is [`legal.md`](legal.md), which stays in Italian because it is the version
that holds.

---

## The pipeline

```
  reel URL ──┐
  file ──────┼──▶ acquire ──▶ Media (video/audio + caption + author + url)
  folder ────┘                    │
                                  ├──▶ audio ──▶ WAV 16kHz ──▶ asr ──▶ Transcript
                                  │                                        │
          caption + transcript ──┴────────────────────────────────────────┘
                     │
                     ▼
                 extract  (local LLM through Ollama, output constrained to a JSON schema)
                     │
                     ▼   RecipeDraft — RAW quantities, never converted by the model
                  units    ← data/unita.yaml + densita.yaml + vaghe.yaml (language × system)
                     │
                     ▼   Recipe — metric quantities + provenance + gaps
              ┌──────┴──────┬─────────────┐
              ▼             ▼             ▼
            store         mela        documents
          (SQLite)  (.melarecipe)   (.md / .pdf)
```

Each stage is an independent module in `src/reel2recipe/`. The chain is wired once, in
`pipeline.py`, and the CLI (`cli.py`) and the web interface (`api.py`) use it identically: one
implementation, one place to fix things.

---

## The decisions that matter

### 1. The LLM extracts, the code converts

This is the central principle, the one the perceived quality follows from. An LLM converting
"1 cup of flour" into grams produces a plausible and often wrong number, because it is
remembering rather than calculating. So:

- The model reports the quantity **as it appears** (`quantity_raw`, `unit_raw`) and never
  converts.
- `units.py` converts with deterministic, versioned tables (`data/`).
- With no known density for an ingredient, the volume→weight conversion **is not done**: the
  volume is kept and the gap declared. Never an invented density.

Every quantity carries its **provenance** (`declared`, `converted:density`,
`estimated:vague`, `indeterminate`, …), which the interface and the exports use to tell data
from an estimate at a glance.

**The golden rule: invent nothing.** It holds for the model and for the code, and not only for
quantities. If a weight, a time or a step cannot be deduced from the material, it is not filled
in at random: the hole is left and declared among the `gaps`. An incomplete but honest recipe
is usable; one completed at random is harmful, because in a kitchen a wrong weight you do not
know is wrong does real damage. `extract.py`'s prompt imposes it on the model, `units.py` and
`recipe.py` honour it in code, and `tests/test_modello.py` verifies it against the local model
actually installed — it is the gate protecting the project's central promise.

The tables follow the same discipline: **every density in `data/densita.yaml` declares its
`source`**, and a test demands it. A number without a provenance is a number you cannot trust.

**Two axes, not one: `system` and `language`.** The product works in Italian/English and in
metric/imperial, and the two axes stay separate because they do not coincide (an Australian
reads in English but cooks in grams). The **system** decides the numbers — it is settled at the
conversion, in `units.py`, and it applies to the *raw* quantity: towards imperial density is not
crossed and quantities are written as fractions (`3/4 cup`), because a measuring cup has no
0.75. The **language** decides the words: unit labels, eyeball measures and gap messages. The
first two live in `data/`, indexed by language and by system; the messages live in `units.py`
(they are program strings, not data). Temperatures follow the system in both directions
(°F↔°C). The translation of names and method is done by the model in `extract.py`, with one
system prompt per language — and it is the only non-deterministic piece of the path, hence the
least reliable.

**A third axis, which does not belong to that pair: the language *spoken* in the reel.** It
concerns the input, not the output, which is why it is called `audio_language` and not
`language`: it serves Whisper alone. The default is `None`, i.e. *recognise it yourself*, which
is what Whisper does natively and reports in `Transcript.language`. **It is not deduced from
the output language**: an English reel becoming an Italian recipe is the normal case, not the
exception, and tying the two axes together would mean declaring a false language to Whisper
every time we translate. There used to be a hard-wired `"it"` here that no option could remove,
and the damage was not a crooked translation but a crooked **transcription** — Italian words
forced onto English sounds, with the whole rest of the chain working on that. Invisible
downstream, because the local model produces a plausible recipe anyway.

### 2. Reading comes before conversion

Six extractions on real reels produced four defects, and **none of them was in the conversion
engine**. They were all cases where the model put the right thing in the wrong field and the
code read it literally. It is a distinction worth keeping in mind, because faced with a wrong
number the temptation is to reach into `units.py` — and four times out of four that would have
been the wrong analysis.

That is why `normalise_ingredient` is a **wrapper** that puts the input back in order before
calling `_normalise_ingredient`, which is the real engine. Given a coherent pair the engine
already does the right thing, and the most delicate part of the project stays untouched.

What the wrapper straightens out:

- **Quantity and unit contradicting each other.** Captions often write the same amount twice —
  "1¼ cups (300 ml) water" — and the model mixes the pieces. Out came "1 ml" of water instead of
  300, with provenance `declared`: a wrong number presented as certain. **The internally
  coherent pair wins** ("1¼" and "cups" sit in the same piece of text, the "ml" comes from
  elsewhere in the sentence) and **the discrepancy is declared anyway**, even when the choice
  gets the value right: the source was ambiguous there and the cook has to know. Outside this
  case the policy does not change: if the model isolated the unit, its one is the good one.
- **A word in brackets is usually not a unit — but you have to look inside.** "1 melanzana
  bianca (facoltativa)" became "1 (facoltativa) melanzana bianca". The first version of this
  rule said "no unit of measurement is written in brackets" and stopped there, because that
  looks like a cheaper and safer criterion than a vocabulary. It was false: the model also
  writes `unit_raw="(g)"`, and since the normalisation already strips brackets, before that
  check "200" + "(g)" converted correctly. Demoting it to a note turned "200 g di farina" into a
  count of two hundred flours, **without even a gap** — the regression lasted half a day and was
  found by a cold re-read, not by the tests. Now the content is inspected: if it is a known
  unit, nothing is touched.
- **A measure that ended up in the wrong field is still an indication.** The model has three
  ways of getting the field wrong, all three seen: inside the name ("semi di sesamo q.b."), in
  brackets within the name ("sale (un pizzico)") and — when it really does not know where to put
  it — in the `note`. In all three the quantity arrived empty and the recipe declared "quantity
  not given in the reel": **a false gap**. They become an open-ended quantity or a declared
  estimate. The criterion is that the text be a measure **known** to `vaghe.yaml`, not that it
  sit in a particular field: "burro (a temperatura ambiente)" stays a note. And the comparison
  is **exact and anchored at the end**, never by containment, or "pomodori poco maturi" would
  become an open-ended quantity because a vague word appears in the middle. In brackets, **at
  least two words** are also required: many `vaghe.yaml` entries have single-word aliases —
  noce, tazza, bicchiere, filo — which after a name indicate its variety or its container, not
  its dose. "frutta secca (noce)" is not ten grams of nuts.

The common thread is the most important criterion to come out of those trials: **a false gap is
worse than no gap**, because it teaches you not to trust even the true ones — and the honesty of
the entire product rests on that mechanism.

Those defects had been found only because somebody was watching: no test covered `extract.py`'s
prompt and schema. Now `tests/test_modello.py` covers them, with **synthetic** captions that
reproduce the patterns without bringing third-party material into the repo. This is not theory:
the fourth variant — "q.b." landing in the `note` — was found by that suite on its first run,
not by a reel.

### 3. When the prompt and the schema contradict each other, the schema wins

`porzioni` and the times always came out empty, even from sources saying "Serves 2" or "180° per
25'-30'". The prompt insisted, the mapping was right: the culprit was the **JSON schema**, where
those fields were optional. With schema-constrained output the model is free to omit an optional
field, and `qwen2.5:14b` omitted it systematically. The prompt asks, the schema permits: **the
schema is the mechanical constraint on the decoding, the prompt is a prayer.**

But the remedy has a symmetric cost. Made required, `tempo_preparazione_min` was **invented** —
15 and 30 minutes on sources that stated no prep time at all, splitting a cooking range across
the two fields. So a field is made required only where the datum is normally present in the
sources: `porzioni` and `tempo_cottura_min` yes, `tempo_preparazione_min` no. A few genuinely
stated prep times are lost, and that is fine: **a missing time is less harmful than an invented
one.**

**Requiring a field is not enough: you also have to tell it what shape to take.** `porzioni`
became required but the prompts said nothing about it, and the model improvised a whole sentence
— "These ingredients make 6 burgers." instead of "6 burgers", in a field recipe apps show next
to the title. One line of instruction with three examples closed the matter on five sources out
of five. The general rule holds: if a field systematically comes out in the wrong shape, before
blaming the model check whether anybody ever told it what to write there.

### 4. Everything local, by choice and not as a fallback

Transcription with Whisper on the machine, structuring with an LLM through Ollama. No paid
service, no API key, no data leaving the PC. The constraint is the user's, explicitly: the
product has to keep working even if every subscription stops being paid tomorrow. It follows
that the "brain" is Ollama (mandatory) and not a remote API.

### 5. The pipeline degrades, it does not stop

If the audio is missing, or the transcription fails, or a backend is not installed, the job
**carries on with the caption alone** and says so. A great many cooking reels have the complete
recipe in the post's text: giving up over an audio problem would mean losing a recoverable
recipe. Every non-fatal failure becomes a *warning*, not an exception.

### 6. Transcription with two backends and a fallback

`asr.py` exposes a single interface over two local implementations:

- **mlx-whisper** — the GPU of Apple Silicon Macs (Metal), far faster where available.
- **faster-whisper** — CPU, portable everywhere, the reference.

With `backend="auto"` the fastest available is used and the other takes over if the first fails
at runtime. This too was an explicit request: maximum coverage.

### 7. Static frontend, no build

The interface is a single page (HTML + CSS + ES-module JS, in `web/`), served by FastAPI. No
React, no Vite, no `node_modules`, no toolchain to maintain. PersonalFinance uses React because
it has dozens of pages; here it would be oversized. If it is ever needed, we migrate then.

Extraction is slow (download + transcription + LLM), so it does not block the HTTP request: it
starts in a thread and the progress reaches the page over Server-Sent Events. The *Cook* bar
tells the stages in real time.

**The interface is bilingual, and its catalogue lives in the frontend** (`web/i18n.js`), not in
the server. The criterion is *whoever writes the string owns it*: the buttons' words are
written by the page, the progress lines and the errors are written by Python and stay in
`pipeline.py` and `api.py`. Moving them all into the server would force the page into a network
round trip before it could draw itself, with a flash of untranslated text on every load.

The two sides follow different axes, though, and the difference is deliberate. The **page**
follows the interface's language, which travels on every call as `ui_language` — a name distinct
from `language`, which on `/api/cook` already means something else: which language to *produce
the recipe in*. The **progress and the warnings** follow the recipe's language instead, because
they end up next to the `gaps`, which are saved inside the recipe in its language; letting them
diverge would give a card half in one language and half in the other. In normal use the two
values coincide anyway, because the recipe's language follows the interface's.

Because the frontend has no toolchain, the things that would break silently there are covered by
structural guards in `tests/test_web.py`, which read the files rather than executing them: every
`#opt-…` drawn is queried by some module and every selector points at something that exists;
neither language of the catalogue is half translated; the placeholders a sentence declares match
the arguments the calls fill them with; the JSON keys the page reads exist in what the server
actually produces; and every CSS class used has a rule in the stylesheet. Each of those guards
was added the day something got past the suite, and each was verified by breaking it on purpose.

The API calls start from the page's base (`document.baseURI`) and not from the site's root.
Locally it is the same thing; under Home Assistant's Ingress it is not, because there the page
lives behind a token prefix and an absolute `/api/status` would land on Home Assistant's API
instead of ours. One line of difference, a failure that otherwise shows up only in production.

### 8. SQLite with full-text search for the library

The real problem the project solves is not "extracting a recipe" but **finding it again months
later**. That is why the library is a searchable database (`store.py`, FTS5) and not a folder of
files: searching "courgettes" or "gluten free" across titles, ingredients and methods is exactly
what is wanted when you open the fridge. Deduplication on the source URL means re-importing the
same reel updates the recipe instead of duplicating it.

The FTS5 index is a standard table (not *contentless*): it keeps a copy of the text and in
exchange supports deletion and modification by row — both needed when the user corrects a
recipe. Duplicating the text is irrelevant for a personal library.

**The SQL names stay Italian, and that is not an oversight.** Table and column names are not
code, they are *format*: they are written inside every database already on a user's disk, and
renaming them would mean an `ALTER TABLE` over live data. The same reasoning covers the nested
keys of a stored recipe. What did move to English is what nothing on disk is keyed by: the
top-level JSON fields — with `LEGACY_KEYS`/`stored_field` in `recipe.py` reading both spellings
for good, so a recipe saved months ago keeps opening — and the keys `Library.list_` hands to the
frontend. The full reasoning is in [`naming.md`](naming.md).

### 9. Manual review is part of the flow, not a fallback

The LLM proposes, the user corrects, and **only then** does it export. The interface allows the
recipe to be edited before saving or exporting it; the API exposes `PUT /api/recipes/{id}` for
the same purpose. A local model of 7–14 billion parameters is wrong more often than a frontier
one: giving the user the last word is not a patch, it is the right way to use a tool that
assists without claiming to be infallible.

### 10. One single decision about where the data lives

`paths.py` decides `workspace/`'s root for everybody: library, downloaded media, exports.
Before, the same line (`parents[2] / "workspace"`) appeared identically in `store.py`,
`pipeline.py` and `api.py` — three copies of one fact, i.e. three chances to diverge.

There was a fourth, which the first consolidation missed: the default of `r2r export --out`,
and a **relative** one at that, so resolved against the current directory instead of the
project. In the container it would have written next to the code while the web interface's
export landed on the persistent volume — two commands doing the same thing in two different
places. It is the typical way a consolidation stays half done: the copies that look alike are
merged and the one written in another shape survives.

It is needed because the root is not always next to the repo. Inside a container the code is
read-only and the data has to land on the persistent volume: `R2R_WORKSPACE` says so without
the code having to know where it is running. The other variables (`R2R_COOKIES`,
`R2R_TIMEOUT_LLM`) answer the same question for the cookies and for the patience to grant a
model running on a CPU; they are listed in the README.

The security boundary does not move with the root: whatever the folder is, there is
third-party material inside it and it is not committed.

---

## The Mela format — the two details that break silently

The format is documented by its author at <https://mela.recipes/fileformat/>. Two things have
to be known, because getting them wrong gives no error but a wrong import:

1. `ingredients` and `instructions` are **strings separated by `\n`**, not arrays. A line
   starting with `#` becomes a group heading.
2. Mela's parser already recognises quantities and units **in Italian**. So the right shape for
   an ingredient is the plain string `"200 g farina 00"`: inventing a structure of our own and
   recomposing it would make the result worse. Text in brackets is treated by Mela as a comment
   — that is where the notes and the equivalents go (`≈ 4 g`).

Both are protected by tests in `tests/test_mela.py`, but the real proof is still **opening a
`.melarecipe` in Mela on iOS** and checking that everything arrives clean.

### Markdown and PDF (`documents.py`)

Mela is the best format *if* you have it. Anyone who does not would be left with nothing to
keep, and a recipe you cannot keep has not solved the problem it started from: finding it
again. Hence two formats that ask nobody to install anything in order to **read** them —
Markdown opens everywhere and stays editable, a PDF prints and can be sent.

The two share the same structure (`_blocks`), so the same recipe says the same things in the
same order in both; only the rendering changes. **The gaps and the estimates are exported here
too:** a clean PDF hiding the uncertainties would be prettier and more dangerous than one that
declares them.

Two practical constraints of the PDF, both documented in the module. The standard fonts cover
Latin-1: Italian accents are there, emoji are not, and rather than letting them become black
rectangles `_pdf_text` translates the symbols we actually produce (`≈` → `~`) and drops the
rest. The provenance line goes in the **page footer** and not at the end of the text: in the
flow it ended up alone on a nearly empty second page every time the recipe filled the first.

`reportlab` sits in the optional `doc` extra and is pure Python, with no system libraries to
install alongside — a necessary condition for running inside a container or on a Raspberry Pi.

---

## Security boundaries

- **Untrusted input (incoming).** The caption and the transcript are arbitrary third-party
  text: *data to analyse, never instructions to execute*. `extract.py` hands them to the model
  inside explicit delimiters and the prompt requires that any commands contained in the material
  be disobeyed. It is the boundary mirroring the anti-leak one.
- **Third-party material (outgoing).** Everything downloaded stays in `workspace/`, outside git.
  The guard in `check.sh` verifies it before every commit. Details in [`legal.md`](legal.md).

---

## The two contracts with the Home Assistant add-on

The add-on lives in another repository (`Stinocon/addons`) and **clones this one at build
time**, from `main`. Neither repo checks the other, so a rename here can stop a build there
with nothing warning us. Two of the coupling points are contracts in the strict sense, and
both are held still by `tests/test_cli.py`:

1. **The start-up line.** `r2r --ollama URL serve --host 0.0.0.0 --porta 8500`. `--ollama` is a
   *global* option and goes before the subcommand; put after, argparse exits with code 2, s6
   restarts for ever and the Ingress answers 502 without naming the cause. It has happened.
   Every Italian option name is still accepted as an alias for exactly this reason.
2. **The symbols its Dockerfile imports.** The build ends with a sanity check —
   `from reel2recipe.paths import REPO_ROOT`, `from reel2recipe.units import load_tables` —
   that verifies the clone is installed in a shape where the code can still find `web/` and
   `data/`. This one was *not* written down anywhere, and two consecutive renames broke it:
   `percorsi` → `paths`, then `carica_tabelle` → `load_tables`. The add-on could not build
   through either, and the check that says "the coupling points hold" kept coming back green
   because it was reading a list of four that should have had five.

The remaining links — the three environment variables and the frontend's relative API calls —
are not tested from here, because breaking them shows up immediately in the add-on's log.

---

## Why the structure stays flat

This project's value lies in its clarity: lean, clean, as simple as possible without
sacrificing features. One module per pipeline stage, the tables in `data/`, the frontend with no
build, and nothing else until it is really needed.

The same holds for what gets added: before introducing a file, a layer of abstraction or a tool,
the question is whether it solves a problem **already seen**, not whether it might come in handy
one day. A file that can be shortened without losing a piece of reasoning is to be shortened.
