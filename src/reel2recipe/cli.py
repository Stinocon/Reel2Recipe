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
    from .acquire import ErroreAcquisizione
    from .extract import ErroreEstrazione
    from .store import Libreria

    sorgente = args.sorgente
    try:
        if _pare_un_url(sorgente):
            esito = pipeline.da_url(
                sorgente, _avanzamento_cli,
                cookies_da_browser=args.cookies,
                backend_asr=args.asr, modello_llm=args.modello,
                salta_audio=args.no_audio, url_ollama=args.ollama,
                **assi_di_uscita(args),
            )
        else:
            esito = pipeline.da_file(
                sorgente, didascalia=args.didascalia or "",
                su_avanzamento=_avanzamento_cli,
                backend_asr=args.asr, modello_llm=args.modello,
                salta_audio=args.no_audio, url_ollama=args.ollama,
                **assi_di_uscita(args),
            )
    except pipeline.NonEUnaRicetta as e:
        print(errore(f"\n✗ {e}"))
        return 2
    except (ErroreAcquisizione, ErroreEstrazione) as e:
        print(errore(f"\n✗ {e}"))
        return 1

    if not esito.riuscito:
        print(errore(f"\n✗ {esito.errore}"))
        return 1

    for a in esito.avvertenze:
        print(avviso(f"  ⚠ {a}"))

    ricetta = esito.ricetta
    print(ok(f"\n✓ {ricetta.titolo}") + spento(f"  ({esito.modello})"))
    _stampa_ricetta(ricetta)

    if not args.no_salva:
        with Libreria(args.db) as lib:
            identificativo = lib.salva(ricetta)
        print(spento(f"\n  Salvata in libreria con id {identificativo}."))

    if args.export:
        from .mela import scrivi_melarecipe
        percorso = scrivi_melarecipe(ricetta, args.export)
        print(ok(f"  Esportata: {percorso}"))

    return 0


def _stampa_ricetta(ricetta) -> None:
    from .units import PROVENIENZE_INCERTE

    if ricetta.porzioni or ricetta.tempo_totale_min():
        dettagli = [d for d in (ricetta.porzioni,
                                f"{ricetta.tempo_totale_min()} min" if ricetta.tempo_totale_min() else None) if d]
        print(spento("  " + " · ".join(dettagli)))

    print("\n  " + _c("Ingredienti", "1"))
    for gruppo in ricetta.gruppi:
        if gruppo and len([g for g in ricetta.gruppi if g]) > 0 and len(ricetta.gruppi) > 1:
            print(spento(f"    — {gruppo} —"))
        for i in ricetta.ingredienti:
            if i.gruppo == gruppo:
                riga = f"    {i.riga_mela()}"
                print(avviso(riga) if i.quantita.provenienza in PROVENIENZE_INCERTE else riga)

    print("\n  " + _c("Procedimento", "1"))
    for n, passo in enumerate(ricetta.procedimento, 1):
        print(f"    {n}. {passo}")

    if ricetta.lacune:
        print("\n  " + avviso("Da verificare"))
        for l in ricetta.lacune:
            print(avviso(f"    • {l}"))


