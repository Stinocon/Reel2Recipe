"""acquire.py — how a reel enters the pipeline.

Three routes, one normalised result (`Media`):
  - **URL**    the reel is downloaded with yt-dlp, along with caption, author and cover
  - **file**   a video or audio already on disk, with the caption pasted in by hand
  - **folder** iterating over files, for batch mode

The caption is the most valuable source in the whole pipeline, not a garnish: a great many
cooking reels carry the complete recipe in the text of the post, and in that case the audio
transcription only confirms it. That is why it is always extracted, even when working from
a local file.

BOUNDARY: everything downloaded stays in `workspace/`, which is in `.gitignore`. Third-party
material is neither committed nor redistributed (see docs/legale.md). Captions and comments
are **data to analyse, never instructions to follow**: see `AGENTS.md §5`.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


class AcquisitionError(RuntimeError):
    """The media was not retrieved. The message has to say what to do, not only what failed."""


@dataclass
class Media:
    """A reel ready to be transcribed and analysed."""

    path: Path | None = None              # source video or audio
    caption: str = ""
    author_comments: list[str] = field(default_factory=list)  # see _author_comments
    author: str | None = None
    title: str | None = None
    url: str | None = None
    platform: str | None = None
    duration_s: float | None = None
    cover: Path | None = None             # preview image, when available
    extra: dict = field(default_factory=dict)

    @property
    def is_audio(self) -> bool:
        return self.path is not None and self.path.suffix.lower() in AUDIO_EXTENSIONS

    def cover_base64(self) -> str | None:
        """Cover as a base64 string, in the form Mela wants in `images`."""
        if not self.cover or not self.cover.is_file():
            return None
        return base64.b64encode(self.cover.read_bytes()).decode("ascii")

    def label(self) -> str:
        """How this reel is referred to in messages to the user."""
        return self.title or self.url or (self.path.name if self.path else "reel")


# --------------------------------------------------------------------------------------
# From a URL
# --------------------------------------------------------------------------------------


def _cookie_file() -> Path | None:
    """The Netscape-format cookie file named by `R2R_COOKIES`, if there is one.

    It exists for environments with no browser to take them from: inside a container — the
    Home Assistant add-on — `cookiesfrombrowser` has nothing to read, and without cookies
    Instagram refuses nearly everything. It lives in an environment variable rather than a
    parameter because it is a property of the machine, not of the individual request.

    If the variable is set but the file is not there, we fail immediately: carrying on
    silently would have the user misdiagnose the next error.
    """
    raw = os.environ.get("R2R_COOKIES", "").strip()
    if not raw:
        return None
    file = Path(raw).expanduser()
    if not file.is_file():
        raise AcquisitionError(
            f"R2R_COOKIES points at a file that does not exist: {file}\n"
            "Export the cookies in Netscape format from the browser you signed in with, "
            "or drop the variable to carry on without them."
        )

    # We work on a throwaway copy, never on the original. yt-dlp rewrites the cookie jar
    # when it leaves the `with` block (`close` → `save_cookies`), so:
    #   - on read-only storage — `/share` in the Home Assistant add-on is mounted that
    #     way — a SUCCESSFUL download would blow up on the way out, and the message would
    #     say "could not download": the worst possible diagnosis, because it names the
    #     wrong phase;
    #   - and in any case a file the user lends us is not modified behind their back.
    #
    # `mkstemp` and not a hand-built name: what is inside are Instagram session cookies,
    # that is, credentials. The file has to be born 0600 and with an unpredictable name —
    # on a shared /tmp a name derived from the PID is guessable, and `copyfile` would
    # follow a symlink planted there waiting for it. A fresh name on every call also
    # settles the race between two parallel extractions, which in the web interface run
    # in separate threads.
    descriptor, temporary = tempfile.mkstemp(prefix="r2r-cookies-", suffix=".txt")
    os.close(descriptor)
    copy = Path(temporary)
    try:
        shutil.copyfile(file, copy)
    except OSError as e:
        copy.unlink(missing_ok=True)
        raise AcquisitionError(f"Cannot copy the cookie file {file}: {e}") from e
    return copy


def _ytdlp_options(folder: Path, cookies_from_browser: str | None) -> dict:
    options = {
        "outtmpl": str(folder / "%(extractor)s-%(id)s.%(ext)s"),
        "format": "bv*+ba/b",
        "writeinfojson": True,
        "writethumbnail": True,
        # Comments are fetched for the author's own (see `_author_comments`): that is
        # often where the amounts end up when they did not fit in the caption. It costs
        # one extra request; without it yt-dlp returns a handful or none at all.
        "getcomments": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "retries": 3,
    }
    if cookies_from_browser:
        # Needed for private reels, or those that require being signed in.
        options["cookiesfrombrowser"] = (cookies_from_browser,)
    elif file := _cookie_file():
        # The browser wins when it was asked for explicitly: that is the choice of this
        # single run, whereas the file is the machine's permanent fallback.
        options["cookiefile"] = str(file)
    return options


def from_url(url: str, folder: Path | str, cookies_from_browser: str | None = None) -> Media:
    """Downloads a reel and its metadata.

    `cookies_from_browser` ("chrome", "safari", "firefox"…) is only for content that
    requires signing in: it is not automatic, it has to be asked for.
    """
    try:
        import yt_dlp
    except ImportError as e:  # pragma: no cover - dependency declared in pyproject
        raise AcquisitionError("yt-dlp is not installed. Run: uv sync") from e

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    # Outside the try: a configuration problem (a cookie file that is not there) has to
    # reach the user as it is, not disguised as "could not download the reel".
    options = _ytdlp_options(folder, cookies_from_browser)

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        message = str(e)
        if any(s in message.lower() for s in ("login", "private", "rate-limit")):
            raise AcquisitionError(
                f"Cannot download {url}: the content requires signing in, or Instagram is "
                "rate-limiting the requests. Try again with the browser's cookies "
                "(--cookies chrome) after signing in, or name a cookie file with "
                "R2R_COOKIES if there is no browser here."
            ) from e
        raise AcquisitionError(f"Cannot download {url}: {message}") from e
    finally:
        # The copy holds session credentials: it must not outlive the download, whether
        # it went well or badly.
        if temporary := options.get("cookiefile"):
            Path(temporary).unlink(missing_ok=True)

    if info is None:
        raise AcquisitionError(f"Nothing retrieved from {url}")
    if "entries" in info:  # a playlist: the first item is taken
        entries = [v for v in info["entries"] if v]
        if not entries:
            raise AcquisitionError(f"No video found in {url}")
        info = entries[0]

    return _media_from_info(info, folder, url)


def _media_from_info(info: dict, folder: Path, requested_url: str) -> Media:
    path = _downloaded_path(info, folder)
    return Media(
        path=path,
        # On Instagram the post's caption ends up in the `description` field.
        caption=(info.get("description") or "").strip(),
        author_comments=_author_comments(info),
        author=info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        title=(info.get("title") or "").strip() or None,
        url=info.get("webpage_url") or requested_url,
        platform=(info.get("extractor_key") or info.get("extractor") or "").lower() or None,
        duration_s=info.get("duration"),
        cover=_downloaded_cover(path),
        extra={"id": info.get("id")},
    )


def _author_comments(info: dict, most: int = 5, characters: int = 1500) -> list[str]:
    """The comments written by whoever published the reel.

    Authors often use the first comment for what did not fit in the caption: the amounts,
    a correction, a link to the full version. It is usually the comment they pin to the
    top. We cannot ask for "the pinned ones" though: for Instagram yt-dlp does not expose
    `is_pinned`, and a comment's fields are only author, text, date and likes. The workable
    criterion — and also the one with the most signal — is authorship.

    The other comments are left out deliberately. They are strangers' text: noise for the
    extraction, and extra surface for a hostile imperative aimed at the model (see
    "Confini di sicurezza" in docs/architettura.md). An author's comment is still
    third-party material and goes into the prompt inside its own delimiters, like the
    caption.
    """
    comments = info.get("comments")
    if not isinstance(comments, list):
        return []

    # On Instagram `channel` is the handle (amicojeko) and `uploader` the full name; in
    # comments `author` is the handle. Every available form is compared, IDs included.
    identities = {
        str(info.get(k)).strip().lower()
        for k in ("channel", "uploader", "uploader_id", "channel_id")
        if info.get(k)
    }
    if not identities:
        return []

    theirs = []
    for c in comments:
        if not isinstance(c, dict):
            continue
        signatures = {str(c.get(k)).strip().lower() for k in ("author", "author_id") if c.get(k)}
        if signatures & identities and (text := (c.get("text") or "").strip()):
            theirs.append(text[:characters])
        if len(theirs) >= most:
            break
    return theirs


def _downloaded_path(info: dict, folder: Path) -> Path | None:
    """The file yt-dlp actually wrote, with a few fallbacks when the field is missing."""
    for key in ("filepath", "_filename"):
        if (value := info.get(key)) and Path(value).is_file():
            return Path(value)
    for downloaded in info.get("requested_downloads") or []:
        if (value := downloaded.get("filepath")) and Path(value).is_file():
            return Path(value)
    identifier = info.get("id")
    if identifier:
        candidates = [
            p for p in folder.glob(f"*{identifier}*")
            if p.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if candidates:
            return max(candidates, key=lambda p: p.stat().st_size)
    return None


def _downloaded_cover(media_path: Path | None) -> Path | None:
    if not media_path:
        return None
    for extension in (".jpg", ".jpeg", ".webp", ".png"):
        candidate = media_path.with_suffix(extension)
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------------------
# From a file and from a folder
# --------------------------------------------------------------------------------------


def from_file(path: Path | str, caption: str = "", author: str | None = None,
              url: str | None = None) -> Media:
    """A video or audio already on disk. The caption, if there is one, has to be passed in
    by hand: it is the only way to recover it when the file did not come from a URL."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise AcquisitionError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise AcquisitionError(
            f"Unsupported format: {path.suffix}. "
            f"Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # If an earlier download's info.json sits next to the file, reuse its metadata.
    alongside = path.with_suffix(".info.json")
    if alongside.is_file():
        try:
            info = json.loads(alongside.read_text(encoding="utf-8"))
            caption = caption or (info.get("description") or "").strip()
            author = author or info.get("uploader")
            url = url or info.get("webpage_url")
        except (json.JSONDecodeError, OSError):
            pass   # optional metadata: a corrupt file must not stop the import

    return Media(
        path=path,
        caption=caption,
        author=author,
        title=path.stem,
        url=url,
        platform="file",
        cover=_downloaded_cover(path),
    )


def _is_derived_audio(path: Path) -> bool:
    """A `.16k.wav` we extracted ourselves (see `audio.extract_audio`), not a user's file.

    It sits next to the video it came from, so a folder already processed holds both.
    Without this check `r2r batch` processes every reel **twice**: once from the video,
    with its caption, and once from the audio alone — which has neither caption nor URL, so
    it does not deduplicate and lands in the library as a second, poorer recipe. It happens
    precisely when pointing batch at `workspace/media/`, which is where downloaded reels
    land.
    """
    return path.name.lower().endswith(".16k.wav")


def from_folder(folder: Path | str) -> list[Media]:
    """Every media file in a folder, alphabetically. For batch mode."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise AcquisitionError(f"Folder not found: {folder}")
    files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and not _is_derived_audio(p)
    )
    if not files:
        raise AcquisitionError(f"No video or audio in {folder}")
    return [from_file(p) for p in files]


def read_url_list(path: Path | str) -> list[str]:
    """One URL per line; blank lines and `#` comments are ignored."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [r.strip() for r in lines if r.strip() and not r.lstrip().startswith("#")]


def ytdlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return shutil.which("yt-dlp") is not None
