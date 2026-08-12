"""audio.py — estrazione della traccia audio dal video, con ffmpeg.

Whisper vuole un WAV mono a 16 kHz: è il formato su cui il modello è stato addestrato, e
darglielo già pronto evita un ricampionamento interno e qualche errore di trascrizione.

`ffmpeg` è un binario di sistema, non un pacchetto Python: se manca, il messaggio d'errore
deve dire come installarlo, non limitarsi a un FileNotFoundError.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FREQUENZA_WHISPER = 16_000


class ErroreAudio(RuntimeError):
    pass


def ffmpeg_disponibile() -> bool:
    return shutil.which("ffmpeg") is not None


def _pretendi_ffmpeg() -> str:
    percorso = shutil.which("ffmpeg")
    if not percorso:
        raise ErroreAudio(
            "ffmpeg non è installato: senza non si può estrarre l'audio dai video.\n"
            "  macOS:  brew install ffmpeg\n"
            "  Linux:  sudo apt install ffmpeg\n"
            "Oppure esegui ./install.sh, che se ne occupa da sé."
        )
    return percorso


def durata_s(percorso: Path | str) -> float | None:
    """Durata del media in secondi, via ffprobe. `None` se non determinabile —
    è un'informazione accessoria, non deve far fallire nulla."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        esito = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(percorso)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(esito.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return None


def estrai_audio(percorso_media: Path | str, cartella_uscita: Path | str | None = None) -> Path:
    """Estrae l'audio in WAV 16 kHz mono. Se il file è già un WAV con quelle
    caratteristiche non rifà il lavoro.

    Ritorna il percorso del WAV prodotto.
    """
    ffmpeg = _pretendi_ffmpeg()
    percorso_media = Path(percorso_media)
    if not percorso_media.is_file():
        raise ErroreAudio(f"File non trovato: {percorso_media}")

    cartella = Path(cartella_uscita) if cartella_uscita else percorso_media.parent
    cartella.mkdir(parents=True, exist_ok=True)
    destinazione = cartella / f"{percorso_media.stem}.16k.wav"

    if destinazione.is_file() and destinazione.stat().st_size > 0:
        return destinazione   # già estratto in una esecuzione precedente

    comando = [
        ffmpeg, "-nostdin", "-y",
        "-i", str(percorso_media),
        "-vn",                       # scarta il video: qui serve solo la voce
        "-ac", "1",                  # mono
        "-ar", str(FREQUENZA_WHISPER),
        "-c:a", "pcm_s16le",
        str(destinazione),
    ]
    esito = subprocess.run(comando, capture_output=True, text=True)
    if esito.returncode != 0:
        coda = "\n".join(esito.stderr.strip().splitlines()[-5:])
        raise ErroreAudio(f"ffmpeg non è riuscito a estrarre l'audio da {percorso_media.name}:\n{coda}")
    if not destinazione.is_file() or destinazione.stat().st_size == 0:
        raise ErroreAudio(
            f"{percorso_media.name} non contiene una traccia audio utilizzabile. "
            "Se la ricetta è tutta nella didascalia si può procedere lo stesso."
        )
    return destinazione


def estrai_copertina(percorso_video: Path | str, cartella_uscita: Path | str | None = None,
                     istante_s: float = 1.0) -> Path | None:
    """Un fotogramma da usare come copertina della ricetta in Mela.

    Serve solo quando yt-dlp non ha già salvato l'anteprima. Fallisce in silenzio
    (ritorna `None`): un'immagine mancante non è un motivo per perdere una ricetta.
    """
    if not ffmpeg_disponibile():
        return None
    percorso_video = Path(percorso_video)
    cartella = Path(cartella_uscita) if cartella_uscita else percorso_video.parent
    cartella.mkdir(parents=True, exist_ok=True)
    destinazione = cartella / f"{percorso_video.stem}.copertina.jpg"

    if destinazione.is_file():
        return destinazione

    comando = [
        shutil.which("ffmpeg"), "-nostdin", "-y",
        "-ss", str(istante_s), "-i", str(percorso_video),
        "-frames:v", "1",
        "-vf", "scale=640:-1",       # sufficiente per una copertina, tiene basso il peso
        "-q:v", "4",
        str(destinazione),
    ]
    esito = subprocess.run(comando, capture_output=True, text=True)
    if esito.returncode != 0 or not destinazione.is_file():
        return None
    return destinazione
