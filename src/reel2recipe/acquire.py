"""acquire.py — come il reel entra nella pipeline.

Tre strade, un solo risultato normalizzato (`Media`):
  - **URL**   il reel viene scaricato con yt-dlp, insieme a didascalia, autore e copertina
  - **file**  un video o un audio già sul disco, con didascalia incollata a mano
  - **cartella** iterazione sui file, per la modalità batch

La didascalia è la fonte più preziosa dell'intera pipeline, non un contorno: moltissimi
reel di cucina riportano la ricetta completa nel testo del post, e in quel caso la
trascrizione dell'audio serve solo a confermarla. Per questo viene sempre estratta, anche
quando si lavora su un file locale.

CONFINE: tutto ciò che viene scaricato resta in `workspace/`, che è in `.gitignore`.
Materiale di terzi non si committa e non si ridistribuisce (v. docs/legale.md).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ESTENSIONI_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ESTENSIONI_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
ESTENSIONI_SUPPORTATE = ESTENSIONI_VIDEO | ESTENSIONI_AUDIO


class ErroreAcquisizione(RuntimeError):
    """Il media non è stato recuperato. Il messaggio deve dire cosa fare, non solo cosa è fallito."""


@dataclass
class Media:
    """Un reel pronto per essere trascritto e analizzato."""

    percorso: Path | None = None          # video o audio sorgente
    didascalia: str = ""
    commenti_autore: list[str] = field(default_factory=list)  # v. _commenti_dell_autore
    autore: str | None = None
    titolo: str | None = None
    url: str | None = None
    piattaforma: str | None = None
    durata_s: float | None = None
    copertina: Path | None = None         # immagine di anteprima, se disponibile
    extra: dict = field(default_factory=dict)

    @property
    def e_audio(self) -> bool:
        return self.percorso is not None and self.percorso.suffix.lower() in ESTENSIONI_AUDIO

    def copertina_base64(self) -> str | None:
        """Copertina come stringa base64, nel formato che Mela vuole in `images`."""
        if not self.copertina or not self.copertina.is_file():
            return None
        return base64.b64encode(self.copertina.read_bytes()).decode("ascii")

    def etichetta(self) -> str:
        """Come ci si riferisce a questo reel nei messaggi all'utente."""
        return self.titolo or self.url or (self.percorso.name if self.percorso else "reel")


# --------------------------------------------------------------------------------------
# Da URL
# --------------------------------------------------------------------------------------


def _file_cookie() -> Path | None:
    """Il file di cookie in formato Netscape indicato da `R2R_COOKIES`, se c'è.

    Esiste per gli ambienti senza browser da cui pescarli: dentro un container — l'addon
    Home Assistant — `cookiesfrombrowser` non ha nulla da leggere, e senza cookie Instagram
    rifiuta quasi tutto. Sta in una variabile d'ambiente e non in un parametro perché è una
    proprietà della macchina, non della singola richiesta.

    Se la variabile è impostata ma il file non c'è si fallisce subito: proseguire in
    silenzio significherebbe far sbagliare l'utente sulla causa del prossimo errore.
    """
    percorso = os.environ.get("R2R_COOKIES", "").strip()
    if not percorso:
        return None
    file = Path(percorso).expanduser()
    if not file.is_file():
        raise ErroreAcquisizione(
            f"R2R_COOKIES punta a un file che non esiste: {file}\n"
            "Esporta i cookie in formato Netscape dal browser dove hai fatto l'accesso, "
            "oppure togli la variabile per procedere senza."
        )

    # Si lavora su una copia usa-e-getta, mai sull'originale. yt-dlp riscrive il cookie jar
    # quando esce dal blocco `with` (`close` → `save_cookies`), quindi:
    #   - su un supporto in sola lettura — `/share` dell'add-on Home Assistant è montato
    #     così — un download RIUSCITO esploderebbe all'uscita, e il messaggio direbbe
    #     "impossibile scaricare": la diagnosi peggiore possibile, perché indica la fase
    #     sbagliata;
    #   - e comunque un file che l'utente ci presta non si modifica a sua insaputa.
    #
    # `mkstemp` e non un nome composto a mano: dentro ci sono i cookie di sessione di
    # Instagram, cioè credenziali. Serve che il file nasca a 0600 e con un nome
    # imprevedibile — su una /tmp condivisa un nome derivato dal PID è indovinabile, e
    # `copyfile` seguirebbe un collegamento simbolico piazzato lì ad aspettarlo. Un nome
    # nuovo a ogni chiamata risolve anche la corsa fra due estrazioni in parallelo, che
    # nell'interfaccia web girano in thread distinti.
    descrittore, temporaneo = tempfile.mkstemp(prefix="r2r-cookies-", suffix=".txt")
    os.close(descrittore)
    copia = Path(temporaneo)
    try:
        shutil.copyfile(file, copia)
    except OSError as e:
        copia.unlink(missing_ok=True)
        raise ErroreAcquisizione(f"Non riesco a copiare il file dei cookie {file}: {e}") from e
    return copia


