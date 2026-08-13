"""test_api.py — che le scelte dell'utente arrivino davvero alla pipeline.

Questi test non provano l'estrazione (serve Ollama, e c'è `test_modello.py` per quello):
provano il **cablaggio**. Il pannello delle opzioni disegnava una scelta della lingua che
non veniva letta da nessuno, quindi ogni lavorazione usciva in italiano metrico qualunque
cosa si scegliesse. Nessun test copriva quel tratto perché `tests/` non aveva alcun test
dell'API: il difetto non aveva modo di farsi vedere.

La pipeline viene sostituita da una spia che registra gli argomenti ricevuti e dichiara un
esito fallito. Fallito di proposito: così `_concludi_con_esito` esce subito e non tocca la
libreria, e il test resta sul cablaggio senza portarsi dietro un database.
"""

from __future__ import annotations

import threading

import pytest

from reel2recipe import api, pipeline

TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def spia(monkeypatch):
    """Sostituisce `pipeline.from_url` e `pipeline.from_file` con una spia sugli argomenti.

    La lavorazione gira in un thread, quindi la chiamata HTTP torna prima che la spia sia
    stata invocata: l'evento è ciò che permette di aspettarla senza una pausa a caso.
    """
    ricevuti: dict = {}
    chiamata = threading.Event()

    def falsa(*args, **kwargs):
        ricevuti.update(kwargs)
        ricevuti["posizionali"] = args
        chiamata.set()
        return pipeline.Outcome(error="spia: nessuna lavorazione vera")

    monkeypatch.setattr(pipeline, "from_url", falsa)
    monkeypatch.setattr(pipeline, "from_file", falsa)

    def attendi() -> dict:
        assert chiamata.wait(timeout=5), "la pipeline non è mai stata chiamata"
        return ricevuti

    return attendi


@pytest.fixture
def client(tmp_path):
    with TestClient(api.create_app(db=str(tmp_path / "prova.db"))) as c:
        yield c


def _ricetta_minima() -> dict:
    """Una ricetta valida e piccola, nella forma che `to_dict()` produce."""
    from reel2recipe.recipe import Source, from_draft

    return from_draft(
        {"titolo": "Pane", "porzioni": "2 persone",
         "ingredienti": [{"nome": "farina 00", "quantita_raw": "250", "unita_raw": "g"}],
         "procedimento": ["Impasta."], "lacune": []},
        source=Source.now(url="https://x/y", author="tester"),
    ).to_dict()


# --------------------------------------------------------------------------------------
# I due assi di uscita, dalla richiesta alla pipeline
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "richiesta, lingua_attesa, sistema_atteso",
    [
        ({}, "it", "metrico"),                                    # predefiniti
        ({"language": "en"}, "en", "imperiale"),                    # il sistema segue la lingua
        ({"language": "en", "system": "metrico"}, "en", "metrico"),  # inglese coi grammi
        ({"language": "it", "system": "imperiale"}, "it", "imperiale"),
    ],
)
def test_cook_inoltra_lingua_e_sistema(client, spia, richiesta, lingua_attesa, sistema_atteso):
    risposta = client.post("/api/cook", json={"url": "https://esempio.test/reel/1", **richiesta})
    assert risposta.status_code == 200
    ricevuti = spia()
    assert ricevuti["language"] == lingua_attesa
    assert ricevuti["system"] == sistema_atteso


def test_cook_inoltra_le_opzioni_di_lavorazione(client, spia):
    client.post("/api/cook", json={
        "url": "https://esempio.test/reel/1",
        "asr_backend": "mlx", "llm_model": "qwen2.5:14b", "skip_audio": True,
    })
    ricevuti = spia()
    assert ricevuti["asr_backend"] == "mlx"
    assert ricevuti["llm_model"] == "qwen2.5:14b"
    assert ricevuti["skip_audio"] is True


def test_cook_non_dichiara_una_lingua_del_parlato_che_non_sa(client, spia):
    """Senza una scelta esplicita, a Whisper non si dice nulla: la riconosce da sé.

    Non basta che `asr.DEFAULT_LANGUAGE` sia `None` — l'API deve anche non inventarsi
    un valore per conto suo, per esempio deducendolo dalla lingua richiesta in uscita.
    """
    client.post("/api/cook", json={"url": "https://esempio.test/reel/1", "language": "en"})
    assert spia()["audio_language"] is None


def test_cook_inoltra_la_lingua_del_parlato_forzata(client, spia):
    client.post("/api/cook", json={"url": "https://esempio.test/reel/1", "audio_language": "en"})
    assert spia()["audio_language"] == "en"


def test_cook_senza_url_e_rifiutato(client):
    assert client.post("/api/cook", json={"url": "   "}).status_code == 422


# --------------------------------------------------------------------------------------
# Il file caricato: le stesse opzioni del link, non un sottoinsieme
# --------------------------------------------------------------------------------------


