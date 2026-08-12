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
from .paths import REPO_ROOT, export_folder
from .recipe import Ricetta
from .store import Libreria
from .units import Catalogo, testo_da

CARTELLA_WEB = REPO_ROOT / "web"


# Gli errori che l'interfaccia mostra all'utente.
#
# Seguono la lingua **dell'interfaccia**, non quella della ricetta, e per questo il
# parametro si chiama `lingua_ui`: su `/api/cook` esiste gia' un `lingua` e vuol dire
# tutt'altro — la lingua in cui produrre la ricetta. Due nomi diversi perche' sono due
# cose diverse, e chiamarle uguale sarebbe costato un difetto silenzioso appena i due
# valori divergono.
TESTI: Catalogo = {
    "it": {
        "serve_url": "Serve l'URL di un reel.",
        "lavoro_sconosciuto": "Lavoro sconosciuto.",
        "ricetta_non_trovata": "Ricetta non trovata.",
        "formato_sconosciuto": "Formato «{formato}» sconosciuto: usa mela, markdown o pdf.",
        "libreria_vuota": "Libreria vuota.",
    },
    "en": {
        "serve_url": "The URL of a reel is required.",
        "lavoro_sconosciuto": "Unknown job.",
        "ricetta_non_trovata": "Recipe not found.",
        "formato_sconosciuto": "Unknown format «{formato}»: use mela, markdown or pdf.",
        "libreria_vuota": "The library is empty.",
    },
}


