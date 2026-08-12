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
    """Sostituisce `pipeline.da_url` e `pipeline.da_file` con una spia sugli argomenti.

    La lavorazione gira in un thread, quindi la chiamata HTTP torna prima che la spia sia
    stata invocata: l'evento è ciò che permette di aspettarla senza una pausa a caso.
    """
    ricevuti: dict = {}
    chiamata = threading.Event()

    def falsa(*args, **kwargs):
        ricevuti.update(kwargs)
        ricevuti["posizionali"] = args
        chiamata.set()
        return pipeline.Esito(errore="spia: nessuna lavorazione vera")

    monkeypatch.setattr(pipeline, "da_url", falsa)
    monkeypatch.setattr(pipeline, "da_file", falsa)

    def attendi() -> dict:
        assert chiamata.wait(timeout=5), "la pipeline non è mai stata chiamata"
        return ricevuti

    return attendi


@pytest.fixture
def client(tmp_path):
    with TestClient(api.crea_app(db=str(tmp_path / "prova.db"))) as c:
        yield c


# --------------------------------------------------------------------------------------
# I due assi di uscita, dalla richiesta alla pipeline
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "richiesta, lingua_attesa, sistema_atteso",
    [
        ({}, "it", "metrico"),                                    # predefiniti
        ({"lingua": "en"}, "en", "imperiale"),                    # il sistema segue la lingua
        ({"lingua": "en", "sistema": "metrico"}, "en", "metrico"),  # inglese coi grammi
        ({"lingua": "it", "sistema": "imperiale"}, "it", "imperiale"),
    ],
)
def test_cook_inoltra_lingua_e_sistema(client, spia, richiesta, lingua_attesa, sistema_atteso):
    risposta = client.post("/api/cook", json={"url": "https://esempio.test/reel/1", **richiesta})
    assert risposta.status_code == 200
    ricevuti = spia()
    assert ricevuti["lingua"] == lingua_attesa
    assert ricevuti["sistema"] == sistema_atteso


def test_cook_inoltra_le_opzioni_di_lavorazione(client, spia):
    client.post("/api/cook", json={
        "url": "https://esempio.test/reel/1",
        "backend_asr": "mlx", "modello_llm": "qwen2.5:14b", "salta_audio": True,
    })
    ricevuti = spia()
    assert ricevuti["backend_asr"] == "mlx"
    assert ricevuti["modello_llm"] == "qwen2.5:14b"
    assert ricevuti["salta_audio"] is True


def test_cook_non_dichiara_una_lingua_del_parlato_che_non_sa(client, spia):
    """Senza una scelta esplicita, a Whisper non si dice nulla: la riconosce da sé.

    Non basta che `asr.LINGUA_PREDEFINITA` sia `None` — l'API deve anche non inventarsi
    un valore per conto suo, per esempio deducendolo dalla lingua richiesta in uscita.
    """
    client.post("/api/cook", json={"url": "https://esempio.test/reel/1", "lingua": "en"})
    assert spia()["lingua_audio"] is None


def test_cook_inoltra_la_lingua_del_parlato_forzata(client, spia):
    client.post("/api/cook", json={"url": "https://esempio.test/reel/1", "lingua_audio": "en"})
    assert spia()["lingua_audio"] == "en"


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
        params={"backend_asr": "faster-whisper", "modello_llm": "qwen2.5:14b",
                "salta_audio": "true", "lingua": "en", "lingua_audio": "it",
                "didascalia": "una prova"},
        files={"file": ("reel.mp4", b"non un video vero", "video/mp4")},
    )
    assert risposta.status_code == 200

    ricevuti = spia()
    assert ricevuti["backend_asr"] == "faster-whisper"
    assert ricevuti["modello_llm"] == "qwen2.5:14b"
    assert ricevuti["salta_audio"] is True
    assert ricevuti["didascalia"] == "una prova"
    assert ricevuti["lingua"] == "en"
    assert ricevuti["sistema"] == "imperiale"
    assert ricevuti["lingua_audio"] == "it"


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
    assert api.RichiestaCook(lingua=lingua).assi()["sistema"] == atteso


def test_il_sistema_chiesto_esplicitamente_vince():
    assi = api.RichiestaCook(lingua="en", sistema="metrico").assi()
    assert assi == {"lingua": "en", "sistema": "metrico"}


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
