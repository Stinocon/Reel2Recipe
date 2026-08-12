"""asr.py — speech transcription, locally.

Two backends, both on the machine, with an automatic fallback:

  1. **mlx-whisper** — uses the GPU on Apple Silicon Macs (Metal). Much faster, and the
     better choice wherever it is available.
  2. **faster-whisper** — CPU, works everywhere. It is the portable reference.

Neither sends audio anywhere: transcription happens entirely on this machine. That is a
design decision, not an implementation detail — the product has to keep working without an
active subscription and without a connection.

If no backend is installed, `transcribe` raises `TranscriptionError` with instructions for
fixing it. The caller may decide to carry on with the caption alone: plenty of recipes are
already written out in full in the text of the post.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

# large-v3-turbo: quality close to large-v3 at a fraction of the time. On reels
# (30-90 seconds of speech) the difference against the small models is audible, on
# ingredient names above all.
DEFAULT_MODEL = "large-v3-turbo"

# `None` means: let Whisper detect it, which is the thing it natively does.
#
# This used to be "it", and it was not a default but a constraint: the language was never
# exposed by the CLI or the API, so *every* reel was handed to Whisper with the claim that
# it was Italian. An English reel was not translated badly — it was transcribed badly,
# Italian words forced onto English sounds, and from there the whole rest of the chain
# worked on rubbish. The fault was invisible downstream, because the local model produces
# a plausible recipe anyway.
#
# Both backends report the language they detected in `Transcript.language`: the detection
# is not lost, and anyone who wants to force it still can.
DEFAULT_LANGUAGE = None


class TranscriptionError(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    language: str | None = None
    backend: str | None = None
    model: str | None = None
    duration_s: float | None = None

    def __bool__(self) -> bool:
        return bool(self.text.strip())


# --------------------------------------------------------------------------------------
# Backend availability
# --------------------------------------------------------------------------------------


def _mlx_available() -> bool:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def available_backends() -> list[str]:
    """Backends usable on this machine, fastest to most portable."""
    available = []
    if _mlx_available():
        available.append("mlx")
    if _faster_whisper_available():
        available.append("faster-whisper")
    return available


# --------------------------------------------------------------------------------------
# Implementations
# --------------------------------------------------------------------------------------

# MLX model names are Hugging Face repositories, not short labels.
_MLX_MODELS = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
}


def _transcribe_mlx(path: Path, language: str | None, model: str) -> Transcript:
    import mlx_whisper

    outcome = mlx_whisper.transcribe(
        str(path),
        path_or_hf_repo=_MLX_MODELS.get(model, model),
        language=language,
        # Recipes are full of numbers and units: Whisper is better off with little
        # creative latitude, or "200 g" turns into "about two hundred grams".
        temperature=0.0,
        condition_on_previous_text=False,
    )
    return Transcript(
        text=(outcome.get("text") or "").strip(),
        language=outcome.get("language") or language,
        backend="mlx",
        model=model,
    )


def _transcribe_faster_whisper(path: Path, language: str | None, model: str) -> Transcript:
    from faster_whisper import WhisperModel

    # int8 keeps memory and time down on CPU, at a loss of quality that is negligible on
    # clean speech like a reel's.
    engine = WhisperModel(model, device="cpu", compute_type="int8")
    segments, info = engine.transcribe(
        str(path),
        language=language,
        beam_size=5,
        vad_filter=True,               # drops silence and background music
        condition_on_previous_text=False,
        temperature=0.0,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return Transcript(
        text=text,
        language=getattr(info, "language", language),
        backend="faster-whisper",
        model=model,
        duration_s=getattr(info, "duration", None),
    )


# --------------------------------------------------------------------------------------
# Public interface
# --------------------------------------------------------------------------------------


def transcribe(
    audio_path: Path | str,
    language: str | None = DEFAULT_LANGUAGE,
    model: str = DEFAULT_MODEL,
    backend: str = "auto",
) -> Transcript:
    """Transcribes an audio file.

    `backend` takes "auto" (the default), "mlx" or "faster-whisper". With "auto" the
    fastest available one is used, falling back to the other if the first fails at
    runtime — because the model would not download, for instance.
    """
    path = Path(audio_path)
    if not path.is_file():
        raise TranscriptionError(f"Audio file not found: {path}")

    if backend == "mlx":
        candidates = ["mlx"]
    # "locale" is the name this backend went by before the rename: it may still be sitting
    # in someone's shell history or script, and rejecting it would only produce a puzzle.
    elif backend in ("faster-whisper", "local", "locale"):
        candidates = ["faster-whisper"]
    else:
        candidates = available_backends()

    if not candidates:
        raise TranscriptionError(
            "No transcription engine installed.\n"
            "  Portable (anywhere):      uv sync --extra asr\n"
            "  Accelerated (Mac M1/M2+): uv sync --extra asr --extra asr-mlx\n"
            "Or run ./install.sh. Alternatively carry on without audio: if the recipe is "
            "written in the caption, Reel2Recipe extracts it all the same."
        )

    errors: list[str] = []
    for name in candidates:
        try:
            if name == "mlx" and _mlx_available():
                return _transcribe_mlx(path, language, model)
            if name == "faster-whisper" and _faster_whisper_available():
                return _transcribe_faster_whisper(path, language, model)
        except Exception as e:   # fall back to the other backend, without losing the reason
            errors.append(f"{name}: {type(e).__name__}: {e}")

    raise TranscriptionError(
        "Transcription failed on every available backend.\n" + "\n".join(errors)
    )
