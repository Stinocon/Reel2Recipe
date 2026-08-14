"""test_api.py — that the user's choices really reach the pipeline.

These tests do not prove the extraction (that needs Ollama, and `test_modello.py` is there for
it): they prove the **wiring**. The options panel drew a language choice that nobody read, so
every job came out in Italian metric whatever was chosen. No test covered that stretch because
`tests/` had no API test at all: the defect had no way of showing itself.

The pipeline is replaced by a spy that records the arguments it receives and declares a failed
outcome. Failed on purpose: that way `_finish_with_outcome` returns immediately and does not
touch the library, and the test stays on the wiring without dragging a database along.
"""

from __future__ import annotations

import threading

import pytest

from reel2recipe import api, pipeline

TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def spy(monkeypatch):
    """Replaces `pipeline.from_url` and `pipeline.from_file` with a spy on the arguments.

    The job runs in a thread, so the HTTP call returns before the spy has been invoked: the
    event is what makes it possible to wait for it without an arbitrary pause.
    """
    received: dict = {}
    called = threading.Event()

    def fake(*args, **kwargs):
        received.update(kwargs)
        received["positional"] = args
        called.set()
        return pipeline.Outcome(error="spy: no real processing")

    monkeypatch.setattr(pipeline, "from_url", fake)
    monkeypatch.setattr(pipeline, "from_file", fake)

    def wait_for_it() -> dict:
        assert called.wait(timeout=5), "the pipeline was never called"
        return received

    return wait_for_it


@pytest.fixture
def client(tmp_path):
    with TestClient(api.create_app(db=str(tmp_path / "prova.db"))) as c:
        yield c


def _minimal_recipe() -> dict:
    """A valid, small recipe, in the shape `to_dict()` produces."""
    from reel2recipe.recipe import Source, from_draft

    return from_draft(
        {"titolo": "Pane", "porzioni": "2 persone",
         "ingredienti": [{"nome": "farina 00", "quantita_raw": "250", "unita_raw": "g"}],
         "procedimento": ["Impasta."], "lacune": []},
        source=Source.now(url="https://x/y", author="tester"),
    ).to_dict()


# --------------------------------------------------------------------------------------
# The two output axes, from the request to the pipeline
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_body, expected_language, expected_system",
    [
        ({}, "it", "metrico"),                                       # the defaults
        ({"language": "en"}, "en", "imperiale"),                     # the system follows the language
        ({"language": "en", "system": "metrico"}, "en", "metrico"),  # English with grams
        ({"language": "it", "system": "imperiale"}, "it", "imperiale"),
    ],
)
def test_cook_forwards_language_and_system(client, spy, request_body, expected_language,
                                           expected_system):
    response = client.post("/api/cook", json={"url": "https://esempio.test/reel/1", **request_body})
    assert response.status_code == 200
    received = spy()
    assert received["language"] == expected_language
    assert received["system"] == expected_system


def test_cook_forwards_the_processing_options(client, spy):
    client.post("/api/cook", json={
        "url": "https://esempio.test/reel/1",
        "asr_backend": "mlx", "llm_model": "qwen2.5:14b", "skip_audio": True,
    })
    received = spy()
    assert received["asr_backend"] == "mlx"
    assert received["llm_model"] == "qwen2.5:14b"
    assert received["skip_audio"] is True


def test_cook_does_not_declare_a_spoken_language_it_does_not_know(client, spy):
    """Without an explicit choice, Whisper is told nothing: it recognises the language itself.

    It is not enough for `asr.DEFAULT_LANGUAGE` to be `None` — the API must also not invent a
    value of its own, for instance by deducing it from the requested output language.
    """
    client.post("/api/cook", json={"url": "https://esempio.test/reel/1", "language": "en"})
    assert spy()["audio_language"] is None


def test_cook_forwards_the_forced_spoken_language(client, spy):
    client.post("/api/cook", json={"url": "https://esempio.test/reel/1", "audio_language": "en"})
    assert spy()["audio_language"] == "en"


def test_cook_without_a_url_is_refused(client):
    assert client.post("/api/cook", json={"url": "   "}).status_code == 422


# --------------------------------------------------------------------------------------
# The uploaded file: the same options as the link, not a subset
# --------------------------------------------------------------------------------------


