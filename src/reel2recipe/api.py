"""api.py — the local web interface. FastAPI on http://localhost:8500.

It is the "Cook bar": you paste a link, you press, and the pipeline does the rest. The same
app also serves the static frontend in `web/`, so neither a second server nor a build
toolchain is needed.

Extraction is slow (download + transcription + LLM can take minutes), so it does not block the
HTTP request: it starts in a thread and the progress is streamed over Server-Sent Events. The
page shows the stages in real time instead of a mute spinner.

Everything stays local: no data leaves the machine, and by default the app listens on
127.0.0.1 only.

**The URL paths and query parameters are English too, since the last pass** — `/api/status`,
`/api/recipes`, `/api/cook/{job}/events`, `?format=`, `?ui_language=`. They used to be
Italian, kept that way on the argument that a URL is external surface and external surface
gets a synonym rather than a rename. That argument was worth less than it looked: the only
client is `web/app.js`, which ships in the same commit, and this is a single-user app on
localhost — the bookmark it was protecting does not exist. A second set of aliased routes
would have doubled the surface to protect nothing, which AGENTS.md §10 argues against.

The one thing that trap left behind is worth keeping in mind whenever a query parameter is
renamed here: **in FastAPI the parameter's Python name _is_ the query name**. Renaming
`formato` to `format_` once made all three export formats silently return a `.melarecipe` —
no error, a wrong file, visible only on opening it. Where the two have to differ, say so with
an explicit `Query(alias=...)` rather than relying on the spelling, as `export_one` does.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import pipeline
from .documents import DocumentError, write_markdown, write_pdf
from .mela import write_melarecipe, write_melarecipes, to_melarecipe
from .paths import REPO_ROOT, export_folder
from .recipe import Recipe
from .store import Library
from .units import Catalogue, System, text_from

WEB_FOLDER = REPO_ROOT / "web"


# The errors the interface shows the user.
#
# These follow the language **of the interface**, not of the recipe, which is why the parameter
# is called `ui_language`: `/api/cook` already has a `language` meaning something else entirely —
# the language to produce the recipe in. Two different names because they are two different
# things, and calling them the same would have cost a silent defect the moment the two values
# diverged.
#
# `"Libreria vuota."` was `"Library vuota."` until this pass: an earlier commit's
# `Libreria → Library` rename had walked into an Italian string, and the test asserted the
# broken text, so it protected the defect instead of catching it.
TEXTS: Catalogue = {
    "it": {
        "url_required": "Serve l'URL di un reel.",
        "unknown_job": "Lavoro sconosciuto.",
        "recipe_not_found": "Ricetta non trovata.",
        "unknown_format": "Formato «{format}» sconosciuto: usa mela, markdown o pdf.",
        "empty_library": "Libreria vuota.",
    },
    "en": {
        "url_required": "The URL of a reel is required.",
        "unknown_job": "Unknown job.",
        "recipe_not_found": "Recipe not found.",
        "unknown_format": "Unknown format «{format}»: use mela, markdown or pdf.",
        "empty_library": "The library is empty.",
    },
}


def text(language: str, key: str, **data) -> str:
    """An API error in the language of the interface."""
    return text_from(TEXTS, language, key, **data)


# --------------------------------------------------------------------------------------
# Jobs under way: a small in-memory registry with progress queues
# --------------------------------------------------------------------------------------


@dataclass
class Job:
    id: str
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    finished: bool = False
    outcome: dict | None = None


class JobRegistry:
    """Keeps track of the extractions under way and forwards their progress to the page.

    In-process and volatile on purpose: this is a local, single-user app, and a persistent
    queue is not needed. If the process stops, the jobs under way are lost, and that is fine.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._jobs: dict[str, Job] = {}

    def new(self) -> Job:
        job = Job(id=uuid.uuid4().hex[:12])
        self._jobs[job.id] = job
        return job

    def get(self, id: str) -> Job | None:
        return self._jobs.get(id)

    def emit(self, job: Job, kind: str, data: dict) -> None:
        """Callable from a worker thread: forwards an event into the asyncio queue safely."""
        self._loop.call_soon_threadsafe(job.events.put_nowait, {"kind": kind, **data})

    def finish(self, job: Job, outcome: dict) -> None:
        job.outcome = outcome
        job.finished = True
        self.emit(job, "end", outcome)


# --------------------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------------------


