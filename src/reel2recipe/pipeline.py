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
from .paths import media_folder
from .recipe import Fonte, Ricetta, da_bozza
from .units import Catalogo, Lingua, Sistema, Tabelle, carica_tabelle, sigla, testo_da

Avanzamento = Callable[[str, str], None]   # (fase, messaggio)


# Ciò che la pipeline racconta mentre lavora: avanzamento e avvertenze.
#
# Seguono la lingua **della ricetta**, non quella dei bottoni della pagina. Sono frasi che
# parlano della lavorazione di quella ricetta e finiscono accanto alle `lacune`, che nella
# lingua della ricetta ci stanno già perché vengono salvate con lei: farle divergere
# produrrebbe una scheda mezza in una lingua e mezza nell'altra. Nell'uso normale i due
# valori coincidono comunque, perché la lingua della ricetta segue quella dell'interfaccia.
TESTI: Catalogo = {
    "it": {
        "scaricamento": "Scaricamento del reel…",
        "scaricato": "Scaricato: {etichetta}",
        "lettura_file": "Lettura del file…",
        "estrazione_audio": "Estrazione della traccia audio…",
        "trascrizione_in_corso": "Trascrizione del parlato in corso…",
        "trascritto": "Trascritti {caratteri} caratteri ({backend}).",
        "ricostruzione": "Il modello locale sta ricostruendo la ricetta…",
        "commenti_autore": ("Trovati {quanti} commenti dell'autore: spesso contengono le "
                            "dosi mancanti."),
        "conversione": "Conversione delle quantità con le tabelle…",
        "pronta": "Pronta: «{titolo}».",
        "senza_media": "Nessun file multimediale: analizzata la sola didascalia.",
        "audio_fallito": "Audio non estratto ({dettaglio}). Si procede con la sola didascalia.",
        "trascrizione_vuota": ("La trascrizione non ha prodotto testo: forse il reel non ha "
                               "parlato."),
        "trascrizione_fallita": ("Trascrizione non riuscita ({dettaglio}). Si procede con la "
                                 "sola didascalia."),
        "solo_parlato": "Ricetta ricavata dal solo parlato: verifica le quantità.",
        "solo_didascalia": ("Ricetta ricavata dalla sola didascalia: il parlato non è stato "
                            "letto."),
        "niente_da_analizzare": ("Non c'è nulla da analizzare: né didascalia né parlato "
                                 "trascrivibile."),
        "non_una_ricetta": "«{etichetta}» non sembra contenere una ricetta di cucina.",
    },
    "en": {
        "scaricamento": "Downloading the reel…",
        "scaricato": "Downloaded: {etichetta}",
        "lettura_file": "Reading the file…",
        "estrazione_audio": "Extracting the audio track…",
        "trascrizione_in_corso": "Transcribing the speech…",
        "trascritto": "Transcribed {caratteri} characters ({backend}).",
        "ricostruzione": "The local model is reconstructing the recipe…",
        "commenti_autore": ("Found {quanti} comments by the author: they often hold the "
                            "missing amounts."),
        "conversione": "Converting the amounts with the tables…",
        "pronta": "Ready: «{titolo}».",
        "senza_media": "No media file: only the caption was analysed.",
        "audio_fallito": "Audio not extracted ({dettaglio}). Carrying on with the caption alone.",
        "trascrizione_vuota": "The transcription came out empty: perhaps nobody speaks in the reel.",
        "trascrizione_fallita": ("Transcription failed ({dettaglio}). Carrying on with the "
                                 "caption alone."),
        "solo_parlato": "Recipe taken from the speech alone: check the amounts.",
        "solo_didascalia": "Recipe taken from the caption alone: the speech was not read.",
        "niente_da_analizzare": "There is nothing to analyse: no caption and no transcribable speech.",
        "non_una_ricetta": "«{etichetta}» does not seem to contain a cooking recipe.",
    },
}


def testo(lingua: str, chiave: str, **dati) -> str:
    """Una frase di avanzamento o un'avvertenza, nella lingua della ricetta."""
    return testo_da(TESTI, lingua, chiave, **dati)


def _silenzio(fase: str, messaggio: str) -> None:
    pass


