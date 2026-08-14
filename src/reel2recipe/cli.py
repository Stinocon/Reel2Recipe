"""cli.py — Reel2Recipe from the command line.

    r2r cook <url|file>       extract a recipe and save it to the library
    r2r batch <folder|.txt>   process many reels in a row
    r2r list [--search ...]   list or search the library
    r2r export <id|--all>     export to .melarecipe / .melarecipes, markdown or pdf
    r2r delete <id>           remove a recipe from the recipe book
    r2r serve                 start the web interface on http://localhost:8500
    r2r check                 verify that every component is ready

Every Italian option name is still accepted as an alias (`--cerca`, `--tutte`, `--porta`,
`elimina`): the add-on's start-up line depends on it. See `_parser`.

All local: no API key, no paid service.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .units import LEGACY_SYSTEMS, Catalogue, System, text_from

# ANSI colour codes, switched off when the output is not a terminal (a pipe, a log file).
_TTY = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def ok(t: str) -> str: return _c(t, "32")
def warn(t: str) -> str: return _c(t, "33")
def fail(t: str) -> str: return _c(t, "31")
def dim(t: str) -> str: return _c(t, "2")


def _cli_progress(stage: str, message: str) -> None:
    print(f"  {dim('▸')} {message}")


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------


def _looks_like_a_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


def cook_command(args) -> int:
    from . import pipeline
    from .acquire import AcquisitionError
    from .extract import ExtractionError
    from .store import Library

    source_arg = args.source_arg
    try:
        if _looks_like_a_url(source_arg):
            outcome = pipeline.from_url(
                source_arg, _cli_progress,
                cookies_from_browser=args.cookies,
                asr_backend=args.asr, audio_language=spoken_language(args),
                llm_model=args.model,
                skip_audio=args.no_audio, ollama_url=args.ollama,
                **output_axes(args),
            )
        else:
            outcome = pipeline.from_file(
                source_arg, caption=args.caption or "",
                on_progress=_cli_progress,
                asr_backend=args.asr, audio_language=spoken_language(args),
                llm_model=args.model,
                skip_audio=args.no_audio, ollama_url=args.ollama,
                **output_axes(args),
            )
    except pipeline.NotARecipe as e:
        print(fail(f"\n✗ {e}"))
        return 2
    except (AcquisitionError, ExtractionError) as e:
        print(fail(f"\n✗ {e}"))
        return 1

    if not outcome.succeeded:
        print(fail(f"\n✗ {outcome.error}"))
        return 1

    for a in outcome.warnings:
        print(warn(f"  ⚠ {a}"))

    recipe = outcome.recipe
    print(ok(f"\n✓ {recipe.title}") + dim(f"  ({outcome.model})"))
    _print_recipe(recipe)

    if not args.no_save:
        with Library(args.db) as lib:
            identificativo = lib.save(recipe)
        print(dim(f"\n  Saved to the library with id {identificativo}."))

    if args.export:
        from .mela import write_melarecipe
        path = write_melarecipe(recipe, args.export)
        print(ok(f"  Exported: {path}"))

    return 0


# The headings of the printed card. They follow the **recipe's** language, not the interface's:
# what is printed here is the recipe itself, and an Italian card under an English heading is
# the same seam the translation pass exists to remove. The CLI has no interface language of
# its own — its `--help` and its messages are English — so this is the one catalogue here that
# has to be bilingual.
CARD: Catalogue = {
    "it": {"ingredients": "Ingredienti", "method": "Procedimento", "gaps": "Da controllare"},
    "en": {"ingredients": "Ingredients", "method": "Method", "gaps": "To check"},
}


def _print_recipe(recipe) -> None:
    from .units import UNCERTAIN_PROVENANCES

    def heading(key: str) -> str:
        return text_from(CARD, recipe.language, key)

    if recipe.servings or recipe.total_time_min():
        details = [d for d in (recipe.servings,
                                f"{recipe.total_time_min()} min" if recipe.total_time_min() else None) if d]
        print(dim("  " + " · ".join(details)))

    print("\n  " + _c(heading("ingredients"), "1"))
    for group in recipe.groups:
        if group and len([g for g in recipe.groups if g]) > 0 and len(recipe.groups) > 1:
            print(dim(f"    — {group} —"))
        for i in recipe.ingredients:
            if i.group == group:
                line = f"    {i.mela_line()}"
                print(warn(line) if i.quantity.provenance in UNCERTAIN_PROVENANCES else line)

    print("\n  " + _c(heading("method"), "1"))
    for n, step in enumerate(recipe.method, 1):
        print(f"    {n}. {step}")

    if recipe.gaps:
        print("\n  " + warn(heading("gaps")))
        for l in recipe.gaps:
            print(warn(f"    • {l}"))


def batch_command(args) -> int:
    from . import acquire, pipeline
    from .store import Library

    source_arg = Path(args.source_arg)
    jobs: list = []
    if source_arg.is_dir():
        media = acquire.from_folder(source_arg)
        jobs = [("media", m) for m in media]
    elif source_arg.suffix == ".txt":
        jobs = [("url", u) for u in acquire.read_url_list(source_arg)]
    else:
        print(fail("Batch needs a folder of files, or a .txt of URLs (one per line)."))
        return 1

    print(f"Queued: {len(jobs)} item(s).\n")
    riuscite, recipes = 0, []
    with Library(args.db) as lib:
        for index, (kind, item) in enumerate(jobs, 1):
            label = item if kind == "url" else item.label()
            print(_c(f"[{index}/{len(jobs)}] {label}", "1"))
            try:
                if kind == "url":
                    outcome = pipeline.from_url(item, _cli_progress,
                                            asr_backend=args.asr, audio_language=spoken_language(args),
                                            ollama_url=args.ollama,
                                            **output_axes(args))
                else:
                    outcome = pipeline.process(item, _cli_progress,
                                            asr_backend=args.asr, audio_language=spoken_language(args),
                                            ollama_url=args.ollama,
                                            **output_axes(args))
            except pipeline.NotARecipe as e:
                print(warn(f"  ⚠ skipped: {e}\n"))
                continue
            except Exception as e:
                print(fail(f"  ✗ {type(e).__name__}: {e}\n"))
                continue

            if outcome.succeeded:
                lib.save(outcome.recipe)
                recipes.append(outcome.recipe)
                riuscite += 1
                print(ok(f"  ✓ {outcome.recipe.title}\n"))

    print(f"\nDone: {ok(str(riuscite))} succeeded out of {len(jobs)}.")
    if recipes and args.export:
        from .mela import write_melarecipes
        path = write_melarecipes(recipes, args.export)
        print(ok(f"Exported together to {path}"))
    return 0 if riuscite else 1


def list_command(args) -> int:
    from .store import Library

    with Library(args.db) as lib:
        entries = lib.list_(search=args.search)

    if not entries:
        print(dim("The library is empty." if not args.search
                     else f"No results for «{args.search}»."))
        return 0

    for v in entries:
        mark = warn(" (to review)") if v["has_uncertainties"] else ""
        details = " · ".join(str(x) for x in (v["author"], v["servings"],
                              f"{v['total_time_min']} min" if v["total_time_min"] else None) if x)
        print(f"{_c(str(v['id']).rjust(4), '1')}  {v['title']}{mark}")
        if details:
            print(dim(f"      {details}"))
    print(dim(f"\n{len(entries)} recipe{'' if len(entries) == 1 else 's'}."))
    return 0


def delete_command(args) -> int:
    """Removes a recipe from the book. It asks for confirmation showing the title, because
    the operation cannot be undone and a wrong id gives no signal at all."""
    from .store import Library

    with Library(args.db) as lib:
        recipe = lib.read(args.id)
        if not recipe:
            print(fail(f"No recipe with id {args.id}."))
            return 1

        if not args.yes:
            # Affirmative answers stay accepted in both languages: anyone who has used this
            # command for months types "s" without thinking, and an "s" not recognised here
            # does not cancel a mistake — it cancels a deletion they meant.
            answer = input(f"Delete «{recipe.title}»? This cannot be undone. [y/N] ").strip().lower()
            if answer not in ("y", "yes", "s", "si", "sì"):
                print(dim("Cancelled."))
                return 0

        lib.delete(args.id)
    print(ok(f"✓ «{recipe.title}» deleted from the library."))
    return 0


# Both spellings are accepted, for the same reason `--sistema` still is: a script written
# before the rename keeps running. English first, because argparse prints `choices` in order
# and the first one reads as the answer.
#
# The alternative was to refuse `metrico` outright. It would fail loudly — argparse exits 2 —
# so it is not the silent kind of breakage, but it would break the one user this library
# belongs to for nothing. `output_axes` normalises whichever arrives, so nothing downstream
# ever sees the Italian value.
SYSTEM_CHOICES = [s.value for s in System] + list(LEGACY_SYSTEMS)


def output_axes(args) -> dict:
    """The language and system to pass to the pipeline.

    The system, when not asked for, follows the language: someone producing in English
    usually wants cups and ounces, someone producing in Italian wants grams. They stay
    independent, though — an Australian writes `--language en --system metric` and gets
    English with grams, which is the combination they would really use.
    """
    language = getattr(args, "language", "it")
    system = getattr(args, "system", None)
    if system is None:
        system = System.IMPERIAL.value if language == "en" else System.METRIC.value
    # `--system metrico` is still accepted, like every other Italian spelling on this command
    # line, and is normalised here rather than at the twenty places downstream that compare
    # against `System.METRIC`. Accepting a value and then never matching it would be worse
    # than refusing it.
    return {"language": language, "system": LEGACY_SYSTEMS.get(system, system)}


def spoken_language(args) -> str | None:
    """The language to declare to Whisper, or `None` to let it recognise the language itself.

    **It is not an output axis and it does not follow `--lingua`.** It is the language
    *spoken in the reel*, which is a fact about the input: an English reel can perfectly well
    produce an Italian recipe, and that is in fact the commonest case. Deducing it from the
    requested output language would mean telling Whisper something false every time we
    translate.
    """
    choice = getattr(args, "spoken_language", "auto")
    return None if choice == "auto" else choice


def export_command(args) -> int:
    from . import paths
    from .documents import DocumentError, write_markdown, write_pdf
    from .mela import write_melarecipe, write_melarecipes
    from .store import Library

    # Without --out the destination is `paths.py`'s decision, as it is for everything else:
    # the default used to be a fourth hard-wired copy of that fact, and a RELATIVE one at that
    # — inside the container it would have written next to the code instead of on the
    # persistent volume.
    destination = Path(args.out) if args.out else paths.export_folder()
    formats = list(dict.fromkeys(args.format))   # no duplicates, in the order given

    def write_one(recipe, fmt: str) -> Path:
        if fmt == "markdown":
            return write_markdown(recipe, destination)
        if fmt == "pdf":
            return write_pdf(recipe, destination)
        return write_melarecipe(recipe, destination)

    with Library(args.db) as lib:
        if args.all:
            recipes = lib.all_recipes()
            if not recipes:
                print(dim("The library is empty: nothing to export."))
                return 0
            for fmt in formats:
                try:
                    if fmt == "mela":
                        # Only Mela has a format for several recipes at once: a zip that imports
                        # in one go. Markdown and PDF are one file per recipe.
                        path = write_melarecipes(recipes, destination / "library")
                        print(ok(f"✓ {len(recipes)} recipes in {path}"))
                    else:
                        for recipe in recipes:
                            write_one(recipe, fmt)
                        print(ok(f"✓ {len(recipes)} recipes as {fmt} in {destination}"))
                except DocumentError as e:
                    print(fail(str(e)))
                    return 1
        else:
            recipe = lib.read(args.id)
            if not recipe:
                print(fail(f"No recipe with id {args.id}."))
                return 1
            for fmt in formats:
                try:
                    print(ok(f"✓ {write_one(recipe, fmt)}"))
                except DocumentError as e:
                    print(fail(str(e)))
                    return 1
    return 0


def serve_command(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print(fail("The web interface needs the «api» dependencies. Install them with:"))
        print("  uv sync --extra api")
        return 1
    from .api import create_app

    print(ok(f"\n  Reel2Recipe — interface on http://{args.host}:{args.port}\n"))
    print(dim("  Ctrl+C to stop.\n"))
    uvicorn.run(create_app(db=args.db, ollama_url=args.ollama),
                host=args.host, port=args.port, log_level="warning")
    return 0


def check_command(args) -> int:
    from . import pipeline

    print(_c("Reel2Recipe components\n", "1"))
    state = pipeline.check_environment(args.ollama)

    def line(label: str, pronto: bool, dettaglio: str = "") -> None:
        segno = ok("✓") if pronto else fail("✗")
        print(f"  {segno} {label}" + (dim(f"  {dettaglio}") if dettaglio else ""))

    line("ffmpeg (audio extraction)", state["ffmpeg"],
         "" if state["ffmpeg"] else "missing → brew install ffmpeg")
    line("yt-dlp (reel download)", state["yt_dlp"],
         "" if state["yt_dlp"] else "missing → uv sync")
    line("Local transcription (Whisper)", state["asr_ready"],
         ", ".join(state["asr_backend"]) if state["asr_backend"]
         else "missing → uv sync --extra asr")
    line("Ollama (local LLM)", state["ollama_up"],
         "" if state["ollama_up"] else "down → ollama serve")
    line("LLM models", bool(state["llm_models"]),
         ", ".join(state["llm_models"]) if state["llm_models"]
         else f"none → ollama pull {state['modello_consigliato']}")

    print()
    if state["ready"]:
        print(ok("  Everything is ready to extract recipes.") if state["asr_ready"]
              else warn("  Ready for captions; for speech install Whisper (uv sync --extra asr)."))
        return 0
    print(fail("  Something essential is missing. Run ./install.sh to sort it out."))
    return 1


# --------------------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    """The program's public surface, in English.

    Every name carries its old Italian name as an **alias**, and that is not a courtesy:
    `--porta` appears in the line with which the Home Assistant add-on starts the server, and
    that line lives in another repository. It has already killed the add-on once (argparse
    exits with code 2, s6 restarts for ever, the Ingress answers 502 without naming the
    cause). An alias costs one string and makes the rename impossible to get wrong; removing
    it can be done later, deliberately and across both repos.
    """
    p = argparse.ArgumentParser(
        prog="r2r",
        description="Reel2Recipe — extracts recipes from reels and takes them to Mela. All local.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"Reel2Recipe {__version__}")
    p.add_argument("--db", default=None,
                   help="path to the database (default: workspace/ricette.db)")
    p.add_argument("--ollama", default="http://localhost:11434", help="URL of the Ollama server")

    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("cook", help="extract a recipe from a reel (url or file)")
    c.add_argument("source_arg", metavar="SOURCE",
                   help="URL of the reel, or path to a video/audio file")
    c.add_argument("--caption", "--didascalia", dest="caption",
                   help="text of the post, for local files without metadata")
    c.add_argument("--asr", default="auto", choices=["auto", "mlx", "faster-whisper"],
                   help="transcription backend")
    c.add_argument("--spoken-language", "--lingua-parlato", dest="spoken_language",
                   default="auto", choices=["auto", "it", "en"],
                   help="language spoken in the reel (default: auto, Whisper detects it)")
    c.add_argument("--model", "--modello", dest="model",
                   help="Ollama model to use (default: the best one installed)")
    c.add_argument("--cookies", metavar="BROWSER",
                   help="use the browser's cookies (chrome/safari/firefox) for private reels")
    c.add_argument("--no-audio", action="store_true",
                   help="skip transcription, use the caption only")
    c.add_argument("--language", "--lingua", dest="language",
                   default="it", choices=["it", "en"],
                   help="language of the recipe produced (default: it)")
    c.add_argument("--system", "--sistema", dest="system",
                   default=None, choices=SYSTEM_CHOICES,
                   help="measurement system (default: metric with --language it, imperial with en)")
    c.add_argument("--no-save", "--no-salva", dest="no_save", action="store_true",
                   help="do not save to the library")
    c.add_argument("--export", metavar="FOLDER",
                   help="export the .melarecipe to this folder straight away")
    c.set_defaults(func=cook_command)

    b = sub.add_parser("batch", help="process many reels in a row")
    b.add_argument("source_arg", metavar="SOURCE",
                   help="folder of files, or a .txt with one URL per line")
    b.add_argument("--asr", default="auto", choices=["auto", "mlx", "faster-whisper"])
    b.add_argument("--spoken-language", "--lingua-parlato", dest="spoken_language",
                   default="auto", choices=["auto", "it", "en"])
    b.add_argument("--language", "--lingua", dest="language",
                   default="it", choices=["it", "en"])
    b.add_argument("--system", "--sistema", dest="system",
                   default=None, choices=SYSTEM_CHOICES)
    b.add_argument("--export", metavar="PATH", help="export everything to a single .melarecipes")
    b.set_defaults(func=batch_command)

    l = sub.add_parser("list", help="list or search the library")
    l.add_argument("--search", "--cerca", dest="search",
                   help="search across titles, ingredients and methods")
    l.set_defaults(func=list_command)

    e = sub.add_parser("export", help="export in Mela format")
    e.add_argument("id", nargs="?", type=int, help="id of the recipe to export")
    e.add_argument("--all", "--tutte", dest="all", action="store_true",
                   help="export the whole library as one .melarecipes")
    e.add_argument("--out", default=None,
                   help="destination folder (default: the workspace export folder)")
    e.add_argument("--format", "--formato", dest="format", nargs="+",
                   choices=("mela", "markdown", "pdf"),
                   default=["mela"], metavar="FORMAT",
                   help="mela (default), markdown, pdf — more than one can be asked for")
    e.set_defaults(func=export_command)

    d = sub.add_parser("delete", aliases=["elimina"], help="delete a recipe from the library")
    d.add_argument("id", type=int, help="id of the recipe to delete")
    d.add_argument("--yes", "--si", dest="yes", action="store_true", help="do not ask for confirmation")
    d.set_defaults(func=delete_command)

    s = sub.add_parser("serve", help="start the web interface")
    s.add_argument("--host", default="127.0.0.1")
    # 8500 and not 8000: uvicorn's default port is almost always already taken by
    # something else on a development machine.
    s.add_argument("--port", "--porta", dest="port", type=int, default=8500)
    s.set_defaults(func=serve_command)

    k = sub.add_parser("check", help="verify that the components are ready")
    k.set_defaults(func=check_command)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if getattr(args, "command", None) == "export" and not args.all and args.id is None:
        print(fail("Give the recipe id, or use --all."))
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print(dim("\nInterrupted."))
        return 130


if __name__ == "__main__":
    sys.exit(main())