def _opzioni_ytdlp(cartella: Path, cookies_da_browser: str | None) -> dict:
    opzioni = {
        "outtmpl": str(cartella / "%(extractor)s-%(id)s.%(ext)s"),
        "format": "bv*+ba/b",
        "writeinfojson": True,
        "writethumbnail": True,
        # I commenti servono per quelli dell'autore (v. `_commenti_dell_autore`): spesso è
        # lì che finiscono le dosi che nella didascalia non ci stavano. Costa una richiesta
        # in più; senza, yt-dlp ne restituisce solo una manciata o nessuno.
        "getcomments": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "retries": 3,
    }
    if cookies_da_browser:
        # Serve per i reel privati o che richiedono di aver effettuato l'accesso.
        opzioni["cookiesfrombrowser"] = (cookies_da_browser,)
    elif file := _file_cookie():
        # Il browser vince se è stato chiesto esplicitamente: è la scelta della singola
        # esecuzione, mentre il file è il ripiego permanente della macchina.
        opzioni["cookiefile"] = str(file)
    return opzioni


def da_url(url: str, cartella: Path | str, cookies_da_browser: str | None = None) -> Media:
    """Scarica un reel e i suoi metadati.

    `cookies_da_browser` ("chrome", "safari", "firefox"…) serve solo per i contenuti che
    richiedono l'accesso: non è automatico, va chiesto esplicitamente.
    """
    try:
        import yt_dlp
    except ImportError as e:  # pragma: no cover - dipendenza dichiarata in pyproject
        raise ErroreAcquisizione(
            "yt-dlp non è installato. Esegui: uv sync"
        ) from e

    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)

    # Fuori dal try: un problema di configurazione (un file di cookie che non c'è) deve
    # arrivare all'utente com'è, non travestito da "impossibile scaricare il reel".
    opzioni = _opzioni_ytdlp(cartella, cookies_da_browser)

    try:
        with yt_dlp.YoutubeDL(opzioni) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        messaggio = str(e)
        if "login" in messaggio.lower() or "private" in messaggio.lower() or "rate-limit" in messaggio.lower():
            raise ErroreAcquisizione(
                f"Impossibile scaricare {url}: il contenuto richiede l'accesso oppure "
                "Instagram sta limitando le richieste. Riprova con i cookie del browser "
                "(--cookies chrome) dopo aver effettuato l'accesso, oppure indica un file "
                "di cookie con R2R_COOKIES se qui un browser non c'è."
            ) from e
        raise ErroreAcquisizione(f"Impossibile scaricare {url}: {messaggio}") from e
    finally:
        # La copia contiene credenziali di sessione: non deve sopravvivere al download,
        # né quando è andato bene né quando è fallito.
        if temporaneo := opzioni.get("cookiefile"):
            Path(temporaneo).unlink(missing_ok=True)

    if info is None:
        raise ErroreAcquisizione(f"Nessun contenuto recuperato da {url}")
    if "entries" in info:  # una playlist: si prende il primo elemento
        voci = [v for v in info["entries"] if v]
        if not voci:
            raise ErroreAcquisizione(f"Nessun video trovato in {url}")
        info = voci[0]

    return _media_da_info(info, cartella, url)


def _media_da_info(info: dict, cartella: Path, url_richiesto: str) -> Media:
    percorso = _percorso_scaricato(info, cartella)
    return Media(
        percorso=percorso,
        # Su Instagram la didascalia del post finisce nel campo `description`.
        didascalia=(info.get("description") or "").strip(),
        commenti_autore=_commenti_dell_autore(info),
        autore=info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        titolo=(info.get("title") or "").strip() or None,
        url=info.get("webpage_url") or url_richiesto,
        piattaforma=(info.get("extractor_key") or info.get("extractor") or "").lower() or None,
        durata_s=info.get("duration"),
        copertina=_copertina_scaricata(percorso),
        extra={"id": info.get("id")},
    )


def _commenti_dell_autore(info: dict, massimo: int = 5, caratteri: int = 1500) -> list[str]:
    """I commenti scritti da chi ha pubblicato il reel.

    Gli autori usano spesso il primo commento per quello che non è entrato nella didascalia:
    le dosi, una correzione, il link alla versione completa. È il commento che di solito
    fissano in cima. Non possiamo però chiedere "quelli fissati": per Instagram yt-dlp non
    espone `is_pinned`, i campi di un commento sono solo autore, testo, data e like. Il
    criterio praticabile — ed è anche quello con più segnale — è la paternità.

    Gli altri commenti restano fuori di proposito. Sono testo di sconosciuti: rumore per
    l'estrazione e superficie in più per un imperativo ostile rivolto al modello (v. "Confini
    di sicurezza" in docs/architettura.md). Un commento dell'autore resta comunque materiale di
    terzi e va nel prompt dentro i suoi delimitatori, come la didascalia.
    """
    commenti = info.get("comments")
    if not isinstance(commenti, list):
        return []

    # Su Instagram `channel` è l'handle (amicojeko) e `uploader` il nome esteso; nei commenti
    # `author` è l'handle. Si confrontano tutte le forme disponibili, ID compresi.
    identita = {
        str(info.get(k)).strip().lower()
        for k in ("channel", "uploader", "uploader_id", "channel_id")
        if info.get(k)
    }
    if not identita:
        return []

    suoi = []
    for c in commenti:
        if not isinstance(c, dict):
            continue
        firme = {str(c.get(k)).strip().lower() for k in ("author", "author_id") if c.get(k)}
        if firme & identita and (testo := (c.get("text") or "").strip()):
            suoi.append(testo[:caratteri])
        if len(suoi) >= massimo:
            break
    return suoi