class CookRequest(BaseModel):
    """The body of `/api/cook` and the query of `/api/cook-file`.

    These field names are the **HTTP contract** with `web/app.js`, nothing more: no file on
    disk is keyed this way. They moved to English in the same commit as the frontend that
    sends them — the same rule already applied to `Library.list_`'s keys and to the pipeline's
    stage names.

    Worth knowing, because it bit during the migration: pydantic ignores unknown keyword
    arguments by default. A field renamed on one side and not the other does not raise — the
    value is silently dropped and the default takes over, which is exactly the defect
    `/api/cook-file` had once already, in another form.
    """

    url: str | None = None
    caption: str | None = None
    asr_backend: str = "auto"
    llm_model: str | None = None
    skip_audio: bool = False
    cookies_from_browser: str | None = None
    # The language SPOKEN in the reel, which concerns the input and not the output. `None`
    # means "let Whisper recognise it", and it is the default: deducing it from the requested
    # output language would mean declaring a false language every time we translate.
    audio_language: str | None = None
    # The two output axes. They are independent: the system does not follow the language, it
    # defaults to metric and is chosen. See `cli.output_axes` for why that default moved —
    # briefly, imperial cooking measures are one country's, and most people who read recipes
    # in English cook in grams.
    language: str = "it"
    system: str | None = None

    def axes(self) -> dict:
        return {"language": self.language, "system": self.system or System.METRIC.value}


# --------------------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------------------


def create_app(db: str | None = None, ollama_url: str = "http://localhost:11434") -> FastAPI:
    app = FastAPI(title="Reel2Recipe", version="0.1.0")
    registry: JobRegistry | None = None

    def library() -> Library:
        return Library(db)

    @app.on_event("startup")
    async def _startup():
        nonlocal registry
        registry = JobRegistry(asyncio.get_running_loop())

    # ---- diagnostics -----------------------------------------------------------------

    @app.get("/api/status")
    def status() -> dict:
        """What is ready and what is missing. The page uses it to warn before starting."""
        return pipeline.check_environment(ollama_url)

    # ---- extraction ------------------------------------------------------------------

    @app.post("/api/cook")
    async def cook(request: CookRequest) -> dict:
        """Starts an extraction from a URL. Returns an id to follow over SSE straight away."""
        if not request.url or not request.url.strip():
            # The interface's language does not reach this far: the only reference is the
            # recipe's, which in normal use coincides because it follows it.
            raise HTTPException(422, text(request.language, "url_required"))
        job = registry.new()
        threading.Thread(
            target=_run_from_url, args=(registry, job, request, ollama_url, db), daemon=True
        ).start()
        return {"job": job.id}

    @app.post("/api/cook-file")
    async def cook_file(file: UploadFile, caption: str = "",
                        asr_backend: str = "auto", llm_model: str | None = None,
                        skip_audio: bool = False, audio_language: str | None = None,
                        language: str = "it", system: str | None = None) -> dict:
        """As above, but from a file uploaded by the page (drag and drop).

        The options arrive as query parameters and not in the body, because the body is
        already the file's multipart. They are **the same** as `/api/cook`'s: an uploaded file
        is not a second-class citizen. It used to be — the ASR backend, the model and
        `skip_audio` were not even accepted, so anyone dragging a video always got the default
        settings with nothing saying so.
        """
        suffix = Path(file.filename or "reel.mp4").suffix or ".mp4"
        temporary = Path(tempfile.gettempdir()) / f"r2r-{uuid.uuid4().hex[:8]}{suffix}"
        temporary.write_bytes(await file.read())

        request = CookRequest(
            caption=caption, asr_backend=asr_backend, llm_model=llm_model,
            skip_audio=skip_audio, audio_language=audio_language,
            language=language, system=system,
        )
        job = registry.new()
        threading.Thread(
            target=_run_from_file,
            args=(registry, job, temporary, request, ollama_url, db),
            daemon=True,
        ).start()
        return {"job": job.id}

    @app.get("/api/cook/{job}/events")
    async def events(job: str, ui_language: str = "it") -> StreamingResponse:
        """SSE stream with a job's progress."""
        job = registry.get(job)
        if not job:
            raise HTTPException(404, text(ui_language, "unknown_job"))

        async def generate():
            while True:
                event = await job.events.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["kind"] == "end":
                    break

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- library ---------------------------------------------------------------------

    @app.get("/api/recipes")
    def list_recipes(search: str | None = None) -> list[dict]:
        with library() as lib:
            return lib.list_(search=search)

    @app.get("/api/recipes/{id}")
    def read_recipe(id: int, ui_language: str = "it") -> dict:
        with library() as lib:
            recipe = lib.read(id)
        if not recipe:
            raise HTTPException(404, text(ui_language, "recipe_not_found"))
        d = recipe.to_dict()
        d["id"] = id
        return d

    @app.put("/api/recipes/{id}")
    def update_recipe(id: int, recipe: dict, ui_language: str = "it") -> dict:
        """Saves the user's manual corrections. It is the step that makes the export
        trustworthy: the LLM proposes, the user corrects, and only then does it export."""
        with library() as lib:
            if not lib.read(id):
                raise HTTPException(404, text(ui_language, "recipe_not_found"))
            recipe.pop("id", None)
            lib.update(id, Recipe.from_dict(recipe))
        return {"ok": True}

    @app.delete("/api/recipes/{id}")
    def delete_recipe(id: int, ui_language: str = "it") -> dict:
        with library() as lib:
            if not lib.delete(id):
                raise HTTPException(404, text(ui_language, "recipe_not_found"))
        return {"ok": True}

    @app.post("/api/recipes")
    def save_new(recipe: dict) -> dict:
        """Saves a freshly extracted recipe (with any corrections) into the library."""
        with library() as lib:
            id = lib.save(Recipe.from_dict(recipe))
        return {"id": id}

    # ---- export ----------------------------------------------------------------------

    @app.get("/api/recipes/{id}/export")
    def export_one(id: int, fmt: str = Query("mela", alias="format"),
                   ui_language: str = "it") -> FileResponse:
        """Downloads a recipe. `?format=` is `mela` (the default), `markdown` or `pdf`.

        The alias is not decoration. In FastAPI the query name *is* the parameter name, and
        `format` alone would shadow the builtin inside this function, so the two have to
        differ — which is exactly the situation that once made every format silently return a
        `.melarecipe`. Stating the query name explicitly is what stops the next rename from
        moving it by accident; `tests/test_api.py` covers all three formats.

        The default stays Mela because that is the format the app imports; the other two are
        for anyone who does not have Mela and wants to keep the recipe anyway.
        """
        with library() as lib:
            recipe = lib.read(id)
        if not recipe:
            raise HTTPException(404, text(ui_language, "recipe_not_found"))

        try:
            if fmt == "markdown":
                path, media_type = write_markdown(recipe, export_folder()), "text/markdown"
            elif fmt == "pdf":
                path, media_type = write_pdf(recipe, export_folder()), "application/pdf"
            elif fmt == "mela":
                path, media_type = write_melarecipe(recipe, export_folder()), "application/json"
            else:
                raise HTTPException(400, text(ui_language, "unknown_format", format=fmt))
        except DocumentError as e:
            # The `doc` extra is missing: an installation problem, not a problem with the request.
            raise HTTPException(503, str(e)) from e

        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.get("/api/export")
    def export_all(ui_language: str = "it") -> FileResponse:
        with library() as lib:
            recipes = lib.all_recipes()
        if not recipes:
            raise HTTPException(404, text(ui_language, "empty_library"))
        path = write_melarecipes(recipes, export_folder() / "library")
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.post("/api/preview-mela")
    def mela_preview(recipe: dict) -> dict:
        """What the recipe will look like in Mela, without writing it to disk."""
        return to_melarecipe(Recipe.from_dict(recipe))

    # ---- static frontend -------------------------------------------------------------

    if WEB_FOLDER.is_dir():
        app.mount("/", StaticFiles(directory=WEB_FOLDER, html=True), name="web")
    else:  # pragma: no cover - only if someone deletes web/
        @app.get("/")
        def _no_frontend():
            return JSONResponse({"error": "The web/ folder is missing."}, status_code=500)

    return app


