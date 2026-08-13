"""Tests for the cookie file.

It covers a branch that is never taken on a development machine — there the cookies come from
the browser — but which is the only possible route inside a container. A failure here would
show up as "Instagram will not download", i.e. as the hardest thing to diagnose in the whole
project.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reel2recipe.acquire import AcquisitionError, _ytdlp_options


def test_no_variable_means_no_cookies(monkeypatch, tmp_path):
    monkeypatch.delenv("R2R_COOKIES", raising=False)
    options = _ytdlp_options(tmp_path, cookies_from_browser=None)
    assert "cookiefile" not in options
    assert "cookiesfrombrowser" not in options


def test_cookie_file_from_the_variable(monkeypatch, tmp_path):
    file = tmp_path / "cookies.txt"
    file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("R2R_COOKIES", str(file))
    used = Path(_ytdlp_options(tmp_path, cookies_from_browser=None)["cookiefile"])
    assert used.is_file() and used.read_text() == file.read_text()


def test_the_user_file_is_never_touched(monkeypatch, tmp_path):
    """yt-dlp rewrites the cookie jar on leaving the `with` block. On the add-on's `/share`,
    which is mounted read-only, a SUCCESSFUL download would fail on the way out and the
    message would say "could not download": the worst possible diagnosis, because it points
    at the wrong stage. And in any case a borrowed file is not modified."""
    file = tmp_path / "cookies.txt"
    file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("R2R_COOKIES", str(file))

    used = Path(_ytdlp_options(tmp_path, cookies_from_browser=None)["cookiefile"])
    assert used != file, "the user's file is being used instead of a copy"

    # Simulates yt-dlp's rewrite: it has to land on the copy, not on the original.
    used.write_text("modified by yt-dlp\n")
    assert file.read_text() == "# Netscape HTTP Cookie File\n"


def test_an_unreadable_source_says_so(monkeypatch, tmp_path):
    """If the copy fails, the error has to name the cookies and not the download.

    The failure is simulated by replacing `copyfile` rather than by removing permissions:
    `chmod 000` does not stop root, and root is exactly the user inside the add-on's
    container, i.e. the environment this function exists for. A test that inverts itself
    precisely there is of no use.
    """
    file = tmp_path / "cookies.txt"
    file.write_text("x")
    monkeypatch.setenv("R2R_COOKIES", str(file))
    monkeypatch.setattr(
        "reel2recipe.acquire.shutil.copyfile",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(AcquisitionError, match="cookie"):
        _ytdlp_options(tmp_path, cookies_from_browser=None)


def test_the_browser_takes_precedence(monkeypatch, tmp_path):
    """The browser is the choice of the single run, the file is the machine's fallback."""
    file = tmp_path / "cookies.txt"
    file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("R2R_COOKIES", str(file))
    options = _ytdlp_options(tmp_path, cookies_from_browser="chrome")
    assert options["cookiesfrombrowser"] == ("chrome",)
    assert "cookiefile" not in options


def test_a_missing_path_fails_immediately(monkeypatch, tmp_path):
    """Better an error that names the cause than a download failing on "login required"."""
    monkeypatch.setenv("R2R_COOKIES", str(tmp_path / "non-esiste.txt"))
    with pytest.raises(AcquisitionError, match="R2R_COOKIES"):
        _ytdlp_options(tmp_path, cookies_from_browser=None)


def test_the_cookie_copy_is_private_and_unpredictable(monkeypatch, tmp_path):
    """It holds session credentials. On a shared /tmp a copy at 0644 publishes them to every
    local user, and a name derived from the PID is guessable — hence pre-placeable as a
    symbolic link, which `copyfile` would follow."""
    import os
    import stat

    file = tmp_path / "cookies.txt"
    file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("R2R_COOKIES", str(file))

    first = Path(_ytdlp_options(tmp_path, cookies_from_browser=None)["cookiefile"])
    second = Path(_ytdlp_options(tmp_path, cookies_from_browser=None)["cookiefile"])

    mode = stat.S_IMODE(os.stat(first).st_mode)
    assert mode == 0o600, f"the copy is readable by others: {oct(mode)}"
    assert first != second, "two parallel extractions would share the same file"
    for p in (first, second):
        p.unlink(missing_ok=True)


def test_batch_does_not_reprocess_the_audio_it_extracted_itself(tmp_path):
    """`workspace/media/` holds the downloaded videos AND the `.16k.wav` files we extract from
    them. Without a filter, `r2r batch` pointed there processes every reel twice: the second
    time from the audio alone, which has neither caption nor URL, so it does not deduplicate
    and lands in the library as a poorer recipe. Seen in the field, with eight duplicates to
    clean up by hand."""
    from reel2recipe.acquire import from_folder

    (tmp_path / "reel.mp4").write_bytes(b"x")
    (tmp_path / "reel.16k.wav").write_bytes(b"x")     # derived: to be skipped
    (tmp_path / "podcast.wav").write_bytes(b"x")      # the user's real audio: to be kept

    names = sorted(m.path.name for m in from_folder(tmp_path))
    assert names == ["podcast.wav", "reel.mp4"]