def comando_batch(args) -> int:
    from . import acquire, pipeline
    from .store import Libreria

    sorgente = Path(args.sorgente)
    lavori: list = []
    if sorgente.is_dir():
        media = acquire.da_cartella(sorgente)
        lavori = [("media", m) for m in media]
    elif sorgente.suffix == ".txt":
        lavori = [("url", u) for u in acquire.leggi_elenco_url(sorgente)]
    else:
        print(errore("Per il batch serve una cartella di file o un .txt di URL (uno per riga)."))
        return 1

    print(f"In coda: {len(lavori)} elemento/i.\n")
    riuscite, ricette = 0, []
    with Libreria(args.db) as lib:
        for indice, (tipo, elemento) in enumerate(lavori, 1):
            etichetta = elemento if tipo == "url" else elemento.etichetta()
            print(_c(f"[{indice}/{len(lavori)}] {etichetta}", "1"))
            try:
                if tipo == "url":
                    esito = pipeline.da_url(elemento, _avanzamento_cli,
                                            backend_asr=args.asr, url_ollama=args.ollama,
                                            **assi_di_uscita(args))
                else:
                    esito = pipeline.lavora(elemento, _avanzamento_cli,
                                            backend_asr=args.asr, url_ollama=args.ollama,
                                            **assi_di_uscita(args))
            except pipeline.NonEUnaRicetta as e:
                print(avviso(f"  ⚠ saltato: {e}\n"))
                continue
            except Exception as e:
                print(errore(f"  ✗ {type(e).__name__}: {e}\n"))
                continue

            if esito.riuscito:
                lib.salva(esito.ricetta)
                ricette.append(esito.ricetta)
                riuscite += 1
                print(ok(f"  ✓ {esito.ricetta.titolo}\n"))

    print(f"\nFatto: {ok(str(riuscite))} riuscite su {len(lavori)}.")
    if ricette and args.export:
        from .mela import scrivi_melarecipes
        percorso = scrivi_melarecipes(ricette, args.export)
        print(ok(f"Esportate insieme in {percorso}"))
    return 0 if riuscite else 1


def comando_list(args) -> int:
    from .store import Libreria

    with Libreria(args.db) as lib:
        voci = lib.elenca(cerca=args.cerca)

    if not voci:
        print(spento("Libreria vuota." if not args.cerca else f"Nessun risultato per «{args.cerca}»."))
        return 0

    for v in voci:
        marchio = avviso(" (da rivedere)") if v["ha_incertezze"] else ""
        dettagli = " · ".join(str(x) for x in (v["autore"], v["porzioni"],
                              f"{v['tempo_totale_min']} min" if v["tempo_totale_min"] else None) if x)
        print(f"{_c(str(v['id']).rjust(4), '1')}  {v['titolo']}{marchio}")
        if dettagli:
            print(spento(f"      {dettagli}"))
    print(spento(f"\n{len(voci)} ricett{'a' if len(voci) == 1 else 'e'}."))
    return 0


def comando_elimina(args) -> int:
    """Toglie una ricetta dal ricettario. Chiede conferma mostrando il titolo, perché
    l'operazione non è reversibile e un id sbagliato non dà nessun segnale."""
    from .store import Libreria

    with Libreria(args.db) as lib:
        ricetta = lib.leggi(args.id)
        if not ricetta:
            print(errore(f"Nessuna ricetta con id {args.id}."))
            return 1

        if not args.si:
            risposta = input(f"Eliminare «{ricetta.titolo}»? Non è reversibile. [s/N] ").strip().lower()
            if risposta not in ("s", "si", "sì", "y", "yes"):
                print(spento("Annullato."))
                return 0

        lib.elimina(args.id)
    print(ok(f"✓ «{ricetta.titolo}» eliminata dal ricettario."))
    return 0


def assi_di_uscita(args) -> dict:
    """Lingua e sistema da passare alla pipeline.

    Il sistema, se non chiesto, segue la lingua: chi produce in inglese di solito vuole
    cup e once, chi produce in italiano grammi. Restano però indipendenti — un australiano
    scrive `--lingua en --sistema metrico` e ottiene inglese con i grammi, che è la
    combinazione che userebbe davvero.
    """
    lingua = getattr(args, "lingua", "it")
    sistema = getattr(args, "sistema", None)
    if sistema is None:
        sistema = "imperiale" if lingua == "en" else "metrico"
    return {"lingua": lingua, "sistema": sistema}