# --------------------------------------------------------------------------------------
# Execution in the job threads
# --------------------------------------------------------------------------------------


def _progress(registry: JobRegistry, job: Job):
    def emit(stage: str, message: str) -> None:
        registry.emit(job, "progress", {"stage": stage, "message": message})
    return emit


def _finish_with_outcome(registry: JobRegistry, job: Job, outcome: pipeline.Outcome,
                        db: str | None) -> None:
    if not outcome.succeeded:
        registry.finish(job, {"ok": False, "error": outcome.error, "warnings": outcome.warnings})
        return
    with Library(db) as lib:
        identifier = lib.save(outcome.recipe)
    data = outcome.recipe.to_dict()
    data["id"] = identifier
    registry.finish(job, {
        "ok": True,
        "recipe": data,
        "model": outcome.model,
        "warnings": outcome.warnings,
    })


def _run_from_url(registry: JobRegistry, job: Job, request: CookRequest,
                   ollama_url: str, db: str | None) -> None:
    try:
        outcome = pipeline.from_url(
            request.url, _progress(registry, job),
            cookies_from_browser=request.cookies_from_browser,
            asr_backend=request.asr_backend, audio_language=request.audio_language,
            llm_model=request.llm_model,
            skip_audio=request.skip_audio, ollama_url=ollama_url,
            **request.axes(),
        )
        _finish_with_outcome(registry, job, outcome, db)
    except pipeline.NotARecipe as e:
        registry.finish(job, {"ok": False, "error": str(e), "not_a_recipe": True})
    except Exception as e:
        registry.finish(job, {"ok": False, "error": f"{type(e).__name__}: {e}"})


def _run_from_file(registry: JobRegistry, job: Job, path: Path,
                    request: CookRequest, ollama_url: str, db: str | None) -> None:
    try:
        outcome = pipeline.from_file(
            path, caption=request.caption or "",
            on_progress=_progress(registry, job), ollama_url=ollama_url,
            asr_backend=request.asr_backend, audio_language=request.audio_language,
            llm_model=request.llm_model,
            skip_audio=request.skip_audio,
            **request.axes(),
        )
        _finish_with_outcome(registry, job, outcome, db)
    except pipeline.NotARecipe as e:
        registry.finish(job, {"ok": False, "error": str(e), "not_a_recipe": True})
    except Exception as e:
        registry.finish(job, {"ok": False, "error": f"{type(e).__name__}: {e}"})
    finally:
        path.unlink(missing_ok=True)   # the temporary upload must not linger
