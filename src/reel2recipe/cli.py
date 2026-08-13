"""cli.py — Reel2Recipe da riga di comando.

    r2r cook <url|file>       estrae una ricetta e la salva in libreria
    r2r batch <cartella|.txt> lavora molti reel in serie
    r2r list [--cerca ...]    elenca / cerca nella libreria
    r2r export <id|--tutte>   esporta in .melarecipe / .melarecipes, markdown o pdf
    r2r elimina <id>          elimina una ricetta dal ricettario
    r2r serve                 avvia l'interfaccia web su http://localhost:8500
    r2r check                 verifica che tutti i componenti siano pronti

Tutto locale: nessuna chiave API, nessun servizio a pagamento.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__

# Codici colore ANSI, disattivati se l'output non è un terminale (pipe, file di log).
_TTY = sys.stdout.isatty()


def _c(testo: str, codice: str) -> str:
    return f"\033[{codice}m{testo}\033[0m" if _TTY else testo


def ok(t: str) -> str: return _c(t, "32")
def avviso(t: str) -> str: return _c(t, "33")
def errore(t: str) -> str: return _c(t, "31")
def spento(t: str) -> str: return _c(t, "2")


def _avanzamento_cli(fase: str, messaggio: str) -> None:
    print(f"  {spento('▸')} {messaggio}")


# --------------------------------------------------------------------------------------
# Comandi
# --------------------------------------------------------------------------------------


def _pare_un_url(testo: str) -> bool:
    return testo.startswith(("http://", "https://"))


def comando_cook(args) -> int:
    from . import pipeline
    from .acquire import AcquisitionError
    from .extract import ErroreEstrazione
    from .store import Library

    sorgente = args.sorgente
    try:
        if _pare_un_url(sorgente):
            esito = pipeline.da_url(
                sorgente, _avanzamento_cli,
                cookies_da_browser=args.cookies,
                backend_asr=args.asr, lingua_audio=lingua_del_parlato(args),
                modello_llm=args.model,
                salta_audio=args.no_audio, url_ollama=args.ollama,
                **assi_di_uscita(args),
            )
        else:
            esito = pipeline.da_file(
                sorgente, didascalia=args.caption or "",
                su_avanzamento=_avanzamento_cli,
                backend_asr=args.asr, lingua_audio=lingua_del_parlato(args),
                modello_llm=args.model,
                salta_audio=args.no_audio, url_ollama=args.ollama,
                **assi_di_uscita(args),
            )
    except pipeline.NonEUnaRicetta as e:
        print(errore(f"\n✗ {e}"))
        return 2
    except (AcquisitionError, ErroreEstrazione) as e:
        print(errore(f"\n✗ {e}"))
        return 1

    if not esito.riuscito:
        print(errore(f"\n✗ {esito.errore}"))
        return 1

    for a in esito.avvertenze:
        print(avviso(f"  ⚠ {a}"))

    ricetta = esito.ricetta
    print(ok(f"\n✓ {ricetta.title}") + spento(f"  ({esito.modello})"))
    _stampa_ricetta(ricetta)

    if not args.no_save:
        with Library(args.db) as lib:
            identificativo = lib.save(ricetta)
        print(spento(f"\n  Saved to the library with id {identificativo}."))

    if args.export:
        from .mela import write_melarecipe
        percorso = write_melarecipe(ricetta, args.export)
        print(ok(f"  Exported: {percorso}"))

    return 0


def _stampa_ricetta(ricetta) -> None:
    from .units import UNCERTAIN_PROVENANCES

    if ricetta.servings or ricetta.total_time_min():
        dettagli = [d for d in (ricetta.servings,
                                f"{ricetta.total_time_min()} min" if ricetta.total_time_min() else None) if d]
        print(spento("  " + " · ".join(dettagli)))

    print("\n  " + _c("Ingredients", "1"))
    for gruppo in ricetta.groups:
        if gruppo and len([g for g in ricetta.groups if g]) > 0 and len(ricetta.groups) > 1:
            print(spento(f"    — {gruppo} —"))
        for i in ricetta.ingredients:
            if i.group == gruppo:
                riga = f"    {i.mela_line()}"
                print(avviso(riga) if i.quantity.provenance in UNCERTAIN_PROVENANCES else riga)

    print("\n  " + _c("Method", "1"))
    for n, passo in enumerate(ricetta.method, 1):
        print(f"    {n}. {passo}")

    if ricetta.gaps:
        print("\n  " + avviso("To check"))
        for l in ricetta.gaps:
            print(avviso(f"    • {l}"))


def comando_batch(args) -> int:
    from . import acquire, pipeline
    from .store import Library

    sorgente = Path(args.sorgente)
    lavori: list = []
    if sorgente.is_dir():
        media = acquire.from_folder(sorgente)
        lavori = [("media", m) for m in media]
    elif sorgente.suffix == ".txt":
        lavori = [("url", u) for u in acquire.read_url_list(sorgente)]
    else:
        print(errore("Batch needs a folder of files, or a .txt of URLs (one per line)."))
        return 1

    print(f"Queued: {len(lavori)} item(s).\n")
    riuscite, ricette = 0, []
    with Library(args.db) as lib:
        for indice, (tipo, elemento) in enumerate(lavori, 1):
            etichetta = elemento if tipo == "url" else elemento.label()
            print(_c(f"[{indice}/{len(lavori)}] {etichetta}", "1"))
            try:
                if tipo == "url":
                    esito = pipeline.da_url(elemento, _avanzamento_cli,
                                            backend_asr=args.asr, lingua_audio=lingua_del_parlato(args),
                                            url_ollama=args.ollama,
                                            **assi_di_uscita(args))
                else:
                    esito = pipeline.lavora(elemento, _avanzamento_cli,
                                            backend_asr=args.asr, lingua_audio=lingua_del_parlato(args),
                                            url_ollama=args.ollama,
                                            **assi_di_uscita(args))
            except pipeline.NonEUnaRicetta as e:
                print(avviso(f"  ⚠ skipped: {e}\n"))
                continue
            except Exception as e:
                print(errore(f"  ✗ {type(e).__name__}: {e}\n"))
                continue

            if esito.riuscito:
                lib.save(esito.ricetta)
                ricette.append(esito.ricetta)
                riuscite += 1
                print(ok(f"  ✓ {esito.ricetta.title}\n"))

    print(f"\nDone: {ok(str(riuscite))} succeeded out of {len(lavori)}.")
    if ricette and args.export:
        from .mela import write_melarecipes
        percorso = write_melarecipes(ricette, args.export)
        print(ok(f"Exported together to {percorso}"))
    return 0 if riuscite else 1


def comando_list(args) -> int:
    from .store import Library

    with Library(args.db) as lib:
        voci = lib.list_(search=args.search)

    if not voci:
        print(spento("The library is empty." if not args.search
                     else f"No results for «{args.search}»."))
        return 0

    for v in voci:
        marchio = avviso(" (to review)") if v["has_uncertainties"] else ""
        dettagli = " · ".join(str(x) for x in (v["author"], v["servings"],
                              f"{v['total_time_min']} min" if v["total_time_min"] else None) if x)
        print(f"{_c(str(v['id']).rjust(4), '1')}  {v['title']}{marchio}")
        if dettagli:
            print(spento(f"      {dettagli}"))
    print(spento(f"\n{len(voci)} ricett{'a' if len(voci) == 1 else 'e'}."))
    return 0


def comando_elimina(args) -> int:
    """Toglie una ricetta dal ricettario. Chiede conferma mostrando il titolo, perché
    l'operazione non è reversibile e un id sbagliato non dà nessun segnale."""
    from .store import Library

    with Library(args.db) as lib:
        ricetta = lib.read(args.id)
        if not ricetta:
            print(errore(f"No recipe with id {args.id}."))
            return 1

        if not args.yes:
            # Le risposte affermative restano accettate in entrambe le lingue: chi ha usato
            # questo comando per mesi digita «s» senza pensarci, e un «s» non riconosciuto
            # qui non annulla un errore — annulla una cancellazione voluta.
            risposta = input(f"Delete «{ricetta.title}»? This cannot be undone. [y/N] ").strip().lower()
            if risposta not in ("y", "yes", "s", "si", "sì"):
                print(spento("Cancelled."))
                return 0

        lib.delete(args.id)
    print(ok(f"✓ «{ricetta.title}» deleted from the library."))
    return 0