def comando_export(args) -> int:
    from . import percorsi
    from .documenti import ErroreDocumento, scrivi_markdown, scrivi_pdf
    from .mela import scrivi_melarecipe, scrivi_melarecipes
    from .store import Libreria

    # Senza --out la destinazione la decide `percorsi.py`, come per tutto il resto: il
    # predefinito era una quarta copia cablata di quel fatto, per giunta RELATIVA — dentro
    # il container avrebbe scritto accanto al codice invece che sul volume persistente.
    destinazione = Path(args.out) if args.out else percorsi.cartella_export()
    formati = list(dict.fromkeys(args.formato))   # senza duplicati, nell'ordine dato

    def scrivi_una(ricetta, formato: str) -> Path:
        if formato == "markdown":
            return scrivi_markdown(ricetta, destinazione)
        if formato == "pdf":
            return scrivi_pdf(ricetta, destinazione)
        return scrivi_melarecipe(ricetta, destinazione)

    with Libreria(args.db) as lib:
        if args.tutte:
            ricette = lib.tutte()
            if not ricette:
                print(spento("Libreria vuota: niente da esportare."))
                return 0
            for formato in formati:
                try:
                    if formato == "mela":
                        # Solo Mela ha un formato per più ricette insieme: uno zip che si
                        # importa in un colpo. Markdown e PDF sono un file per ricetta.
                        percorso = scrivi_melarecipes(ricette, destinazione / "libreria")
                        print(ok(f"✓ {len(ricette)} ricette in {percorso}"))
                    else:
                        for ricetta in ricette:
                            scrivi_una(ricetta, formato)
                        print(ok(f"✓ {len(ricette)} ricette in {formato} dentro {destinazione}"))
                except ErroreDocumento as e:
                    print(errore(str(e)))
                    return 1
        else:
            ricetta = lib.leggi(args.id)
            if not ricetta:
                print(errore(f"Nessuna ricetta con id {args.id}."))
                return 1
            for formato in formati:
                try:
                    print(ok(f"✓ {scrivi_una(ricetta, formato)}"))
                except ErroreDocumento as e:
                    print(errore(str(e)))
                    return 1
    return 0


def comando_serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print(errore("L'interfaccia web richiede le dipendenze «api». Installa con:"))
        print("  uv sync --extra api")
        return 1
    from .api import crea_app

    print(ok(f"\n  Reel2Recipe — interfaccia su http://{args.host}:{args.porta}\n"))
    print(spento("  Ctrl+C per fermare.\n"))
    uvicorn.run(crea_app(db=args.db, url_ollama=args.ollama),
                host=args.host, port=args.porta, log_level="warning")
    return 0


def comando_check(args) -> int:
    from . import pipeline

    print(_c("Componenti di Reel2Recipe\n", "1"))
    stato = pipeline.controlla_ambiente(args.ollama)

    def riga(etichetta: str, pronto: bool, dettaglio: str = "") -> None:
        segno = ok("✓") if pronto else errore("✗")
        print(f"  {segno} {etichetta}" + (spento(f"  {dettaglio}") if dettaglio else ""))

    riga("ffmpeg (estrazione audio)", stato["ffmpeg"],
         "" if stato["ffmpeg"] else "manca → brew install ffmpeg")
    riga("yt-dlp (scaricamento reel)", stato["yt_dlp"],
         "" if stato["yt_dlp"] else "manca → uv sync")
    riga("Trascrizione locale (Whisper)", stato["asr_pronto"],
         ", ".join(stato["asr_backend"]) if stato["asr_backend"]
         else "manca → uv sync --extra asr")
    riga("Ollama (LLM locale)", stato["ollama_attivo"],
         "" if stato["ollama_attivo"] else "spento → ollama serve")
    riga("Modelli LLM", bool(stato["modelli_llm"]),
         ", ".join(stato["modelli_llm"]) if stato["modelli_llm"]
         else f"nessuno → ollama pull {stato['modello_consigliato']}")

    print()
    if stato["pronto"]:
        print(ok("  Tutto pronto per estrarre ricette.") if stato["asr_pronto"]
              else avviso("  Pronto per le didascalie; per il parlato installa Whisper (uv sync --extra asr)."))
        return 0
    print(errore("  Manca qualcosa di essenziale. Esegui ./install.sh per sistemare tutto."))
    return 1


