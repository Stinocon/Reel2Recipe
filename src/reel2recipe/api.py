"""api.py — l'interfaccia web locale. FastAPI su http://localhost:8500.

È la "barra Cook": si incolla un link, si preme, e la pipeline fa il resto. La stessa
app serve anche il frontend statico in `web/`, così non serve un secondo server né una
toolchain di build.

L'estrazione è lunga (scaricamento + trascrizione + LLM possono richiedere minuti), quindi
non blocca la richiesta HTTP: parte in un thread e l'avanzamento viene trasmesso via
Server-Sent Events. La pagina mostra le fasi in tempo reale invece di una rotellina muta.

Tutto resta locale: nessun dato lascia la macchina, l'app ascolta di default solo su
127.0.0.1.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import pipeline
from .documenti import ErroreDocumento, scrivi_markdown, scrivi_pdf
from .mela import scrivi_melarecipe, scrivi_melarecipes, verso_melarecipe
from .percorsi import RADICE_REPO, cartella_export
from .recipe import Ricetta
from .store import Libreria

CARTELLA_WEB = RADICE_REPO / "web"


# --------------------------------------------------------------------------------------
# Lavori in corso: un piccolo registro in memoria con code di avanzamento
# --------------------------------------------------------------------------------------


@dataclass
class Lavoro:
    id: str
    eventi: asyncio.Queue = field(default_factory=asyncio.Queue)
    finito: bool = False
    esito: dict | None = None


class RegistroLavori:
    """Tiene traccia delle estrazioni in corso e inoltra il loro avanzamento alla pagina.

    In-process e volatile di proposito: è un'app locale monoutente, non serve una coda
    persistente. Se il processo si ferma i lavori in corso si perdono, e va bene così.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._lavori: dict[str, Lavoro] = {}

    def nuovo(self) -> Lavoro:
        lavoro = Lavoro(id=uuid.uuid4().hex[:12])
        self._lavori[lavoro.id] = lavoro
        return lavoro

    def get(self, id: str) -> Lavoro | None:
        return self._lavori.get(id)

    def emetti(self, lavoro: Lavoro, tipo: str, dati: dict) -> None:
        """Chiamabile da un thread di lavoro: inoltra un evento nella coda asyncio in modo thread-safe."""
        self._loop.call_soon_threadsafe(lavoro.eventi.put_nowait, {"tipo": tipo, **dati})

    def concludi(self, lavoro: Lavoro, esito: dict) -> None:
        lavoro.esito = esito
        lavoro.finito = True
        self.emetti(lavoro, "fine", esito)


# --------------------------------------------------------------------------------------
# Modelli di richiesta
# --------------------------------------------------------------------------------------


class RichiestaCook(BaseModel):
    url: str | None = None
    didascalia: str | None = None
    backend_asr: str = "auto"
    modello_llm: str | None = None
    salta_audio: bool = False
    cookies_da_browser: str | None = None
    # I due assi di uscita. Se il sistema non è chiesto segue la lingua, ma resta
    # sovrascrivibile: inglese con i grammi è una combinazione reale.
    lingua: str = "it"
    sistema: str | None = None

    def assi(self) -> dict:
        return {"lingua": self.lingua,
                "sistema": self.sistema or ("imperiale" if self.lingua == "en" else "metrico")}


# --------------------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------------------