def assi_di_uscita(args) -> dict:
    """Lingua e sistema da passare alla pipeline.

    Il sistema, se non chiesto, segue la lingua: chi produce in inglese di solito vuole
    cup e once, chi produce in italiano grammi. Restano però indipendenti — un australiano
    scrive `--lingua en --sistema metrico` e ottiene inglese con i grammi, che è la
    combinazione che userebbe davvero.
    """
    lingua = getattr(args, "language", "it")
    sistema = getattr(args, "system", None)
    if sistema is None:
        sistema = "imperiale" if lingua == "en" else "metrico"
    return {"lingua": lingua, "sistema": sistema}


def lingua_del_parlato(args) -> str | None:
    """La lingua da dichiarare a Whisper, oppure `None` per fargliela riconoscere.

    **Non è un asse di uscita e non segue `--lingua`.** È la lingua *parlata nel reel*,
    che è un fatto dell'ingresso: un reel inglese può benissimo produrre una ricetta
    italiana, ed è anzi il caso più comune. Dedurla dalla lingua richiesta in uscita
    significherebbe dire a Whisper una cosa falsa ogni volta che si traduce.
    """
    scelta = getattr(args, "spoken_language", "auto")
    return None if scelta == "auto" else scelta


def comando_export(args) -> int:
    from . import paths
    from .documents import DocumentError, write_markdown, write_pdf
    from .mela import write_melarecipe, write_melarecipes
    from .store import Library

    # Senza --out la destinazione la decide `paths.py`, come per tutto il resto: il
    # predefinito era una quarta copia cablata di quel fatto, per giunta RELATIVA — dentro
    # il container avrebbe scritto accanto al codice invece che sul volume persistente.
    destinazione = Path(args.out) if args.out else paths.export_folder()
    formati = list(dict.fromkeys(args.format))   # senza duplicati, nell'ordine dato

    def scrivi_una(ricetta, formato: str) -> Path:
        if formato == "markdown":
            return write_markdown(ricetta, destinazione)
        if formato == "pdf":
            return write_pdf(ricetta, destinazione)
        return write_melarecipe(ricetta, destinazione)

    with Library(args.db) as lib:
        if args.all:
            ricette = lib.all_recipes()
            if not ricette:
                print(spento("The library is empty: nothing to export."))
                return 0
            for formato in formati:
                try:
                    if formato == "mela":
                        # Solo Mela ha un formato per più ricette insieme: uno zip che si
                        # importa in un colpo. Markdown e PDF sono un file per ricetta.
                        percorso = write_melarecipes(ricette, destinazione / "libreria")
                        print(ok(f"✓ {len(ricette)} recipes in {percorso}"))
                    else:
                        for ricetta in ricette:
                            scrivi_una(ricetta, formato)
                        print(ok(f"✓ {len(ricette)} recipes as {formato} in {destinazione}"))
                except DocumentError as e:
                    print(errore(str(e)))
                    return 1
        else:
            ricetta = lib.read(args.id)
            if not ricetta:
                print(errore(f"No recipe with id {args.id}."))
                return 1
            for formato in formati:
                try:
                    print(ok(f"✓ {scrivi_una(ricetta, formato)}"))
                except DocumentError as e:
                    print(errore(str(e)))
                    return 1
    return 0


