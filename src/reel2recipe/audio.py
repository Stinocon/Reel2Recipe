"""audio.py — pulling the audio track out of the video, with ffmpeg.

Whisper wants a mono WAV at 16 kHz: it is the format the model was trained on, and handing
it over ready-made avoids an internal resampling and a few transcription errors.

`ffmpeg` is a system binary, not a Python package: if it is missing, the error message has
to say how to install it rather than settle for a FileNotFoundError.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

WHISPER_SAMPLE_RATE = 16_000


class AudioError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise AudioError(
            "ffmpeg is not installed: without it the audio cannot be pulled out of videos.\n"
            "  macOS:  brew install ffmpeg\n"
            "  Linux:  sudo apt install ffmpeg\n"
            "Or run ./install.sh, which takes care of it by itself."
        )
    return path


def duration_s(path: Path | str) -> float | None:
    """Duration of the media in seconds, via ffprobe. `None` when it cannot be determined —
    it is incidental information and must not make anything fail."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        outcome = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(outcome.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return None


def extract_audio(media_path: Path | str, output_folder: Path | str | None = None) -> Path:
    """Extracts the audio as 16 kHz mono WAV. If the file is already a WAV with those
    characteristics, the work is not redone.

    Returns the path of the WAV produced.
    """
    ffmpeg = _require_ffmpeg()
    media_path = Path(media_path)
    if not media_path.is_file():
        raise AudioError(f"File not found: {media_path}")

    folder = Path(output_folder) if output_folder else media_path.parent
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{media_path.stem}.16k.wav"

    if destination.is_file() and destination.stat().st_size > 0:
        return destination   # already extracted on an earlier run

    command = [
        ffmpeg, "-nostdin", "-y",
        "-i", str(media_path),
        "-vn",                       # drop the video: only the voice is wanted here
        "-ac", "1",                  # mono
        "-ar", str(WHISPER_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        str(destination),
    ]
    outcome = subprocess.run(command, capture_output=True, text=True)
    if outcome.returncode != 0:
        tail = "\n".join(outcome.stderr.strip().splitlines()[-5:])
        raise AudioError(f"ffmpeg could not extract the audio from {media_path.name}:\n{tail}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise AudioError(
            f"{media_path.name} holds no usable audio track. "
            "If the recipe is all in the caption, it is still possible to carry on."
        )
    return destination


def extract_cover(video_path: Path | str, output_folder: Path | str | None = None,
                  at_second: float = 1.0) -> Path | None:
    """A frame to use as the recipe's cover in Mela.

    Only needed when yt-dlp has not already saved the thumbnail. Fails silently (returns
    `None`): a missing image is no reason to lose a recipe.
    """
    if not ffmpeg_available():
        return None
    video_path = Path(video_path)
    folder = Path(output_folder) if output_folder else video_path.parent
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{video_path.stem}.copertina.jpg"

    if destination.is_file():
        return destination

    command = [
        shutil.which("ffmpeg"), "-nostdin", "-y",
        "-ss", str(at_second), "-i", str(video_path),
        "-frames:v", "1",
        "-vf", "scale=640:-1",       # enough for a cover, and keeps the weight down
        "-q:v", "4",
        str(destination),
    ]
    outcome = subprocess.run(command, capture_output=True, text=True)
    if outcome.returncode != 0 or not destination.is_file():
        return None
    return destination