def test_cook_file_inoltra_tutte_le_opzioni(client, spia):
    """Il caricamento accettava solo lingua e sistema: backend ASR, modello e `salta_audio`
    venivano scartati in silenzio. Trascinare un video non deve valere meno che incollare
    un link."""
    risposta = client.post(
        "/api/cook-file",
        params={"asr_backend": "faster-whisper", "llm_model": "qwen2.5:14b",
                "skip_audio": "true", "language": "en", "audio_language": "it",
                "caption": "una prova"},
        files={"file": ("reel.mp4", b"non un video vero", "video/mp4")},
    )
    assert risposta.status_code == 200

    ricevuti = spia()
    assert ricevuti["asr_backend"] == "faster-whisper"
    assert ricevuti["llm_model"] == "qwen2.5:14b"
    assert ricevuti["skip_audio"] is True
    assert ricevuti["caption"] == "una prova"
    assert ricevuti["language"] == "en"
    assert ricevuti["system"] == "imperiale"
    assert ricevuti["audio_language"] == "it"


def test_cook_file_ripulisce_il_temporaneo(client, spia):
    """Il file caricato viene scritto in una cartella temporanea e deve sparire a fine
    lavorazione, riuscita o meno: è materiale di terzi (AGENTS.md §7)."""
    client.post("/api/cook-file", files={"file": ("reel.mp4", b"xxx", "video/mp4")})
    percorso = spia()["posizionali"][0]
    # La spia scatta *dentro* la lavorazione, il file sparisce subito dopo: si concede
    # un attimo al thread per arrivare al `finally`.
    for _ in range(50):
        if not percorso.exists():
            break
        threading.Event().wait(0.02)
    assert not percorso.exists(), f"temporaneo rimasto sul disco: {percorso}"


# --------------------------------------------------------------------------------------
# La regola di ripiego sta in un punto solo
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("lingua, atteso", [("it", "metrico"), ("en", "imperiale")])
def test_il_sistema_segue_la_lingua(lingua, atteso):
    assert api.CookRequest(language=lingua).axes()["system"] == atteso


def test_il_sistema_chiesto_esplicitamente_vince():
    assi = api.CookRequest(language="en", system="metrico").axes()
    assert assi == {"language": "en", "system": "metrico"}


# --------------------------------------------------------------------------------------
# Gli errori dell'API seguono la lingua dell'INTERFACCIA
# --------------------------------------------------------------------------------------


def test_errori_tradotti(client):
    """`lingua_ui` e non `lingua`: su `/api/cook` quest'ultimo esiste già e vuol dire
    un'altra cosa — in che lingua produrre la ricetta. Chiamarli uguale avrebbe legato la
    lingua dei bottoni a quella del contenuto senza che nessuno lo avesse deciso."""
    assert client.get("/api/export?lingua_ui=en").json()["detail"] == "The library is empty."
    assert client.get("/api/export?lingua_ui=it").json()["detail"] == "Libreria vuota."
    assert client.get("/api/ricette/999?lingua_ui=en").json()["detail"] == "Recipe not found."


def test_errori_in_italiano_senza_indicazione(client):
    """Senza `lingua_ui` si ripiega sull'italiano, che è la lingua in cui il progetto è
    scritto: un ripiego deve essere una lingua vera, non una chiave grezza."""
    assert client.get("/api/export").json()["detail"] == "Libreria vuota."


def test_una_lingua_ignota_non_fa_sparire_il_messaggio(client):
    """Il ripiego serve proprio a questo: meglio una frase italiana dentro un'uscita in
    un'altra lingua che un `KeyError` davanti all'utente."""
    assert client.get("/api/export?lingua_ui=de").json()["detail"] == "Libreria vuota."


# --------------------------------------------------------------------------------------
# L'export: il formato chiesto deve essere quello prodotto
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("formato, tipo, estensione", [
    ("mela", "application/json", ".melarecipe"),
    ("markdown", "text/markdown", ".md"),
    ("pdf", "application/pdf", ".pdf"),
])
def test_l_export_rispetta_il_formato_chiesto(client, formato, tipo, estensione):
    """Il parametro di query deve arrivare davvero al codice che sceglie il formato.

    Nessun test lo copriva, e durante la migrazione il parametro è stato rinominato da
    `formato` a `format_` nella firma Python — che in FastAPI *è* il nome del parametro di
    query. La pagina continuava a mandare `?formato=`, che a quel punto non corrispondeva a
    nulla: ogni export cadeva sul valore predefinito e restituiva un `.melarecipe` con
    l'etichetta del formato chiesto. Nessun errore, un file sbagliato, e lo si vede solo
    aprendolo. Trovato eseguendo il prodotto, non la suite.
    """
    if formato == "pdf":
        pytest.importorskip("reportlab")

    id = client.post("/api/ricette", json=_ricetta_minima()).json()["id"]
    risposta = client.get(f"/api/ricette/{id}/export?formato={formato}")

    assert risposta.status_code == 200
    assert risposta.headers["content-type"].startswith(tipo)
    assert estensione in risposta.headers.get("content-disposition", "")


def test_un_formato_sconosciuto_non_diventa_un_mela(client):
    """Il verso opposto: un formato che non esiste deve dirlo, non ripiegare in silenzio."""
    id = client.post("/api/ricette", json=_ricetta_minima()).json()["id"]
    risposta = client.get(f"/api/ricette/{id}/export?formato=sbagliato")
    assert risposta.status_code == 400
    assert "sbagliato" in risposta.json()["detail"]
