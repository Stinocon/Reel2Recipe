"""pipeline.py — la catena completa, da un link a una ricetta.

    URL o file  →  acquire  →  audio  →  asr  →  extract  →  recipe  →  Ricetta

Vive qui e non nella CLI perché la usano in due: il comando da terminale e l'interfaccia
web. Una sola implementazione, un solo posto dove correggere le cose.

Ogni fase riporta il proprio avanzamento tramite `su_avanzamento`, così la barra "Cook"
della pagina può raccontare cosa sta succedendo invece di mostrare una rotellina muta.

Principio di robustezza: **la pipeline degrada, non si ferma.** Se l'audio manca o la
trascrizione fallisce, si prosegue con la sola didascalia e lo si dichiara. Moltissimi
reel di cucina hanno la ricetta completa nel testo del post: rinunciare per un problema
audio significherebbe perdere una ricetta recuperabile.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import acquire, asr, audio, extract
from .percorsi import cartella_media
from .recipe import Fonte, Ricetta, da_bozza
from .units import Lingua, Sistema, Tabelle, carica_tabelle, sigla

Avanzamento = Callable[[str, str], None]   # (fase, messaggio)


def _silenzio(fase: str, messaggio: str) -> None:
    pass


@dataclass
class Esito:
    """Il risultato di una lavorazione, con la traccia di come ci si è arrivati."""

    ricetta: Ricetta | None = None
    media: acquire.Media | None = None
    trascrizione: asr.Trascrizione | None = None
    modello: str | None = None
    avvertenze: list[str] = field(default_factory=list)
    errore: str | None = None

    @property
    def riuscito(self) -> bool:
        return self.ricetta is not None


class NonEUnaRicetta(RuntimeError):
    """Il contenuto analizzato non è una ricetta di cucina."""


# --------------------------------------------------------------------------------------
# Fasi
# --------------------------------------------------------------------------------------


def _trascrivi_se_possibile(
    media: acquire.Media,
    backend: str,
    modello_asr: str,
    lingua_audio: str | None,
    su_avanzamento: Avanzamento,
    avvertenze: list[str],
) -> asr.Trascrizione | None:
    """Estrae l'audio e lo trascrive. Ogni fallimento diventa un'avvertenza, non un'eccezione:
    la didascalia da sola può bastare."""
    if media.percorso is None:
        avvertenze.append("Nessun file multimediale: analizzata la sola didascalia.")
        return None

    try:
        if media.e_audio:
            percorso_audio = media.percorso
        else:
            su_avanzamento("audio", "Estrazione della traccia audio…")
            percorso_audio = audio.estrai_audio(media.percorso, cartella_media())
    except audio.ErroreAudio as e:
        avvertenze.append(f"Audio non estratto ({e}). Si procede con la sola didascalia.")
        return None

    try:
        su_avanzamento("trascrizione", "Trascrizione del parlato in corso…")
        trascrizione = asr.trascrivi(percorso_audio, lingua=lingua_audio,
                                     modello=modello_asr, backend=backend)
        if not trascrizione:
            avvertenze.append("La trascrizione non ha prodotto testo: forse il reel non ha parlato.")
            return None
        su_avanzamento("trascrizione", f"Trascritti {len(trascrizione.testo)} caratteri "
                                       f"({trascrizione.backend}).")
        return trascrizione
    except asr.ErroreTrascrizione as e:
        avvertenze.append(f"Trascrizione non riuscita ({e}). Si procede con la sola didascalia.")
        return None


def _copertina(media: acquire.Media) -> list[str]:
    """Un'immagine di copertina per la ricetta, se ottenibile. Non è essenziale:
    un fallimento qui non deve costare una ricetta."""
    if base64_copertina := media.copertina_base64():
        return [base64_copertina]
    if media.percorso and not media.e_audio:
        if fotogramma := audio.estrai_copertina(media.percorso, cartella_media()):
            media.copertina = fotogramma
            if base64_copertina := media.copertina_base64():
                return [base64_copertina]
    return []


# --------------------------------------------------------------------------------------
# Punto d'ingresso
# --------------------------------------------------------------------------------------


def lavora(
    media: acquire.Media,
    su_avanzamento: Avanzamento = _silenzio,
    backend_asr: str = "auto",
    modello_asr: str = asr.MODELLO_PREDEFINITO,
    lingua_audio: str | None = asr.LINGUA_PREDEFINITA,
    modello_llm: str | None = None,
    url_ollama: str = extract.URL_OLLAMA_PREDEFINITO,
    salta_audio: bool = False,
    tabelle: Tabelle | None = None,
    # I due assi di uscita. `lingua_audio` sopra è un'altra cosa: è la lingua PARLATA nel
    # reel, che serve a Whisper. Un reel giapponese può benissimo produrre una ricetta in
    # italiano — tenerli separati evita di confondere l'ingresso con l'uscita.
    lingua: str = Lingua.IT,
    sistema: str = Sistema.METRICO,
) -> Esito:
    """Porta un `Media` già acquisito fino alla `Ricetta` normalizzata."""
    avvertenze: list[str] = []
    t = tabelle or carica_tabelle()

    trascrizione = None
    if not salta_audio:
        trascrizione = _trascrivi_se_possibile(
            media, backend_asr, modello_asr, lingua_audio, su_avanzamento, avvertenze
        )

    testo_trascrizione = trascrizione.testo if trascrizione else ""
    if not media.didascalia.strip() and not testo_trascrizione.strip():
        return Esito(
            media=media,
            avvertenze=avvertenze,
            errore="Non c'è nulla da analizzare: né didascalia né parlato trascrivibile.",
        )

    if media.commenti_autore:
        su_avanzamento("estrazione", f"Trovati {len(media.commenti_autore)} commenti "
                                     f"dell'autore: spesso contengono le dosi mancanti.")

    su_avanzamento("estrazione", "Il modello locale sta ricostruendo la ricetta…")
    esito_estrazione = extract.estrai_bozza(
        didascalia=media.didascalia,
        trascrizione=testo_trascrizione,
        titolo=media.titolo,
        modello=modello_llm,
        url=url_ollama,
        commenti_autore=media.commenti_autore,
        lingua=sigla(lingua),
    )

    if not esito_estrazione.e_una_ricetta:
        raise NonEUnaRicetta(
            f"«{media.etichetta()}» non sembra contenere una ricetta di cucina."
        )

    su_avanzamento("conversione", "Conversione delle quantità con le tabelle…")
    ricetta = da_bozza(
        esito_estrazione.bozza,
        fonte=Fonte.adesso(
            url=media.url,
            autore=media.autore,
            piattaforma=media.piattaforma,
            titolo_originale=media.titolo,
        ),
        immagini=_copertina(media),
        trascrizione=testo_trascrizione or None,
        tabelle=t,
        lingua=lingua,
        sistema=sistema,
    )

    if not media.didascalia.strip():
        avvertenze.append("Ricetta ricavata dal solo parlato: verifica le quantità.")
    if not testo_trascrizione.strip():
        avvertenze.append("Ricetta ricavata dalla sola didascalia: il parlato non è stato letto.")

    su_avanzamento("fatto", f"Pronta: «{ricetta.titolo}».")
    return Esito(
        ricetta=ricetta,
        media=media,
        trascrizione=trascrizione,
        modello=esito_estrazione.modello,
        avvertenze=avvertenze,
    )


def da_url(url: str, su_avanzamento: Avanzamento = _silenzio,
           cookies_da_browser: str | None = None, **kwargs) -> Esito:
    """La strada principale: si incolla un link e si preme Cook."""
    su_avanzamento("acquisizione", "Scaricamento del reel…")
    media = acquire.da_url(url, cartella_media(), cookies_da_browser=cookies_da_browser)
    su_avanzamento("acquisizione", f"Scaricato: {media.etichetta()}")
    return lavora(media, su_avanzamento, **kwargs)


def da_file(percorso: Path | str, didascalia: str = "",
            su_avanzamento: Avanzamento = _silenzio, **kwargs) -> Esito:
    """Per i reel già salvati sul disco, o quando lo scaricamento non è possibile."""
    su_avanzamento("acquisizione", "Lettura del file…")
    media = acquire.da_file(percorso, didascalia=didascalia)
    return lavora(media, su_avanzamento, **kwargs)


def controlla_ambiente(url_ollama: str = extract.URL_OLLAMA_PREDEFINITO) -> dict:
    """Stato dei componenti esterni, per la diagnostica di CLI e interfaccia.

    Serve a dare messaggi utili *prima* che qualcosa fallisca a metà lavorazione.
    """
    backend = asr.backend_disponibili()
    modelli = extract.modelli_disponibili(url_ollama)
    ollama_ok = extract.ollama_attivo(url_ollama)
    return {
        "ffmpeg": audio.ffmpeg_disponibile(),
        "yt_dlp": acquire.ytdlp_disponibile(),
        "asr_backend": backend,
        "asr_pronto": bool(backend),
        "ollama_attivo": ollama_ok,
        "modelli_llm": modelli,
        # Quale modello suggerire a chi non ne ha nessuno. Viene da qui e non è scritto nella
        # pagina, perché una stringa duplicata nel frontend invecchia da sola: consigliava il
        # 7b mentre l'add-on installava il 14b.
        "modello_consigliato": extract.MODELLI_PREFERITI[0],
        "llm_pronto": ollama_ok and bool(modelli),
        # Il minimo per poter lavorare qualcosa: senza LLM non si struttura nulla.
        "pronto": ollama_ok and bool(modelli),
    }
