"""asr.py — trascrizione dell'audio, in locale.

Due backend, entrambi sulla macchina, con ripiego automatico:

  1. **mlx-whisper** — usa la GPU dei Mac Apple Silicon (Metal). Molto più veloce, è la
     scelta migliore dove è disponibile.
  2. **faster-whisper** — CPU, funziona ovunque. È il riferimento portabile.

Nessuno dei due manda audio da nessuna parte: la trascrizione avviene interamente sul PC.
È una scelta di progetto, non un dettaglio implementativo — il prodotto deve continuare a
funzionare senza abbonamenti attivi e senza connessione.

Se nessun backend è installato, `trascrivi` solleva `ErroreTrascrizione` con le istruzioni
per rimediare. Il chiamante può decidere di proseguire con la sola didascalia: molte
ricette sono già scritte per intero nel testo del post.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

# large-v3-turbo: qualità vicina al large-v3 a una frazione del tempo. Sui reel
# (30-90 secondi di parlato) la differenza rispetto ai modelli piccoli si sente,
# soprattutto sui nomi degli ingredienti.
MODELLO_PREDEFINITO = "large-v3-turbo"
LINGUA_PREDEFINITA = "it"


class ErroreTrascrizione(RuntimeError):
    pass


@dataclass
class Trascrizione:
    testo: str
    lingua: str | None = None
    backend: str | None = None
    modello: str | None = None
    durata_s: float | None = None

    def __bool__(self) -> bool:
        return bool(self.testo.strip())


# --------------------------------------------------------------------------------------
# Disponibilità dei backend
# --------------------------------------------------------------------------------------


def _mlx_disponibile() -> bool:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _faster_whisper_disponibile() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def backend_disponibili() -> list[str]:
    """Backend utilizzabili su questa macchina, dal più veloce al più portabile."""
    disponibili = []
    if _mlx_disponibile():
        disponibili.append("mlx")
    if _faster_whisper_disponibile():
        disponibili.append("faster-whisper")
    return disponibili


# --------------------------------------------------------------------------------------
# Implementazioni
# --------------------------------------------------------------------------------------

# I nomi dei modelli MLX sono repository Hugging Face, non etichette brevi.
_MODELLI_MLX = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
}


def _trascrivi_mlx(percorso: Path, lingua: str | None, modello: str) -> Trascrizione:
    import mlx_whisper

    esito = mlx_whisper.transcribe(
        str(percorso),
        path_or_hf_repo=_MODELLI_MLX.get(modello, modello),
        language=lingua,
        # Le ricette sono piene di numeri e unità: conviene lasciare a Whisper poca
        # libertà creativa, o "200 g" diventa "duecento grammi circa".
        temperature=0.0,
        condition_on_previous_text=False,
    )
    return Trascrizione(
        testo=(esito.get("text") or "").strip(),
        lingua=esito.get("language") or lingua,
        backend="mlx",
        modello=modello,
    )


def _trascrivi_faster_whisper(percorso: Path, lingua: str | None, modello: str) -> Trascrizione:
    from faster_whisper import WhisperModel

    # int8 tiene bassi memoria e tempi su CPU con una perdita di qualità trascurabile
    # su parlato pulito come quello dei reel.
    motore = WhisperModel(modello, device="cpu", compute_type="int8")
    segmenti, info = motore.transcribe(
        str(percorso),
        language=lingua,
        beam_size=5,
        vad_filter=True,               # scarta silenzi e musica di sottofondo
        condition_on_previous_text=False,
        temperature=0.0,
    )
    testo = " ".join(s.text.strip() for s in segmenti).strip()
    return Trascrizione(
        testo=testo,
        lingua=getattr(info, "language", lingua),
        backend="faster-whisper",
        modello=modello,
        durata_s=getattr(info, "duration", None),
    )


# --------------------------------------------------------------------------------------
# Interfaccia pubblica
# --------------------------------------------------------------------------------------


def trascrivi(
    percorso_audio: Path | str,
    lingua: str | None = LINGUA_PREDEFINITA,
    modello: str = MODELLO_PREDEFINITO,
    backend: str = "auto",
) -> Trascrizione:
    """Trascrive un file audio.

    `backend` accetta "auto" (predefinito), "mlx" o "faster-whisper". Con "auto" si usa
    il più veloce disponibile e si ripiega sull'altro se il primo fallisce a runtime —
    per esempio perché il modello non si scarica.
    """
    percorso = Path(percorso_audio)
    if not percorso.is_file():
        raise ErroreTrascrizione(f"File audio non trovato: {percorso}")

    if backend == "mlx":
        candidati = ["mlx"]
    elif backend in ("faster-whisper", "locale"):
        candidati = ["faster-whisper"]
    else:
        candidati = backend_disponibili()

    if not candidati:
        raise ErroreTrascrizione(
            "Nessun motore di trascrizione installato.\n"
            "  Portabile (ovunque):     uv sync --extra asr\n"
            "  Accelerato (Mac M1/M2+): uv sync --extra asr --extra asr-mlx\n"
            "Oppure esegui ./install.sh. In alternativa procedi senza audio: se la ricetta "
            "è scritta nella didascalia, Reel2Recipe la estrae lo stesso."
        )

    errori: list[str] = []
    for nome in candidati:
        try:
            if nome == "mlx" and _mlx_disponibile():
                return _trascrivi_mlx(percorso, lingua, modello)
            if nome == "faster-whisper" and _faster_whisper_disponibile():
                return _trascrivi_faster_whisper(percorso, lingua, modello)
        except Exception as e:   # ripiego sull'altro backend, ma senza perdere il motivo
            errori.append(f"{nome}: {type(e).__name__}: {e}")

    raise ErroreTrascrizione(
        "Trascrizione fallita su tutti i backend disponibili.\n" + "\n".join(errori)
    )
