"""pipeline.py — the whole chain, from a link to a recipe.

    URL or file  →  acquire  →  audio  →  asr  →  extract  →  recipe  →  Recipe

It lives here and not in the CLI because two things use it: the terminal command and the web
interface. One implementation, one place to fix things.

Every stage reports its own progress through `on_progress`, so the page's "Cook" bar can say
what is happening instead of showing a mute spinner.

Robustness principle: **the pipeline degrades, it does not stop.** If the audio is missing or
the transcription fails, it carries on with the caption alone and declares it. A great many
cooking reels have the complete recipe in the post's text: giving up over an audio problem
would mean losing a recoverable recipe.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import acquire, asr, audio, extract
from .paths import media_folder
from .recipe import Source, Recipe, from_draft
from .units import Catalogue, Language, System, Tables, code_of, load_tables, text_from

Progress = Callable[[str, str], None]   # (stage, message)


# What the pipeline says while it works: progress and warnings.
#
# These follow the language **of the recipe**, not the language of the page's buttons. They are
# sentences about the processing of that recipe and they end up next to the `gaps`, which are
# already in the recipe's language because they are saved with it: letting them diverge would
# produce a card half in one language and half in the other. In normal use the two values
# coincide anyway, because the recipe's language follows the interface's.
TEXTS: Catalogue = {
    "it": {
        "downloading": "Scaricamento del reel…",
        "downloaded": "Scaricato: {label}",
        "reading_file": "Lettura del file…",
        "extracting_audio": "Estrazione della traccia audio…",
        "transcribing": "Trascrizione del parlato in corso…",
        "transcribed": "Trascritti {characters} caratteri ({backend}).",
        "reconstructing": "Il modello locale sta ricostruendo la ricetta…",
        "translating": "Traduzione dei testi nella lingua della ricetta…",
        "author_comments": ("Trovati {how_many} commenti dell'autore: spesso contengono le "
                            "dosi mancanti."),
        "converting": "Conversione delle quantità con le tabelle…",
        "ready_recipe": "Pronta: «{title}».",
        "no_media": "Nessun file multimediale: analizzata la sola didascalia.",
        "audio_failed": "Audio non estratto ({detail}). Si procede con la sola didascalia.",
        "empty_transcript": ("La trascrizione non ha prodotto testo: forse il reel non ha "
                               "parlato."),
        "transcription_failed": ("Trascrizione non riuscita ({detail}). Si procede con la "
                                 "sola didascalia."),
        "speech_only": "Ricetta ricavata dal solo parlato: verifica le quantità.",
        "caption_only": ("Ricetta ricavata dalla sola didascalia: il parlato non è stato "
                            "letto."),
        "nothing_to_analyse": ("Non c'è nulla da analizzare: né didascalia né parlato "
                                 "trascrivibile."),
        "not_a_recipe": "«{label}» non sembra contenere una ricetta di cucina.",
    },
    "en": {
        "downloading": "Downloading the reel…",
        "downloaded": "Downloaded: {label}",
        "reading_file": "Reading the file…",
        "extracting_audio": "Extracting the audio track…",
        "transcribing": "Transcribing the speech…",
        "transcribed": "Transcribed {characters} characters ({backend}).",
        "reconstructing": "The local model is reconstructing the recipe…",
        "translating": "Translating the text into the recipe’s language…",
        "author_comments": ("Found {how_many} comments by the author: they often hold the "
                            "missing amounts."),
        "converting": "Converting the amounts with the tables…",
        "ready_recipe": "Ready: «{title}».",
        "no_media": "No media file: only the caption was analysed.",
        "audio_failed": "Audio not extracted ({detail}). Carrying on with the caption alone.",
        "empty_transcript": "The transcription came out empty: perhaps nobody speaks in the reel.",
        "transcription_failed": ("Transcription failed ({detail}). Carrying on with the "
                                 "caption alone."),
        "speech_only": "Recipe taken from the speech alone: check the amounts.",
        "caption_only": "Recipe taken from the caption alone: the speech was not read.",
        "nothing_to_analyse": "There is nothing to analyse: no caption and no transcribable speech.",
        "not_a_recipe": "«{label}» does not seem to contain a cooking recipe.",
    },
}


def text(language: str, key: str, **data) -> str:
    """A progress sentence or a warning, in the recipe's language."""
    return text_from(TEXTS, language, key, **data)