def test_cook_file_forwards_every_option(client, spy):
    """The upload accepted only language and system: the ASR backend, the model and
    `skip_audio` were dropped in silence. Dragging a video must not be worth less than pasting
    a link."""
    response = client.post(
        "/api/cook-file",
        params={"asr_backend": "faster-whisper", "llm_model": "qwen2.5:14b",
                "skip_audio": "true", "language": "en", "audio_language": "it",
                "caption": "una prova"},
        files={"file": ("reel.mp4", b"non un video vero", "video/mp4")},
    )
    assert response.status_code == 200

    received = spy()
    assert received["asr_backend"] == "faster-whisper"
    assert received["llm_model"] == "qwen2.5:14b"
    assert received["skip_audio"] is True
    assert received["caption"] == "una prova"
    assert received["language"] == "en"
    assert received["system"] == "imperiale"
    assert received["audio_language"] == "it"


def test_cook_file_cleans_up_the_temporary(client, spy):
    """The uploaded file is written into a temporary folder and has to vanish when the job
    ends, successful or not: it is third-party material (AGENTS.md §7)."""
    client.post("/api/cook-file", files={"file": ("reel.mp4", b"xxx", "video/mp4")})
    path = spy()["positional"][0]
    # The spy fires *inside* the job and the file vanishes just afterwards: the thread is
    # given a moment to reach its `finally`.
    for _ in range(50):
        if not path.exists():
            break
        threading.Event().wait(0.02)
    assert not path.exists(), f"temporary left on disk: {path}"


# --------------------------------------------------------------------------------------
# The fallback rule lives in one place only
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("language, expected", [("it", "metrico"), ("en", "imperiale")])
def test_the_system_follows_the_language(language, expected):
    assert api.CookRequest(language=language).axes()["system"] == expected


def test_an_explicitly_asked_system_wins():
    axes = api.CookRequest(language="en", system="metrico").axes()
    assert axes == {"language": "en", "system": "metrico"}


# --------------------------------------------------------------------------------------
# The API's errors follow the language of the INTERFACE
# --------------------------------------------------------------------------------------


def test_translated_errors(client):
    """`ui_language` and not `language`: on `/api/cook` the latter already exists and means
    something else — which language to produce the recipe in. Calling them the same would have
    tied the buttons' language to the content's without anybody deciding it."""
    assert client.get("/api/export?ui_language=en").json()["detail"] == "The library is empty."
    assert client.get("/api/export?ui_language=it").json()["detail"] == "Libreria vuota."
    assert client.get("/api/recipes/999?ui_language=en").json()["detail"] == "Recipe not found."


def test_errors_in_italian_when_nothing_is_stated(client):
    """Without `ui_language` it falls back to Italian, the language the project is written in: a
    fallback has to be a real language, not a raw key."""
    assert client.get("/api/export").json()["detail"] == "Libreria vuota."


def test_an_unknown_language_does_not_make_the_message_vanish(client):
    """That is exactly what the fallback is for: better an Italian sentence inside output in
    another language than a `KeyError` in front of the user."""
    assert client.get("/api/export?ui_language=de").json()["detail"] == "Libreria vuota."


# --------------------------------------------------------------------------------------
# The export: the format asked for has to be the one produced
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt, media_type, extension", [
    ("mela", "application/json", ".melarecipe"),
    ("markdown", "text/markdown", ".md"),
    ("pdf", "application/pdf", ".pdf"),
])
def test_the_export_honours_the_format_asked_for(client, fmt, media_type, extension):
    """The query parameter has to actually reach the code that picks the format.

    No test covered it, and during the migration the parameter was renamed from `formato` to
    `format_` in the Python signature — which in FastAPI *is* the query parameter's name. The
    page kept sending `?formato=`, which by then matched nothing: every export fell through to
    the default and returned a `.melarecipe` labelled with the format that had been asked for.
    No error, a wrong file, and you only see it on opening it. Found by running the product,
    not the suite.

    The query name is now `?format=` and, since it cannot be the Python parameter's name
    without shadowing the builtin, it is pinned by an explicit `Query(alias="format")` rather
    than by the spelling of a signature — which is the part that moved last time.
    """
    if fmt == "pdf":
        pytest.importorskip("reportlab")

    id = client.post("/api/recipes", json=_minimal_recipe()).json()["id"]
    response = client.get(f"/api/recipes/{id}/export?format={fmt}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert extension in response.headers.get("content-disposition", "")


def test_an_unknown_format_does_not_become_a_mela(client):
    """The other way round: a format that does not exist has to say so, not fall back
    silently."""
    id = client.post("/api/recipes", json=_minimal_recipe()).json()["id"]
    response = client.get(f"/api/recipes/{id}/export?format=wrong")
    assert response.status_code == 400
    assert "wrong" in response.json()["detail"]
