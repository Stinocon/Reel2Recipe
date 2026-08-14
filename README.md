<p align="center">
  <img src="docs/brand/banner.svg" alt="Reel2Recipe" width="860">
</p>

<p align="center">
  <strong>English</strong> · <a href="README.it.md">Italiano</a>
</p>

# Reel2Recipe

> **Read this first.** A **personal** project, published as is and **with no warranty**: it
> is not a finished product, not a commercial one, and it will not become either. It was
> written in large part **with an AI assistant**, under human guidance and review — that was
> part of the point.
>
> Extraction is automatic and can get things wrong. The project is built to make its
> uncertainties visible rather than hide them, but **read the recipe before you cook it**,
> weights and times above all; and if you have allergies, go back to the original source,
> which is always cited. Details in [`docs/condizioni-uso.md`](docs/condizioni-uso.md)
> (Italian).

**From Instagram cooking reels to a tidy recipe book you can import into
[Mela](https://mela.recipes).** Paste a link, press *Cook*, and you get a clean recipe —
ingredients in grams and millilitres, the method rewritten in your own words, and the
original source always credited.

It came from a concrete problem: you save dozens of recipes on Instagram and then never find
them again. Reel2Recipe extracts them, makes them searchable, and moves them into the app you
actually cook from.

> **Everything happens on your own computer.** No online AI, no subscription, no API key, no
> data leaving the machine. If you stop paying for every service you have, Reel2Recipe keeps
> working exactly as before.

## Languages

**Italian and English, on both sides of the tool.**

- **The interface** is available in both. The switch is in the top right of the page; the
  choice is remembered, and on first open it follows your browser's language.
- **The recipes** can be produced in either language, independently of the interface, and in
  either **metric** or **imperial** units.
- **The source reel** can be spoken in either language, and you do not have to say which:
  Whisper detects it. An English reel can become an Italian recipe, and the other way round.

The three are separate axes, described under
[Language and measurement system](#language-and-measurement-system). Be aware of one honest
limitation before you rely on it: translating **ingredient names** is the least reliable part
of the whole chain — see [the note on limits](#honesty-about-the-limits). The numbers stay
right; it is the words that slip.

> **A note on this documentation.** This README and the add-on's are kept in English and
> Italian, as two copies that move together. Everything else exists in one language only,
> chosen by its audience: [`docs/architecture.md`](docs/architecture.md) is in English,
> because it explains code whose identifiers and comments are English. The two legal
> documents stay **authoritative in Italian**, with a non-binding English summary at the top:
> two published legal versions that drift apart are a real problem, not a stylistic one.

---

## What it does, briefly

1. **Takes a reel** — from a link, from a video file you already saved, or from a whole
   folder (batch mode, for working through the backlog).
2. **Reads everything** — the post's caption and the speech in the video (transcribed with
   Whisper, locally).
3. **Reconstructs the recipe** — with a local language model (via
   [Ollama](https://ollama.com)): title, ingredients, method, servings and cooking time.
   *Preparation* time is only extracted when the source states it plainly: forcing the model
   to fill it in made it invent one, and a missing time does less harm than a wrong one.
4. **Converts the amounts** — "1 cup of flour" becomes "120 g", "2 tbsp of oil" becomes
   "2 tbsp (≈ 30 ml)". The conversion is **deterministic**, based on verified density tables,
   not guessed by the model (see [The principle that matters](#the-principle-that-matters)).
5. **Files and searches** — every recipe in a searchable local library.
6. **Exports for Mela** — as `.melarecipe`, with ingredient groups, times and a link back to
   the source.

---

## Installation

You need **[uv](https://docs.astral.sh/uv/)** (the script installs the rest).
In a terminal, inside the project folder:

```bash
./install.sh
```

The script checks and, where it can, installs everything needed by itself:

| Component | What it is for | Required? |
|---|---|---|
| **uv** | the Python project manager | yes |
| **Ollama** + a model | the "brain" that structures the recipe | yes |
| **ffmpeg** | pulls the audio out of videos | for speech (without it, captions only) |
| **Whisper** (local) | transcribes the speech | for speech |

Where it cannot install something on its own (for instance if Homebrew is missing on macOS)
it tells you exactly what to do. You can run it as many times as you like: it is idempotent.

To check at any time what is ready:

```bash
uv run r2r check
```

---

## Usage

### Web interface (recommended)

```bash
uv run r2r serve
```

Then open **http://localhost:8500**. Paste a reel's link in the bar, press *Cook*, and follow
the extraction phase by phase. When the recipe is ready you can **correct it by hand** (the
model proposes, you have the last word), save it to the library or download it for Mela.

You can also **drag a video** straight onto the page.

### From the terminal

```bash
# Extract a recipe from a link and save it to the library
uv run r2r cook https://www.instagram.com/reel/XXXXX/

# From a file you already have, with the caption pasted in
uv run r2r cook ~/Videos/reel.mp4 --caption "1 cup flour, 2 eggs..."

# Many reels in a row: a folder of videos, or a .txt with one URL per line
uv run r2r batch ~/Videos/reels-to-process/ --export workspace/export/
# (audio files Reel2Recipe extracted itself are skipped: no double processing)

# Search the library
uv run r2r list --search "courgettes"

# Export
uv run r2r export 42                    # one recipe, for Mela
uv run r2r export --all                 # the whole library as one .melarecipes
uv run r2r export 42 --format pdf       # or markdown, or several formats at once
uv run r2r export 42 --format markdown pdf mela

# Delete a recipe from the library (asks for confirmation; --yes skips it)
uv run r2r delete 42
```

> **If you used the older Italian names**, they still work: `--lingua`, `--sistema`,
> `--didascalia`, `--modello`, `--cerca`, `--formato`, `--tutte`, `--si`, `--porta` and the
> `elimina` command are kept as aliases, and so is the `R2R_PORTA` variable. Nothing you have
> already typed or scripted breaks.

### If you do not use Mela

`.melarecipe` is the best format *if* you have Mela. Otherwise the same recipe comes out as
**Markdown** (opens anywhere and stays editable) or **PDF** (prints and sends), from the
command line with `--format` or from the buttons under the recipe card in the web interface.

All three formats also carry the **gaps** and the amounts that are our own estimates: a clean
PDF that hid the uncertainties would be prettier and more dangerous. Markdown needs nothing;
the PDF uses `reportlab`, which `./install.sh` installs by itself (by hand:
`uv sync --extra doc`).

### Language and measurement system

**The interface is bilingual**, Italian and English. The switch sits in the header, top
right: the choice is remembered, and on first open it starts from your browser's language.

From that choice a chain of three links descends, each falling back to the one before it: the
**interface** decides the **recipe**'s language, which decides the **measurement system**.
Change nothing and you get a coherent set; cross them at any link if you want to — an English
interface with Italian recipes is a legitimate combination, and for someone who cooks in one
language and lives in another it is the right one.

There is no interface on the command line, so there the axes are two and start from the
recipe:

```bash
uv run r2r cook <url> --language en                    # recipe in English, imperial units
uv run r2r cook <url> --language en --system metric    # English, but grams and ml
uv run r2r cook <url> --system imperial                # Italian, but cups and ounces
```

In the web interface the same two selectors live under *Options*, and by default follow the
link above them. The system, if you do not choose one, follows the language (Italian →
metric, English → imperial), but you can cross them: an English or Australian cook reads in
English and weighs in grams.

Then there is a further axis with nothing to do with those two, because it concerns the
**input**: the language *spoken* in the reel, which Whisper needs in order to transcribe. By
default it is not declared at all — Whisper detects it, which is the thing it natively does —
and that is what lets you process an English reel and get an Italian recipe out of it. It
does not follow the output language, because translating is the normal case. You can force it
when detection gets it wrong, for instance on very short or noisy audio:

```bash
uv run r2r cook <url> --spoken-language en    # it is spoken in English, do not guess
```

The difference between the two output axes is sharp. The **system** changes the numbers and
the code does it, deterministically: "1 cup of flour" becomes 120 g in metric and stays
"1 cup" in imperial, written as fractions ("2 1/2 cup"), the way a measuring cup works. The
**language** changes the words. Unit labels, export section headings and messages are always
translated; ingredient names and the method are translated by the local model at extraction
time, and that is the weakest part — see the note below.

#### Honesty about the limits

> Translating names and the method is the least reliable part, and the only
> non-deterministic step in the whole path. On an **already Italian** source the quality is
> very good. On an **English** source ingredient names go wrong with some regularity:
> `berries` became "fragole" (strawberries), `flax seeds` became "semi di lecithia" (not a
> word), `a pinch` became "una pizzetta". A **bilingual** caption makes it worse, because the
> model draws on both languages: an English-German post produced "dinkel fette". **Towards
> English**, from an entirely Italian text, `qwen2.5:14b` tends to stay anchored to Italian:
> it translates the title but not always the list.
>
> In every one of these cases **the amounts stay correct**: the words slip, the numbers do
> not. It is the reason conversion is not entrusted to the model, and why reviewing before
> export is part of the flow rather than a fallback.

### Private reels

For reels that require you to be signed in, pass the cookies of the browser you signed in
with:

```bash
uv run r2r cook <url> --cookies chrome    # or safari, firefox
```

Where there is no browser — inside a container, for instance — export the cookies in Netscape
format and point at the file with `R2R_COOKIES=/path/cookies.txt`. If the variable points at
a file that does not exist, the error says so straight away instead of letting the download
fail for no apparent reason.

### Environment variables

Few, and all of them exist to run the product where the default paths do not suit.

| variable | effect |
|-----------|---------|
| `R2R_WORKSPACE` | Moves the data root (library, media, exports). Default: `workspace/` next to the repo |
| `R2R_COOKIES` | Netscape-format cookie file for reels that require signing in. It is never modified: a temporary copy is used and deleted when the download ends |
| `R2R_TIMEOUT_LLM` | Seconds granted to the model for one answer — the number alone. Default 300: raise it on a CPU without an accelerator |
| `R2R_PORT` | Port for the interface started by `tools/serve.sh`. Default 8500. The old `R2R_PORTA` is still read |

### Home Assistant

There is an add-on that runs the whole thing — interface, Whisper and Ollama — on an
always-on server, with the interface in the sidebar:
**[Stinocon/addons](https://github.com/Stinocon/addons/tree/master/reel2recipe)**. It needs an
amd64 machine with 16 GB of RAM: inference runs on the CPU.

---

## How to import into Mela

Reel2Recipe produces `.melarecipe` files (one recipe) or `.melarecipes` (several recipes, in
a zip). To import them:

1. Save the exported file somewhere Mela can reach it (AirDrop, iCloud Drive, an email to
   yourself…).
2. Open it on iPhone/iPad/Mac: Mela recognises it and offers to import.

Mela's parser already reads amounts in both languages, so ingredients arrive with their
measurement and groups ("For the base", "For the cream") are respected. The **link to the
source** is always included, so you can go back to the original reel.

---

## The principle that matters

The piece this project is proudest of is the **conversion of amounts**, and it is where it
differs from simply "asking an AI to transcribe the recipe".

Ask a language model "how many grams is a cup of flour?" and it gives you a *plausible*
number. Sometimes 120, sometimes 128, sometimes 150 — and for sugar it may repeat the same
number it gave for flour, which is wrong by **67%** (same volume, different densities). The
model is not calculating: it is misremembering.

Reel2Recipe does something else:

- The model reports the amount **exactly as it appears** in the reel ("1", "cup") and **never
  converts it**.
- The conversion is done by a deterministic module, with **verified density tables** (one per
  ingredient). Every density cites the source it comes from — the USDA FoodData Central
  database or King Arthur Baking's weight chart — together with the per-cup weight it was
  computed from, so you can go and check it.
- If we do not know an ingredient's density, the amount **is not converted to weight**: the
  volume is kept and the gap is declared. A number is never invented.

The result: every amount carries its own provenance — *declared* by the reel, *converted*
from a table, or *estimated* (for eyeball measures like "a pinch"). Estimates are always
flagged, so you know which ones to trust. **A declared gap is worth more than an invented
number**: in a kitchen, a wrong weight you don't know is wrong does real damage.

The tables live in [`data/`](data/) and are readable and editable: if a density does not
convince you, correct it there — declaring the source, which the tests insist on.

---

## What is allowed, and what is not

Reel2Recipe is meant for **personal use**, on content **you have already saved**. The terms
addressed to whoever uses the tool are in
[`docs/condizioni-uso.md`](docs/condizioni-uso.md); the legal analysis behind the design
decisions is in [`docs/legale.md`](docs/legale.md). Both are authoritative in Italian and
open with an English summary. In short:

- **Ingredient lists are not protected by copyright**: extracting and reformatting them is
  lawful.
- **A creator's descriptive prose is protected**: this is why Reel2Recipe *rewrites* the
  method instead of copying it, and **always** cites the original source.
- **Downloading a reel from Instagram breaches the platform's Terms of Use.** That is why
  this tool runs locally, for personal use: it is not a public service downloading on
  someone else's behalf. If you use it on other people's reels, do it sensibly and for
  yourself.
- **Downloaded files stay on your computer**: the `workspace/` folder is excluded from git
  and is never shared.

---

## Project structure

```
src/reel2recipe/     the code
  acquire.py         fetching the reel (URL, file, folder)
  audio.py           audio extraction with ffmpeg
  asr.py             local transcription (Whisper) with a fallback
  extract.py         structuring with a local LLM (Ollama)
  units.py           deterministic conversion of amounts — the heart of the project
  recipe.py          the model of a recipe
  mela.py            export in Mela's format
  documents.py       export to Markdown and PDF, for those without Mela
  store.py           the recipe book (SQLite + full-text search)
  paths.py           where the data lives (one decision, movable with R2R_WORKSPACE)
  pipeline.py        the whole chain
  api.py             the web interface
  cli.py             the terminal commands
data/                the conversion tables (readable and editable)
web/                 the interface (HTML/CSS/JS, no build step)
  i18n.js            the interface's words, in Italian and English
  icons.js           the SVG icons, embedded (no CDN)
tools/               support scripts (starting Ollama and the interface, boundary guards)
docs/                documentation: architecture in English, the two legal notes in Italian
tests/               the tests
workspace/           your data — never shared (in .gitignore)
```

Technical documentation: [`docs/architecture.md`](docs/architecture.md).

### If you are reading the code

**The codebase is in English** — identifiers, comments, tests, the JSON keys on disk, the SQL
schema, the frontend's ids and classes, the build scripts, the add-on's runtime log and the
architecture document. The Italian you will still meet is deliberate, and it falls into three
groups:

- **The prompts the local model reads.** `extract.py`'s two system prompts stay each in
  their own language, because a local model follows the language it is spoken to in — and the
  delimiters that fence off untrusted input stay Italian too, being a security boundary tuned
  as it is. The schema's **field names** are English: they are structure, not prose. Anything
  in that file moves only together with a re-run of the model gate.
- **Kitchen vocabulary, which is data.** Unit names (`cucchiaio`), ingredient names
  (`farina 00`) and the eyeball measures (`q.b.`) in `data/*.yaml`. These are what the model
  writes and what the lookup matches against; the English aliases sit next to them
  (`all-purpose flour`, `a pinch`). The same goes for the patterns in
  `tools/check-injection.sh`, which detect prompt-injection attempts written in Italian.
- **The CLI's Italian option aliases**, kept as *synonyms* rather than as the only spelling
  (`--porta`, `--lingua`, `elimina`), for anybody who has them in a script or in their shell
  history. The URL paths and query parameters used to be in this group and are not any more:
  the only client is `web/app.js`, which ships in the same commit. Nor does the add-on depend
  on them any longer — its start-up line uses `--port`.

A compatibility net keeps the old spelling readable **for good**: a recipe saved before any
of this still opens, and is rewritten in English only when it is next saved, so the library is
never half migrated at any moment. `LEGACY_KEYS` in `recipe.py`, `LEGACY_PROVENANCES` and
`LEGACY_SYSTEMS` in `units.py`. The SQL schema is the exception — there a one-off `ALTER TABLE`
migration replaced the need for a net.

[`docs/naming.md`](docs/naming.md) is the map: what moved, what did not, and why. It also
records the six defects the migration produced and the guards added to catch their kind, the
last two of which were an assertion that passed on an empty list and a guard with an exemption
written into its own docstring — worth ten minutes before a large rename in this repo.

---

## Frequently asked questions

**Do I have to pay for anything?** No. It all runs locally and it is free. The only cost is
disk space for the Ollama model (~5 GB) and the Whisper one (~1.5 GB), downloaded once.

**Does it work offline?** After installation, yes — except for downloading a new reel from a
URL, which obviously needs the internet. A reel you already have is processed offline.

**What about recipes in other languages?** An English reel can become an Italian recipe or
stay English, as you prefer — names and method translated, units converted, Fahrenheit
brought to Celsius. Only Italian and English are supported as *output* languages; the spoken
input can be anything Whisper recognises, though the further you get from those two the more
the translation slips. See
*[Language and measurement system](#language-and-measurement-system)*.

**What if a reel has no recipe written or clearly spoken?** Reel2Recipe extracts what it can
and **declares the gaps** instead of filling them in at random. You can then complete it by
hand.

---

## Licence

Reel2Recipe is distributed under the **MIT** licence (see [`LICENSE`](LICENSE)): you may use,
modify and redistribute it freely, including commercially, keeping the attribution.

Third-party material the project includes or uses — the Material Symbols icons embedded in
the interface, the tools installed separately, the density sources — is listed in
[`NOTICE.md`](NOTICE.md) with the respective licences. The same criterion as the densities in
`data/` applies: an attribution nobody can verify is not an attribution.
