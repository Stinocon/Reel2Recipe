"""Test del file di cookie.

Copre un ramo che sulla macchina di sviluppo non si percorre mai — lì i cookie si prendono
dal browser — ma che è l'unica via possibile dentro un container. Un guasto qui si
manifesterebbe come "Instagram non si scarica", cioè come la cosa più difficile da
diagnosticare in tutto il progetto.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reel2recipe.acquire import AcquisitionError, _ytdlp_options


def test_senza_variabile_nessun_cookie(monkeypatch, tmp_path):
    monkeypatch.delenv("R2R_COOKIES", raising=False)
    opzioni = _ytdlp_options(tmp_path, cookies_from_browser=None)
    assert "cookiefile" not in opzioni
    assert "cookiesfrombrowser" not in opzioni


def test_file_di_cookie_dalla_variabile(monkeypatch, tmp_path):
    file = tmp_path / "cookies.txt"
    file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("R2R_COOKIES", str(file))
    usato = Path(_ytdlp_options(tmp_path, cookies_from_browser=None)["cookiefile"])
    assert usato.is_file() and usato.read_text() == file.read_text()


def test_il_file_dell_utente_non_viene_mai_toccato(monkeypatch, tmp_path):
    """yt-dlp riscrive il cookie jar uscendo dal blocco `with`. Su `/share` dell'add-on, che
    e montato in sola lettura, un download RIUSCITO fallirebbe all'uscita e il messaggio
    direbbe «impossibile scaricare»: la diagnosi peggiore, perche indica la fase sbagliata.
    E comunque un file prestato non si modifica."""
    file = tmp_path / "cookies.txt"
    file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("R2R_COOKIES", str(file))

    usato = Path(_ytdlp_options(tmp_path, cookies_from_browser=None)["cookiefile"])
    assert usato != file, "si sta usando il file dell'utente invece di una copia"

    # Simula la riscrittura di yt-dlp: deve finire sulla copia, non sull'originale.
    usato.write_text("modificato da yt-dlp\n")
    assert file.read_text() == "# Netscape HTTP Cookie File\n"


def test_una_sorgente_illeggibile_lo_dice(monkeypatch, tmp_path):
    """Se la copia non riesce, l'errore deve nominare i cookie e non il download.

    Il fallimento si simula sostituendo `copyfile` invece di togliere i permessi: `chmod 000`
    non ferma root, e root e' esattamente l'utente dentro il container dell'add-on, cioe'
    l'ambiente per cui questa funzione esiste. Un test che si inverte proprio la' non serve.
    """
    file = tmp_path / "cookies.txt"
    file.write_text("x")
    monkeypatch.setenv("R2R_COOKIES", str(file))
    monkeypatch.setattr(
        "reel2recipe.acquire.shutil.copyfile",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disco pieno")),
    )
    with pytest.raises(AcquisitionError, match="cookie"):
        _ytdlp_options(tmp_path, cookies_from_browser=None)


def test_il_browser_ha_la_precedenza(monkeypatch, tmp_path):
    """Il browser è la scelta della singola esecuzione, il file il ripiego della macchina."""
    file = tmp_path / "cookies.txt"
    file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("R2R_COOKIES", str(file))
    opzioni = _ytdlp_options(tmp_path, cookies_from_browser="chrome")
    assert opzioni["cookiesfrombrowser"] == ("chrome",)
    assert "cookiefile" not in opzioni


def test_percorso_inesistente_fallisce_subito(monkeypatch, tmp_path):
    """Meglio un errore che nomina la causa che un download che fallisce per «login richiesto»."""
    monkeypatch.setenv("R2R_COOKIES", str(tmp_path / "non-esiste.txt"))
    with pytest.raises(AcquisitionError, match="R2R_COOKIES"):
        _ytdlp_options(tmp_path, cookies_from_browser=None)


def test_la_copia_dei_cookie_e_privata_e_imprevedibile(monkeypatch, tmp_path):
    """Dentro ci sono credenziali di sessione. Su una /tmp condivisa una copia a 0644 le
    pubblica a ogni utente locale, e un nome derivato dal PID e' indovinabile — quindi
    pre-piazzabile come collegamento simbolico, che `copyfile` seguirebbe."""
    import os
    import stat

    file = tmp_path / "cookies.txt"
    file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("R2R_COOKIES", str(file))

    prima = Path(_ytdlp_options(tmp_path, cookies_from_browser=None)["cookiefile"])
    dopo = Path(_ytdlp_options(tmp_path, cookies_from_browser=None)["cookiefile"])

    modo = stat.S_IMODE(os.stat(prima).st_mode)
    assert modo == 0o600, f"la copia e' leggibile da altri: {oct(modo)}"
    assert prima != dopo, "due estrazioni in parallelo condividerebbero lo stesso file"
    for p in (prima, dopo):
        p.unlink(missing_ok=True)


def test_il_batch_non_rilavora_l_audio_che_ha_estratto_lui(tmp_path):
    """`workspace/media/` contiene i video scaricati E i `.16k.wav` che ne estraiamo noi.
    Senza filtro, `r2r batch` puntato li lavora ogni reel due volte: la seconda dal solo
    audio, che non ha didascalia ne URL, quindi non si deduplica e finisce in libreria come
    una ricetta piu povera. Verificato sul campo, con otto duplicati da ripulire a mano."""
    from reel2recipe.acquire import from_folder

    (tmp_path / "reel.mp4").write_bytes(b"x")
    (tmp_path / "reel.16k.wav").write_bytes(b"x")     # derivato: da saltare
    (tmp_path / "podcast.wav").write_bytes(b"x")      # audio vero dell'utente: da tenere

    nomi = sorted(m.path.name for m in from_folder(tmp_path))
    assert nomi == ["podcast.wav", "reel.mp4"]