@dataclass
class Esito:
    """Il risultato di una lavorazione, con la traccia di come ci si è arrivati."""

    ricetta: Ricetta | None = None
    media: acquire.Media | None = None
    trascrizione: asr.Transcript | None = None
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
    lingua: str,
) -> asr.Transcript | None:
    """Estrae l'audio e lo trascrive. Ogni fallimento diventa un'avvertenza, non un'eccezione:
    la didascalia da sola può bastare."""
    if media.percorso is None:
        avvertenze.append(testo(lingua, "senza_media"))
        return None

    try:
        if media.e_audio:
            percorso_audio = media.percorso
        else:
            su_avanzamento("audio", testo(lingua, "estrazione_audio"))
            percorso_audio = audio.extract_audio(media.percorso, media_folder())
    except audio.AudioError as e:
        avvertenze.append(testo(lingua, "audio_fallito", dettaglio=e))
        return None

    try:
        su_avanzamento("trascrizione", testo(lingua, "trascrizione_in_corso"))
        trascrizione = asr.transcribe(percorso_audio, language=lingua_audio,
                                      model=modello_asr, backend=backend)
        if not trascrizione:
            avvertenze.append(testo(lingua, "trascrizione_vuota"))
            return None
        su_avanzamento("trascrizione", testo(lingua, "trascritto",
                                             caratteri=len(trascrizione.text),
                                             backend=trascrizione.backend))
        return trascrizione
    except asr.TranscriptionError as e:
        avvertenze.append(testo(lingua, "trascrizione_fallita", dettaglio=e))
        return None


def _copertina(media: acquire.Media) -> list[str]:
    """Un'immagine di copertina per la ricetta, se ottenibile. Non è essenziale:
    un fallimento qui non deve costare una ricetta."""
    if base64_copertina := media.copertina_base64():
        return [base64_copertina]
    if media.percorso and not media.e_audio:
        if fotogramma := audio.extract_cover(media.percorso, media_folder()):
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
    modello_asr: str = asr.DEFAULT_MODEL,
    lingua_audio: str | None = asr.DEFAULT_LANGUAGE,
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
            media, backend_asr, modello_asr, lingua_audio, su_avanzamento, avvertenze,
            sigla(lingua),
        )

    testo_trascrizione = trascrizione.text if trascrizione else ""
    if not media.didascalia.strip() and not testo_trascrizione.strip():
        return Esito(
            media=media,
            avvertenze=avvertenze,
            errore=testo(lingua, "niente_da_analizzare"),
        )

    if media.commenti_autore:
        su_avanzamento("estrazione", testo(lingua, "commenti_autore",
                                           quanti=len(media.commenti_autore)))

    su_avanzamento("estrazione", testo(lingua, "ricostruzione"))
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
        raise NonEUnaRicetta(testo(lingua, "non_una_ricetta", etichetta=media.etichetta()))

    su_avanzamento("conversione", testo(lingua, "conversione"))
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
        avvertenze.append(testo(lingua, "solo_parlato"))
    if not testo_trascrizione.strip():
        avvertenze.append(testo(lingua, "solo_didascalia"))

    su_avanzamento("fatto", testo(lingua, "pronta", titolo=ricetta.titolo))
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
    lingua = kwargs.get("lingua", Lingua.IT)
    su_avanzamento("acquisizione", testo(lingua, "scaricamento"))
    media = acquire.da_url(url, media_folder(), cookies_da_browser=cookies_da_browser)
    su_avanzamento("acquisizione", testo(lingua, "scaricato", etichetta=media.etichetta()))
    return lavora(media, su_avanzamento, **kwargs)


def da_file(percorso: Path | str, didascalia: str = "",
            su_avanzamento: Avanzamento = _silenzio, **kwargs) -> Esito:
    """Per i reel già salvati sul disco, o quando lo scaricamento non è possibile."""
    su_avanzamento("acquisizione", testo(kwargs.get("lingua", Lingua.IT), "lettura_file"))
    media = acquire.da_file(percorso, didascalia=didascalia)
    return lavora(media, su_avanzamento, **kwargs)


def controlla_ambiente(url_ollama: str = extract.URL_OLLAMA_PREDEFINITO) -> dict:
    """Stato dei componenti esterni, per la diagnostica di CLI e interfaccia.

    Serve a dare messaggi utili *prima* che qualcosa fallisca a metà lavorazione.
    """
    backend = asr.available_backends()
    modelli = extract.modelli_disponibili(url_ollama)
    ollama_ok = extract.ollama_attivo(url_ollama)
    return {
        "ffmpeg": audio.ffmpeg_available(),
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