def testo(lingua: str, chiave: str, **dati) -> str:
    """Un errore dell'API nella lingua dell'interfaccia."""
    return testo_da(TESTI, lingua, chiave, **dati)


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
    # La lingua PARLATA nel reel, che riguarda l'ingresso e non l'uscita. `None` significa
    # «la riconosce Whisper», ed è il predefinito: dedurla dalla lingua richiesta in uscita
    # significherebbe dichiarare una lingua falsa ogni volta che si traduce.
    lingua_audio: str | None = None
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
            # Qui la lingua dell'interfaccia non arriva: l'unico riferimento e' quello
            # della ricetta, che nell'uso normale coincide perche' la segue.
            raise HTTPException(422, testo(richiesta.lingua, "serve_url"))
        lavoro = registro.nuovo()
        threading.Thread(
            target=_esegui_da_url, args=(registro, lavoro, richiesta, url_ollama, db), daemon=True
        ).start()
        return {"job": lavoro.id}

    @app.post("/api/cook-file")
    async def cook_file(file: UploadFile, didascalia: str = "",
                        backend_asr: str = "auto", modello_llm: str | None = None,
                        salta_audio: bool = False, lingua_audio: str | None = None,
                        lingua: str = "it", sistema: str | None = None) -> dict:
        """Come sopra, ma da un file caricato dalla pagina (trascina-e-rilascia).

        Le opzioni arrivano come parametri di query e non nel corpo, perché il corpo è già
        il multipart del file. Sono **le stesse** di `/api/cook`: un file caricato non è un
        cittadino di seconda classe. Prima lo era — backend ASR, modello e `salta_audio`
        non erano nemmeno accettati, quindi chi trascinava un video otteneva sempre le
        impostazioni predefinite senza che niente lo dicesse.
        """
        suffisso = Path(file.filename or "reel.mp4").suffix or ".mp4"
        temporaneo = Path(tempfile.gettempdir()) / f"r2r-{uuid.uuid4().hex[:8]}{suffisso}"
        temporaneo.write_bytes(await file.read())

        richiesta = RichiestaCook(
            didascalia=didascalia, backend_asr=backend_asr, modello_llm=modello_llm,
            salta_audio=salta_audio, lingua_audio=lingua_audio,
            lingua=lingua, sistema=sistema,
        )
        lavoro = registro.nuovo()
        threading.Thread(
            target=_esegui_da_file,
            args=(registro, lavoro, temporaneo, richiesta, url_ollama, db),
            daemon=True,
        ).start()
        return {"job": lavoro.id}

    @app.get("/api/cook/{job}/eventi")
    async def eventi(job: str, lingua_ui: str = "it") -> StreamingResponse:
        """Flusso SSE con l'avanzamento di un lavoro."""
        lavoro = registro.get(job)
        if not lavoro:
            raise HTTPException(404, testo(lingua_ui, "lavoro_sconosciuto"))

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
    def leggi(id: int, lingua_ui: str = "it") -> dict:
        with libreria() as lib:
            ricetta = lib.leggi(id)
        if not ricetta:
            raise HTTPException(404, testo(lingua_ui, "ricetta_non_trovata"))
        d = ricetta.to_dict()
        d["id"] = id
        return d

    @app.put("/api/ricette/{id}")
    def modifica(id: int, ricetta: dict, lingua_ui: str = "it") -> dict:
        """Salva le correzioni manuali dell'utente. È il passaggio che rende affidabile
        l'export: l'LLM propone, l'utente corregge, e solo poi si esporta."""
        with libreria() as lib:
            if not lib.leggi(id):
                raise HTTPException(404, testo(lingua_ui, "ricetta_non_trovata"))
            ricetta.pop("id", None)
            lib.aggiorna(id, Ricetta.from_dict(ricetta))
        return {"ok": True}

    @app.delete("/api/ricette/{id}")
    def elimina(id: int, lingua_ui: str = "it") -> dict:
        with libreria() as lib:
            if not lib.elimina(id):
                raise HTTPException(404, testo(lingua_ui, "ricetta_non_trovata"))
        return {"ok": True}

    @app.post("/api/ricette")
    def salva_nuova(ricetta: dict) -> dict:
        """Salva in libreria una ricetta appena estratta (con eventuali correzioni)."""
        with libreria() as lib:
            id = lib.salva(Ricetta.from_dict(ricetta))
        return {"id": id}

    # ---- export ----------------------------------------------------------------------

    @app.get("/api/ricette/{id}/export")
    def export_singolo(id: int, formato: str = "mela", lingua_ui: str = "it") -> FileResponse:
        """Scarica una ricetta. `formato` è `mela` (predefinito), `markdown` o `pdf`.

        Il predefinito resta Mela perché è il formato che l'app importa; gli altri due
        servono a chi Mela non ce l'ha e vuole comunque tenersi la ricetta.
        """
        with libreria() as lib:
            ricetta = lib.leggi(id)
        if not ricetta:
            raise HTTPException(404, testo(lingua_ui, "ricetta_non_trovata"))

        try:
            if formato == "markdown":
                percorso, tipo = scrivi_markdown(ricetta, export_folder()), "text/markdown"
            elif formato == "pdf":
                percorso, tipo = scrivi_pdf(ricetta, export_folder()), "application/pdf"
            elif formato == "mela":
                percorso, tipo = scrivi_melarecipe(ricetta, export_folder()), "application/json"
            else:
                raise HTTPException(400, testo(lingua_ui, "formato_sconosciuto", formato=formato))
        except ErroreDocumento as e:
            # Manca l'extra `doc`: è un problema di installazione, non della richiesta.
            raise HTTPException(503, str(e)) from e

        return FileResponse(percorso, media_type=tipo, filename=percorso.name)

    @app.get("/api/export")
    def export_tutte(lingua_ui: str = "it") -> FileResponse:
        with libreria() as lib:
            ricette = lib.tutte()
        if not ricette:
            raise HTTPException(404, testo(lingua_ui, "libreria_vuota"))
        percorso = scrivi_melarecipes(ricette, export_folder() / "libreria")
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
            backend_asr=richiesta.backend_asr, lingua_audio=richiesta.lingua_audio,
            modello_llm=richiesta.modello_llm,
            salta_audio=richiesta.salta_audio, url_ollama=url_ollama,
            **richiesta.assi(),
        )
        _concludi_con_esito(registro, lavoro, esito, db)
    except pipeline.NonEUnaRicetta as e:
        registro.concludi(lavoro, {"ok": False, "errore": str(e), "non_ricetta": True})
    except Exception as e:
        registro.concludi(lavoro, {"ok": False, "errore": f"{type(e).__name__}: {e}"})


def _esegui_da_file(registro: RegistroLavori, lavoro: Lavoro, percorso: Path,
                    richiesta: RichiestaCook, url_ollama: str, db: str | None) -> None:
    try:
        esito = pipeline.da_file(
            percorso, didascalia=richiesta.didascalia or "",
            su_avanzamento=_avanzamento(registro, lavoro), url_ollama=url_ollama,
            backend_asr=richiesta.backend_asr, lingua_audio=richiesta.lingua_audio,
            modello_llm=richiesta.modello_llm,
            salta_audio=richiesta.salta_audio,
            **richiesta.assi(),
        )
        _concludi_con_esito(registro, lavoro, esito, db)
    except pipeline.NonEUnaRicetta as e:
        registro.concludi(lavoro, {"ok": False, "errore": str(e), "non_ricetta": True})
    except Exception as e:
        registro.concludi(lavoro, {"ok": False, "errore": f"{type(e).__name__}: {e}"})
    finally:
        percorso.unlink(missing_ok=True)   # il caricamento temporaneo non deve restare in giro