def crea_app(db: str | None = None, url_ollama: str = "http://localhost:11434") -> FastAPI:
    app = FastAPI(title="Reel2Recipe", version="0.1.0")
    registro: RegistroLavori | None = None

    def libreria() -> Libreria:
        return Libreria(db)

    @app.on_event("startup")
    async def _avvio():
        nonlocal registro
        registro = RegistroLavori(asyncio.get_running_loop())

    # ---- diagnostica -----------------------------------------------------------------

    @app.get("/api/stato")
    def stato() -> dict:
        """Cosa è pronto e cosa manca. La pagina lo usa per avvisare prima di iniziare."""
        return pipeline.controlla_ambiente(url_ollama)

    # ---- estrazione ------------------------------------------------------------------

    @app.post("/api/cook")
    async def cook(richiesta: RichiestaCook) -> dict:
        """Avvia un'estrazione da URL. Ritorna subito un id da seguire via SSE."""
        if not richiesta.url or not richiesta.url.strip():
            raise HTTPException(422, "Serve l'URL di un reel.")
        lavoro = registro.nuovo()
        threading.Thread(
            target=_esegui_da_url, args=(registro, lavoro, richiesta, url_ollama, db), daemon=True
        ).start()
        return {"job": lavoro.id}

    @app.post("/api/cook-file")
    async def cook_file(file: UploadFile, didascalia: str = "",
                        lingua: str = "it", sistema: str | None = None) -> dict:
        """Come sopra, ma da un file caricato dalla pagina (trascina-e-rilascia)."""
        suffisso = Path(file.filename or "reel.mp4").suffix or ".mp4"
        temporaneo = Path(tempfile.gettempdir()) / f"r2r-{uuid.uuid4().hex[:8]}{suffisso}"
        temporaneo.write_bytes(await file.read())

        lavoro = registro.nuovo()
        threading.Thread(
            target=_esegui_da_file,
            args=(registro, lavoro, temporaneo, didascalia, url_ollama, db,
                  RichiestaCook(lingua=lingua, sistema=sistema).assi()),
            daemon=True,
        ).start()
        return {"job": lavoro.id}

    @app.get("/api/cook/{job}/eventi")
    async def eventi(job: str) -> StreamingResponse:
        """Flusso SSE con l'avanzamento di un lavoro."""
        lavoro = registro.get(job)
        if not lavoro:
            raise HTTPException(404, "Lavoro sconosciuto.")

        async def genera():
            while True:
                evento = await lavoro.eventi.get()
                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
                if evento["tipo"] == "fine":
                    break

        return StreamingResponse(genera(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- libreria --------------------------------------------------------------------

    @app.get("/api/ricette")
    def elenca(cerca: str | None = None) -> list[dict]:
        with libreria() as lib:
            return lib.elenca(cerca=cerca)

    @app.get("/api/ricette/{id}")
    def leggi(id: int) -> dict:
        with libreria() as lib:
            ricetta = lib.leggi(id)
        if not ricetta:
            raise HTTPException(404, "Ricetta non trovata.")
        d = ricetta.to_dict()
        d["id"] = id
        return d

    @app.put("/api/ricette/{id}")
    def modifica(id: int, ricetta: dict) -> dict:
        """Salva le correzioni manuali dell'utente. È il passaggio che rende affidabile
        l'export: l'LLM propone, l'utente corregge, e solo poi si esporta."""
        with libreria() as lib:
            if not lib.leggi(id):
                raise HTTPException(404, "Ricetta non trovata.")
            ricetta.pop("id", None)
            lib.aggiorna(id, Ricetta.from_dict(ricetta))
        return {"ok": True}

    @app.delete("/api/ricette/{id}")
    def elimina(id: int) -> dict:
        with libreria() as lib:
            if not lib.elimina(id):
                raise HTTPException(404, "Ricetta non trovata.")
        return {"ok": True}

    @app.post("/api/ricette")
    def salva_nuova(ricetta: dict) -> dict:
        """Salva in libreria una ricetta appena estratta (con eventuali correzioni)."""
        with libreria() as lib:
            id = lib.salva(Ricetta.from_dict(ricetta))
        return {"id": id}

    # ---- export ----------------------------------------------------------------------

    @app.get("/api/ricette/{id}/export")
    def export_singolo(id: int, formato: str = "mela") -> FileResponse:
        """Scarica una ricetta. `formato` è `mela` (predefinito), `markdown` o `pdf`.

        Il predefinito resta Mela perché è il formato che l'app importa; gli altri due
        servono a chi Mela non ce l'ha e vuole comunque tenersi la ricetta.
        """
        with libreria() as lib:
            ricetta = lib.leggi(id)
        if not ricetta:
            raise HTTPException(404, "Ricetta non trovata.")

        try:
            if formato == "markdown":
                percorso, tipo = scrivi_markdown(ricetta, cartella_export()), "text/markdown"
            elif formato == "pdf":
                percorso, tipo = scrivi_pdf(ricetta, cartella_export()), "application/pdf"
            elif formato == "mela":
                percorso, tipo = scrivi_melarecipe(ricetta, cartella_export()), "application/json"
            else:
                raise HTTPException(400, f"Formato «{formato}» sconosciuto: usa mela, markdown o pdf.")
        except ErroreDocumento as e:
            # Manca l'extra `doc`: è un problema di installazione, non della richiesta.
            raise HTTPException(503, str(e)) from e

        return FileResponse(percorso, media_type=tipo, filename=percorso.name)

    @app.get("/api/export")
    def export_tutte() -> FileResponse:
        with libreria() as lib:
            ricette = lib.tutte()
        if not ricette:
            raise HTTPException(404, "Libreria vuota.")
        percorso = scrivi_melarecipes(ricette, cartella_export() / "libreria")
        return FileResponse(percorso, media_type="application/zip", filename=percorso.name)

    @app.post("/api/preview-mela")
    def anteprima_mela(ricetta: dict) -> dict:
        """L'aspetto che avrà la ricetta in Mela, senza scriverla su disco."""
        return verso_melarecipe(Ricetta.from_dict(ricetta))

    # ---- frontend statico ------------------------------------------------------------

    if CARTELLA_WEB.is_dir():
        app.mount("/", StaticFiles(directory=CARTELLA_WEB, html=True), name="web")
    else:  # pragma: no cover - solo se qualcuno cancella web/
        @app.get("/")
        def _senza_frontend():
            return JSONResponse({"errore": "Cartella web/ mancante."}, status_code=500)

    return app


# --------------------------------------------------------------------------------------
# Esecuzione nei thread di lavoro
# --------------------------------------------------------------------------------------


def _avanzamento(registro: RegistroLavori, lavoro: Lavoro):
    def emetti(fase: str, messaggio: str) -> None:
        registro.emetti(lavoro, "avanzamento", {"fase": fase, "messaggio": messaggio})
    return emetti


def _concludi_con_esito(registro: RegistroLavori, lavoro: Lavoro, esito: pipeline.Esito,
                        db: str | None) -> None:
    if not esito.riuscito:
        registro.concludi(lavoro, {"ok": False, "errore": esito.errore, "avvertenze": esito.avvertenze})
        return
    with Libreria(db) as lib:
        identificativo = lib.salva(esito.ricetta)
    dati = esito.ricetta.to_dict()
    dati["id"] = identificativo
    registro.concludi(lavoro, {
        "ok": True,
        "ricetta": dati,
        "modello": esito.modello,
        "avvertenze": esito.avvertenze,
    })


def _esegui_da_url(registro: RegistroLavori, lavoro: Lavoro, richiesta: RichiestaCook,
                   url_ollama: str, db: str | None) -> None:
    try:
        esito = pipeline.da_url(
            richiesta.url, _avanzamento(registro, lavoro),
            cookies_da_browser=richiesta.cookies_da_browser,
            backend_asr=richiesta.backend_asr, modello_llm=richiesta.modello_llm,
            salta_audio=richiesta.salta_audio, url_ollama=url_ollama,
            **richiesta.assi(),
        )
        _concludi_con_esito(registro, lavoro, esito, db)
    except pipeline.NonEUnaRicetta as e:
        registro.concludi(lavoro, {"ok": False, "errore": str(e), "non_ricetta": True})
    except Exception as e:
        registro.concludi(lavoro, {"ok": False, "errore": f"{type(e).__name__}: {e}"})


def _esegui_da_file(registro: RegistroLavori, lavoro: Lavoro, percorso: Path,
                    didascalia: str, url_ollama: str, db: str | None,
                    assi: dict | None = None) -> None:
    try:
        esito = pipeline.da_file(
            percorso, didascalia=didascalia,
            su_avanzamento=_avanzamento(registro, lavoro), url_ollama=url_ollama,
            **(assi or {}),
        )
        _concludi_con_esito(registro, lavoro, esito, db)
    except pipeline.NonEUnaRicetta as e:
        registro.concludi(lavoro, {"ok": False, "errore": str(e), "non_ricetta": True})
    except Exception as e:
        registro.concludi(lavoro, {"ok": False, "errore": f"{type(e).__name__}: {e}"})
    finally:
        percorso.unlink(missing_ok=True)   # il caricamento temporaneo non deve restare in giro