def comando_serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print(errore("The web interface needs the «api» dependencies. Install them with:"))
        print("  uv sync --extra api")
        return 1
    from .api import crea_app

    print(ok(f"\n  Reel2Recipe — interface on http://{args.host}:{args.port}\n"))
    print(spento("  Ctrl+C to stop.\n"))
    uvicorn.run(crea_app(db=args.db, url_ollama=args.ollama),
                host=args.host, port=args.port, log_level="warning")
    return 0


def comando_check(args) -> int:
    from . import pipeline

    print(_c("Reel2Recipe components\n", "1"))
    stato = pipeline.controlla_ambiente(args.ollama)

    def riga(etichetta: str, pronto: bool, dettaglio: str = "") -> None:
        segno = ok("✓") if pronto else errore("✗")
        print(f"  {segno} {etichetta}" + (spento(f"  {dettaglio}") if dettaglio else ""))

    riga("ffmpeg (audio extraction)", stato["ffmpeg"],
         "" if stato["ffmpeg"] else "missing → brew install ffmpeg")
    riga("yt-dlp (reel download)", stato["yt_dlp"],
         "" if stato["yt_dlp"] else "missing → uv sync")
    riga("Local transcription (Whisper)", stato["asr_pronto"],
         ", ".join(stato["asr_backend"]) if stato["asr_backend"]
         else "missing → uv sync --extra asr")
    riga("Ollama (local LLM)", stato["ollama_attivo"],
         "" if stato["ollama_attivo"] else "down → ollama serve")
    riga("LLM models", bool(stato["modelli_llm"]),
         ", ".join(stato["modelli_llm"]) if stato["modelli_llm"]
         else f"none → ollama pull {stato['modello_consigliato']}")

    print()
    if stato["pronto"]:
        print(ok("  Everything is ready to extract recipes.") if stato["asr_pronto"]
              else avviso("  Ready for captions; for speech install Whisper (uv sync --extra asr)."))
        return 0
    print(errore("  Something essential is missing. Run ./install.sh to sort it out."))
    return 1