def _silence(stage: str, message: str) -> None:
    pass


@dataclass
class Outcome:
    """The result of one job, with the trace of how it got there."""

    recipe: Recipe | None = None
    media: acquire.Media | None = None
    transcript: asr.Transcript | None = None
    model: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.recipe is not None


class NotARecipe(RuntimeError):
    """The content analysed is not a cooking recipe."""


# --------------------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------------------


def _transcribe_if_possible(
    media: acquire.Media,
    backend: str,
    asr_model: str,
    audio_language: str | None,
    on_progress: Progress,
    warnings: list[str],
    language: str,
) -> asr.Transcript | None:
    """Extracts the audio and transcribes it. Every failure becomes a warning, not an
    exception: the caption on its own may be enough."""
    if media.path is None:
        warnings.append(text(language, "no_media"))
        return None

    try:
        if media.is_audio:
            audio_path = media.path
        else:
            on_progress("audio", text(language, "extracting_audio"))
            audio_path = audio.extract_audio(media.path, media_folder())
    except audio.AudioError as e:
        warnings.append(text(language, "audio_failed", detail=e))
        return None

    try:
        on_progress("transcription", text(language, "transcribing"))
        transcript = asr.transcribe(audio_path, language=audio_language,
                                    model=asr_model, backend=backend)
        if not transcript:
            warnings.append(text(language, "empty_transcript"))
            return None
        on_progress("transcription", text(language, "transcribed",
                                          characters=len(transcript.text),
                                          backend=transcript.backend))
        return transcript
    except asr.TranscriptionError as e:
        warnings.append(text(language, "transcription_failed", detail=e))
        return None


def _cover(media: acquire.Media) -> list[str]:
    """A cover image for the recipe, if one can be had. It is not essential: a failure here
    must not cost a recipe."""
    if cover_base64 := media.cover_base64():
        return [cover_base64]
    if media.path and not media.is_audio:
        if frame := audio.extract_cover(media.path, media_folder()):
            media.cover = frame
            if cover_base64 := media.cover_base64():
                return [cover_base64]
    return []


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


# The stage names the pipeline emits with each progress update. They are a **protocol** with
# `web/app.js`, which matches them to draw the Cook bar: nothing on disk is keyed this way, so
# they moved to English together with the frontend that reads them, exactly like the keys of
# `Library.list_`. `cli.py` ignores the name and only prints the message.
STAGES = ("acquisition", "audio", "transcription", "extraction", "translation",
          "conversion", "done")