def _percorso_scaricato(info: dict, cartella: Path) -> Path | None:
    """Il file effettivamente scritto da yt-dlp, con qualche ripiego se il campo manca."""
    for chiave in ("filepath", "_filename"):
        if (valore := info.get(chiave)) and Path(valore).is_file():
            return Path(valore)
    for scaricato in info.get("requested_downloads") or []:
        if (valore := scaricato.get("filepath")) and Path(valore).is_file():
            return Path(valore)
    identificativo = info.get("id")
    if identificativo:
        candidati = [
            p for p in cartella.glob(f"*{identificativo}*")
            if p.suffix.lower() in ESTENSIONI_SUPPORTATE
        ]
        if candidati:
            return max(candidati, key=lambda p: p.stat().st_size)
    return None


def _copertina_scaricata(percorso_media: Path | None) -> Path | None:
    if not percorso_media:
        return None
    for estensione in (".jpg", ".jpeg", ".webp", ".png"):
        candidato = percorso_media.with_suffix(estensione)
        if candidato.is_file():
            return candidato
    return None


# --------------------------------------------------------------------------------------
# Da file e da cartella
# --------------------------------------------------------------------------------------


def da_file(percorso: Path | str, didascalia: str = "", autore: str | None = None,
            url: str | None = None) -> Media:
    """Un video o un audio già sul disco. La didascalia, se c'è, va passata a mano:
    è l'unico modo di recuperarla quando il file non arriva da un URL."""
    percorso = Path(percorso).expanduser().resolve()
    if not percorso.is_file():
        raise ErroreAcquisizione(f"File non trovato: {percorso}")
    if percorso.suffix.lower() not in ESTENSIONI_SUPPORTATE:
        raise ErroreAcquisizione(
            f"Formato non supportato: {percorso.suffix}. "
            f"Accettati: {', '.join(sorted(ESTENSIONI_SUPPORTATE))}"
        )

    # Se accanto al file c'è l'info.json di un download precedente, riusiamone i metadati.
    accanto = percorso.with_suffix(".info.json")
    if accanto.is_file():
        try:
            info = json.loads(accanto.read_text(encoding="utf-8"))
            didascalia = didascalia or (info.get("description") or "").strip()
            autore = autore or info.get("uploader")
            url = url or info.get("webpage_url")
        except (json.JSONDecodeError, OSError):
            pass   # metadati opzionali: un file corrotto non deve fermare l'importazione

    return Media(
        percorso=percorso,
        didascalia=didascalia,
        autore=autore,
        titolo=percorso.stem,
        url=url,
        piattaforma="file",
        copertina=_copertina_scaricata(percorso),
    )


def _e_audio_derivato(percorso: Path) -> bool:
    """Un `.16k.wav` estratto da noi (v. `audio.estrai_audio`), non un file dell'utente.

    Sta accanto al video da cui viene, quindi una cartella già lavorata contiene entrambi.
    Senza questo controllo `r2r batch` lavora ogni reel **due volte**: una dal video, con la
    sua didascalia, e una dall'audio soltanto — che non ha né didascalia né URL, quindi non
    si deduplica e finisce in libreria come una seconda ricetta più povera. Succede proprio
    puntando batch su `workspace/media/`, che è dove i reel scaricati atterrano.
    """
    return percorso.name.lower().endswith(".16k.wav")


def da_cartella(cartella: Path | str) -> list[Media]:
    """Tutti i media di una cartella, in ordine alfabetico. Per la modalità batch."""
    cartella = Path(cartella).expanduser().resolve()
    if not cartella.is_dir():
        raise ErroreAcquisizione(f"Cartella non trovata: {cartella}")
    file = sorted(
        p for p in cartella.iterdir()
        if p.is_file() and p.suffix.lower() in ESTENSIONI_SUPPORTATE
        and not _e_audio_derivato(p)
    )
    if not file:
        raise ErroreAcquisizione(f"Nessun video o audio in {cartella}")
    return [da_file(p) for p in file]


def leggi_elenco_url(percorso: Path | str) -> list[str]:
    """Un URL per riga; righe vuote e commenti con `#` vengono ignorati."""
    righe = Path(percorso).read_text(encoding="utf-8").splitlines()
    return [r.strip() for r in righe if r.strip() and not r.lstrip().startswith("#")]


def ytdlp_disponibile() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return shutil.which("yt-dlp") is not None