# --------------------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    """La superficie pubblica del programma, in inglese.

    Ogni nome porta con sé il suo vecchio nome italiano come **alias**, e non è una
    cortesia: `--porta` compare nella riga con cui l'add-on Home Assistant avvia il
    server, che vive in un altro repository. Quella riga ha già ucciso l'add-on una volta
    (argparse esce con codice 2, s6 riavvia all'infinito, l'Ingress risponde 502 senza
    nominare la causa). Un alias costa una stringa e rende la rinomina impossibile da
    sbagliare; toglierlo si può fare più avanti, deliberatamente e su entrambi i repo.
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

    sub = p.add_subparsers(dest="comando", required=True)

    c = sub.add_parser("cook", help="extract a recipe from a reel (url or file)")
    c.add_argument("sorgente", metavar="SOURCE",
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
                   default=None, choices=["metrico", "imperiale"],
                   help="measurement system (default: metric with --language it, imperial with en)")
    c.add_argument("--no-save", "--no-salva", dest="no_save", action="store_true",
                   help="do not save to the library")
    c.add_argument("--export", metavar="FOLDER",
                   help="export the .melarecipe to this folder straight away")
    c.set_defaults(func=comando_cook)

    b = sub.add_parser("batch", help="process many reels in a row")
    b.add_argument("sorgente", metavar="SOURCE",
                   help="folder of files, or a .txt with one URL per line")
    b.add_argument("--asr", default="auto", choices=["auto", "mlx", "faster-whisper"])
    b.add_argument("--spoken-language", "--lingua-parlato", dest="spoken_language",
                   default="auto", choices=["auto", "it", "en"])
    b.add_argument("--language", "--lingua", dest="language",
                   default="it", choices=["it", "en"])
    b.add_argument("--system", "--sistema", dest="system",
                   default=None, choices=["metrico", "imperiale"])
    b.add_argument("--export", metavar="PATH", help="export everything to a single .melarecipes")
    b.set_defaults(func=comando_batch)

    l = sub.add_parser("list", help="list or search the library")
    l.add_argument("--search", "--cerca", dest="search",
                   help="search across titles, ingredients and methods")
    l.set_defaults(func=comando_list)

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
    e.set_defaults(func=comando_export)

    d = sub.add_parser("delete", aliases=["elimina"], help="delete a recipe from the library")
    d.add_argument("id", type=int, help="id of the recipe to delete")
    d.add_argument("--yes", "--si", dest="yes", action="store_true", help="do not ask for confirmation")
    d.set_defaults(func=comando_elimina)

    s = sub.add_parser("serve", help="start the web interface")
    s.add_argument("--host", default="127.0.0.1")
    # 8500 e non 8000: la porta predefinita di uvicorn è quasi sempre già occupata da
    # qualcos'altro sulla macchina di sviluppo.
    s.add_argument("--port", "--porta", dest="port", type=int, default=8500)
    s.set_defaults(func=comando_serve)

    k = sub.add_parser("check", help="verify that the components are ready")
    k.set_defaults(func=comando_check)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if getattr(args, "comando", None) == "export" and not args.all and args.id is None:
        print(errore("Give the recipe id, or use --all."))
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print(spento("\nInterrupted."))
        return 130


if __name__ == "__main__":
    sys.exit(main())