def process(
    media: acquire.Media,
    on_progress: Progress = _silence,
    asr_backend: str = "auto",
    asr_model: str = asr.DEFAULT_MODEL,
    audio_language: str | None = asr.DEFAULT_LANGUAGE,
    llm_model: str | None = None,
    ollama_url: str = extract.DEFAULT_OLLAMA_URL,
    skip_audio: bool = False,
    tables: Tables | None = None,
    # The two output axes. `audio_language` above is another thing entirely: it is the language
    # SPOKEN in the reel, which Whisper needs. A Japanese reel can perfectly well produce an
    # Italian recipe — keeping them apart avoids confusing the input with the output.
    language: str = Language.IT,
    system: str = System.METRIC,
) -> Outcome:
    """Takes an already acquired `Media` all the way to a normalised `Recipe`."""
    warnings: list[str] = []
    t = tables or load_tables()

    transcript = None
    if not skip_audio:
        transcript = _transcribe_if_possible(
            media, asr_backend, asr_model, audio_language, on_progress, warnings,
            code_of(language),
        )

    transcript_text = transcript.text if transcript else ""
    if not media.caption.strip() and not transcript_text.strip():
        return Outcome(
            media=media,
            warnings=warnings,
            error=text(language, "nothing_to_analyse"),
        )

    if media.author_comments:
        on_progress("extraction", text(language, "author_comments",
                                       how_many=len(media.author_comments)))

    on_progress("extraction", text(language, "reconstructing"))
    extraction = extract.extract_draft(
        caption=media.caption,
        transcript=transcript_text,
        title=media.title,
        model=llm_model,
        url=ollama_url,
        author_comments=media.author_comments,
        language=code_of(language),
    )

    if not extraction.is_a_recipe:
        raise NotARecipe(text(language, "not_a_recipe", label=media.label()))

    # The translation pass, and only when it is actually needed. The decision is made in code
    # from the **material**, not by asking the model whether it followed its own instruction:
    # an Italian reel asked for in Italian never reaches this line, which is the common case
    # and the one that must not get slower.
    draft = extraction.draft
    if extract.needs_translation(f"{media.caption or ''}\n{transcript_text or ''}",
                                 draft, code_of(language)):
        on_progress("translation", text(language, "translating"))
        draft = extract.translate_draft(
            draft, language=code_of(language), model=llm_model, url=ollama_url,
        )

    on_progress("conversion", text(language, "converting"))
    recipe = from_draft(
        draft,
        source=Source.now(
            url=media.url,
            author=media.author,
            platform=media.platform,
            original_title=media.title,
        ),
        images=_cover(media),
        transcript=transcript_text or None,
        tables=t,
        language=language,
        system=system,
    )

    if not media.caption.strip():
        warnings.append(text(language, "speech_only"))
    if not transcript_text.strip():
        warnings.append(text(language, "caption_only"))

    on_progress("done", text(language, "ready_recipe", title=recipe.title))
    return Outcome(
        recipe=recipe,
        media=media,
        transcript=transcript,
        model=extraction.model,
        warnings=warnings,
    )


def from_url(url: str, on_progress: Progress = _silence,
             cookies_from_browser: str | None = None, **kwargs) -> Outcome:
    """The main road: you paste a link and press Cook."""
    language = kwargs.get("language", Language.IT)
    on_progress("acquisition", text(language, "downloading"))
    media = acquire.from_url(url, media_folder(), cookies_from_browser=cookies_from_browser)
    on_progress("acquisition", text(language, "downloaded", label=media.label()))
    return process(media, on_progress, **kwargs)


def from_file(path: Path | str, caption: str = "",
              on_progress: Progress = _silence, **kwargs) -> Outcome:
    """For reels already saved on disk, or when downloading is not possible."""
    on_progress("acquisition", text(kwargs.get("language", Language.IT), "reading_file"))
    media = acquire.from_file(path, caption=caption)
    return process(media, on_progress, **kwargs)


def check_environment(ollama_url: str = extract.DEFAULT_OLLAMA_URL) -> dict:
    """The state of the external components, for the CLI's and the interface's diagnostics.

    It exists to give useful messages *before* something fails halfway through a job.
    """
    backend = asr.available_backends()
    models = extract.available_models(ollama_url)
    ollama_ok = extract.ollama_up(ollama_url)
    return {
        "ffmpeg": audio.ffmpeg_available(),
        "yt_dlp": acquire.ytdlp_available(),
        "asr_backend": backend,
        "asr_ready": bool(backend),
        "ollama_up": ollama_ok,
        "llm_models": models,
        # Which model to suggest to someone who has none. It comes from here and is not written
        # into the page, because a string duplicated in the frontend ages on its own: it was
        # recommending the 7b while the add-on installed the 14b.
        "recommended_model": extract.PREFERRED_MODELS[0],
        "llm_ready": ollama_ok and bool(models),
        # The minimum needed to process anything: with no LLM nothing gets structured.
        "ready": ollama_ok and bool(models),
    }