# --------------------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="r2r",
        description="Reel2Recipe — estrae ricette dai reel e le porta in Mela. Tutto in locale.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"Reel2Recipe {__version__}")
    p.add_argument("--db", default=None, help="percorso del database (default: workspace/ricette.db)")
    p.add_argument("--ollama", default="http://localhost:11434", help="URL del server Ollama")

    sub = p.add_subparsers(dest="comando", required=True)

    c = sub.add_parser("cook", help="estrae una ricetta da un reel (url o file)")
    c.add_argument("sorgente", help="URL del reel oppure percorso di un file video/audio")
    c.add_argument("--didascalia", help="testo del post, per i file locali senza metadati")
    c.add_argument("--asr", default="auto", choices=["auto", "mlx", "faster-whisper"],
                   help="backend di trascrizione")
    c.add_argument("--modello", help="modello Ollama da usare (default: il migliore installato)")
    c.add_argument("--cookies", metavar="BROWSER",
                   help="usa i cookie del browser (chrome/safari/firefox) per i reel privati")
    c.add_argument("--no-audio", action="store_true", help="salta la trascrizione, usa solo la didascalia")
    c.add_argument("--lingua", default="it", choices=["it", "en"],
                   help="lingua della ricetta prodotta (default: it)")
    c.add_argument("--sistema", default=None, choices=["metrico", "imperiale"],
                   help="sistema di misura (default: metrico con --lingua it, imperiale con en)")
    c.add_argument("--no-salva", action="store_true", help="non salvare in libreria")
    c.add_argument("--export", metavar="CARTELLA", help="esporta subito il .melarecipe in questa cartella")
    c.set_defaults(func=comando_cook)

    b = sub.add_parser("batch", help="lavora molti reel in serie")
    b.add_argument("sorgente", help="cartella di file oppure .txt con un URL per riga")
    b.add_argument("--asr", default="auto", choices=["auto", "mlx", "faster-whisper"])
    b.add_argument("--lingua", default="it", choices=["it", "en"])
    b.add_argument("--sistema", default=None, choices=["metrico", "imperiale"])
    b.add_argument("--export", metavar="PERCORSO", help="esporta tutto in un unico .melarecipes")
    b.set_defaults(func=comando_batch)

    l = sub.add_parser("list", help="elenca o cerca nella libreria")
    l.add_argument("--cerca", help="cerca fra titoli, ingredienti e procedimenti")
    l.set_defaults(func=comando_list)

    e = sub.add_parser("export", help="esporta in formato Mela")
    e.add_argument("id", nargs="?", type=int, help="id della ricetta da esportare")
    e.add_argument("--tutte", action="store_true", help="esporta l'intera libreria in un .melarecipes")
    e.add_argument("--out", default=None,
                   help="cartella di destinazione (default: la cartella export del workspace)")
    e.add_argument("--formato", nargs="+", choices=("mela", "markdown", "pdf"),
                   default=["mela"], metavar="FORMATO",
                   help="mela (predefinito), markdown, pdf — se ne possono chiedere più d'uno")
    e.set_defaults(func=comando_export)

    d = sub.add_parser("elimina", help="elimina una ricetta dal ricettario")
    d.add_argument("id", type=int, help="id della ricetta da eliminare")
    d.add_argument("--si", action="store_true", help="non chiedere conferma")
    d.set_defaults(func=comando_elimina)

    s = sub.add_parser("serve", help="avvia l'interfaccia web")
    s.add_argument("--host", default="127.0.0.1")
    # 8500 e non 8000: la porta di default di uvicorn è quasi sempre già occupata da
    # qualcos'altro sulla macchina di sviluppo.
    s.add_argument("--porta", type=int, default=8500)
    s.set_defaults(func=comando_serve)

    k = sub.add_parser("check", help="verifica che i componenti siano pronti")
    k.set_defaults(func=comando_check)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if getattr(args, "comando", None) == "export" and not args.tutte and args.id is None:
        print(errore("Indica l'id della ricetta, oppure usa --tutte."))
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print(spento("\nInterrotto."))
        return 130


if __name__ == "__main__":
    sys.exit(main())
