// i18n.js — le parole dell'interfaccia, nelle lingue in cui esiste.
//
// Stessa forma di `icone.js`: un modulo ES senza dipendenze, con i suoi dati incorporati.
// Il catalogo sta qui e non nel server di proposito — chi scrive la stringa la possiede.
// Le parole dei *bottoni* le scrive il frontend, quelle dell'avanzamento e degli errori le
// scrive Python e restano di là (`pipeline.py`, `api.py`). Tenerle tutte nel server
// costringerebbe la pagina a un giro di rete prima di potersi disegnare, con un lampo di
// testo non tradotto a ogni caricamento, e metterebbe il testo dell'interfaccia lontano
// dall'interfaccia.
//
// TRE ASSI, NON DUE. Alla coppia già esistente (lingua della ricetta, sistema di misura)
// se ne aggiunge uno che viene prima: la lingua **dell'interfaccia**. I tre stanno in
// catena, ciascuno con il precedente come ripiego — l'interfaccia decide la lingua della
// ricetta, che decide il sistema — così chi non tocca niente ottiene un insieme coerente e
// chi vuole incrociarli può ancora farlo.

const RIPIEGO = 'it';

const TESTI = {
  it: {
    // -- testata e stato ------------------------------------------------------------
    titolo_pagina: 'Reel2Recipe — dai reel al ricettario',
    sottotitolo: 'Dai reel di cucina al tuo ricettario. Tutto sul tuo computer.',
    lingua_interfaccia: 'Lingua dell’interfaccia',
    stato_titolo: 'Stato dei componenti locali',
    stato_verifica: 'verifica…',
    stato_ollama_spento: 'Ollama spento',
    stato_nessun_modello: 'nessun modello LLM',
    stato_pronto_didascalie: 'pronto (solo didascalie)',
    stato_tutto_pronto: 'tutto pronto',
    stato_irraggiungibile: 'server non raggiungibile',
    nota_nessun_modello:
      'Nessun modello di linguaggio disponibile. Se l’installazione è appena avvenuta '
      + 'può essere ancora in scaricamento: sono diversi GB e il registro lo dice. '
      + 'Su un’installazione locale: ollama pull {modello}',
    nota_ollama_spento:
      'Ollama non risponde. Nell’add-on parte da solo, quindi conviene guardare il '
      + 'registro; su un’installazione locale avvialo con: ollama serve',

    // -- barra Cook -----------------------------------------------------------------
    url_placeholder: 'Incolla il link di un reel di cucina…',
    cook: 'Cook',
    trascina: 'oppure trascina qui un video, o <span class="sottolineato">scegli un file</span>',
    rilascia_qui: 'Rilascia qui il video del reel',
    opzioni_apri: 'Opzioni ▾',
    opzioni_chiudi: 'Opzioni ▴',
    annulla: 'Annulla',

    // -- opzioni --------------------------------------------------------------------
    lbl_trascrizione: 'Trascrizione',
    asr_auto: 'Automatica (consigliata)',
    asr_mlx: 'Accelerata (Mac Apple Silicon)',
    asr_cpu: 'Portabile (CPU)',
    lbl_lingua_parlato: 'Lingua parlata nel reel',
    parlato_auto: 'Riconoscila da sé',
    lbl_modello: 'Modello di linguaggio',
    modello_migliore: 'Il migliore installato',
    lbl_lingua_ricetta: 'Lingua della ricetta',
    lingua_come_interfaccia: 'Come l’interfaccia',
    lbl_misure: 'Misure',
    misure_come_lingua: 'Come la lingua',
    misure_metriche: 'Metriche (g, ml)',
    misure_imperiali: 'Imperiali (cup, oz)',
    opt_no_audio: 'Usa solo la didascalia (salta l’audio)',

    // -- fasi della lavorazione -----------------------------------------------------
    fase_acquisizione: 'Recupero del reel',
    fase_audio: 'Estrazione audio',
    fase_trascrizione: 'Trascrizione del parlato',
    fase_estrazione: 'Ricostruzione della ricetta',
    fase_conversione: 'Conversione delle quantità',
    fase_fatto: 'Pronta',

    // -- scheda ricetta -------------------------------------------------------------
    scheda_nota: 'Nota:',
    scheda_ingredienti: 'Ingredienti',
    scheda_procedimento: 'Procedimento',
    scheda_da_verificare: 'Da verificare',
    tag_stima: 'stima',
    btn_salva: 'Salva nel ricettario',
    btn_correggi: 'Correggi',
    btn_mela: 'Scarica per Mela',
    btn_pdf: 'PDF',
    btn_markdown: 'Markdown',
    btn_elimina: 'Elimina',

    // -- modifica -------------------------------------------------------------------
    modale_titolo: 'Correggi la ricetta',
    modale_suggerimento:
      'Un ingrediente per riga (es. "200 g farina 00"), un passo per riga. '
      + 'Usa "# Titolo" per iniziare un gruppo di ingredienti.',
    campo_titolo: 'Titolo',
    campo_porzioni: 'Porzioni',
    campo_ingredienti: 'Ingredienti',
    campo_procedimento: 'Procedimento',
    btn_salva_correzioni: 'Salva le correzioni',

    // -- libreria -------------------------------------------------------------------
    libreria_titolo: 'Il tuo ricettario',
    cerca_placeholder: 'Cerca fra le ricette…',
    esporta_tutto: 'Esporta tutto per Mela',
    libreria_vuota: 'Il ricettario è vuoto. Incolla il link di un reel qui sopra e premi Cook per iniziare.',
    libreria_nessun_risultato: 'Nessuna ricetta trovata per «{cerca}».',
    carta_ingredienti: '{quanti} ingr.',
    carta_da_rivedere: 'da rivedere',
    minuti: '{quanti} min',

    // -- messaggi effimeri ----------------------------------------------------------
    toast_link_http: 'Incolla un link che inizia con http.',
    toast_estrazione_fallita: 'Estrazione non riuscita.',
    toast_connessione: 'Connessione interrotta durante l’estrazione.',
    toast_salvata: 'Salvata nel ricettario.',
    toast_eliminata: 'Ricetta eliminata.',
    toast_correzioni: 'Correzioni applicate. Ricordati di salvare.',
    conferma_elimina: 'Eliminare «{titolo}» dal ricettario?\n\nL’operazione non è reversibile.',
    errore_http: 'Errore {stato}',

    // -- piè di pagina --------------------------------------------------------------
    pie_locale: 'Interamente locale · nessuna IA online · nessun dato lascia il computer · '
      + 'esporta in <strong>Mela</strong>, PDF e Markdown',
    pie_avvertenza: 'Le quantità convertite vengono da tabelle verificate, ma l’estrazione '
      + 'è automatica: <strong>controlla la ricetta prima di cucinarla.</strong> '
      + 'Le lacune sono sempre dichiarate, mai riempite a caso.',
    pie_codice: 'Codice sorgente',
    pie_condizioni: 'Condizioni d’uso',
    pie_licenza: 'Licenza MIT',
  },

  en: {
    // -- testata e stato ------------------------------------------------------------
    titolo_pagina: 'Reel2Recipe — from reels to your recipe book',
    sottotitolo: 'From cooking reels to your recipe book. All on your own computer.',
    lingua_interfaccia: 'Interface language',
    stato_titolo: 'State of the local components',
    stato_verifica: 'checking…',
    stato_ollama_spento: 'Ollama is down',
    stato_nessun_modello: 'no LLM installed',
    stato_pronto_didascalie: 'ready (captions only)',
    stato_tutto_pronto: 'all ready',
    stato_irraggiungibile: 'server unreachable',
    nota_nessun_modello:
      'No language model available. If you have just installed it, it may still be '
      + 'downloading: it is several GB and the log says so. '
      + 'On a local install: ollama pull {modello}',
    nota_ollama_spento:
      'Ollama is not answering. Inside the add-on it starts on its own, so the log is the '
      + 'place to look; on a local install start it with: ollama serve',

    // -- barra Cook -----------------------------------------------------------------
    url_placeholder: 'Paste the link of a cooking reel…',
    cook: 'Cook',
    trascina: 'or drag a video here, or <span class="sottolineato">choose a file</span>',
    rilascia_qui: 'Drop the reel video here',
    opzioni_apri: 'Options ▾',
    opzioni_chiudi: 'Options ▴',
    annulla: 'Cancel',

    // -- opzioni --------------------------------------------------------------------
    lbl_trascrizione: 'Transcription',
    asr_auto: 'Automatic (recommended)',
    asr_mlx: 'Accelerated (Mac Apple Silicon)',
    asr_cpu: 'Portable (CPU)',
    lbl_lingua_parlato: 'Language spoken in the reel',
    parlato_auto: 'Detect it',
    lbl_modello: 'Language model',
    modello_migliore: 'The best one installed',
    lbl_lingua_ricetta: 'Recipe language',
    lingua_come_interfaccia: 'Same as the interface',
    lbl_misure: 'Measurements',
    misure_come_lingua: 'Same as the language',
    misure_metriche: 'Metric (g, ml)',
    misure_imperiali: 'Imperial (cup, oz)',
    opt_no_audio: 'Use the caption only (skip the audio)',

    // -- fasi della lavorazione -----------------------------------------------------
    fase_acquisizione: 'Fetching the reel',
    fase_audio: 'Extracting the audio',
    fase_trascrizione: 'Transcribing the speech',
    fase_estrazione: 'Reconstructing the recipe',
    fase_conversione: 'Converting the amounts',
    fase_fatto: 'Ready',

    // -- scheda ricetta -------------------------------------------------------------
    scheda_nota: 'Note:',
    scheda_ingredienti: 'Ingredients',
    scheda_procedimento: 'Method',
    scheda_da_verificare: 'To check',
    tag_stima: 'estimate',
    btn_salva: 'Save to the recipe book',
    btn_correggi: 'Correct',
    btn_mela: 'Download for Mela',
    btn_pdf: 'PDF',
    btn_markdown: 'Markdown',
    btn_elimina: 'Delete',

    // -- modifica -------------------------------------------------------------------
    modale_titolo: 'Correct the recipe',
    modale_suggerimento:
      'One ingredient per line (e.g. "200 g plain flour"), one step per line. '
      + 'Use "# Title" to start a group of ingredients.',
    campo_titolo: 'Title',
    campo_porzioni: 'Servings',
    campo_ingredienti: 'Ingredients',
    campo_procedimento: 'Method',
    btn_salva_correzioni: 'Save the corrections',

    // -- libreria -------------------------------------------------------------------
    libreria_titolo: 'Your recipe book',
    cerca_placeholder: 'Search the recipes…',
    esporta_tutto: 'Export everything for Mela',
    libreria_vuota: 'The recipe book is empty. Paste the link of a reel above and press Cook to start.',
    libreria_nessun_risultato: 'No recipe found for «{cerca}».',
    carta_ingredienti: '{quanti} ingr.',
    carta_da_rivedere: 'to review',
    minuti: '{quanti} min',

    // -- messaggi effimeri ----------------------------------------------------------
    toast_link_http: 'Paste a link starting with http.',
    toast_estrazione_fallita: 'Extraction failed.',
    toast_connessione: 'The connection dropped during the extraction.',
    toast_salvata: 'Saved to the recipe book.',
    toast_eliminata: 'Recipe deleted.',
    toast_correzioni: 'Corrections applied. Remember to save.',
    conferma_elimina: 'Delete «{titolo}» from the recipe book?\n\nThis cannot be undone.',
    errore_http: 'Error {stato}',

    // -- piè di pagina --------------------------------------------------------------
    pie_locale: 'Entirely local · no online AI · no data leaves your computer · '
      + 'exports to <strong>Mela</strong>, PDF and Markdown',
    pie_avvertenza: 'Converted amounts come from verified tables, but the extraction is '
      + 'automatic: <strong>check the recipe before you cook it.</strong> '
      + 'Gaps are always declared, never filled in at random.',
    pie_codice: 'Source code',
    pie_condizioni: 'Terms of use',
    pie_licenza: 'MIT licence',
  },
};

export const LINGUE = Object.keys(TESTI);

const CHIAVE_MEMORIA = 'r2r-lingua';

// La lingua di partenza: quella scelta l'ultima volta, altrimenti quella del browser,
// altrimenti l'italiano. Il progetto nasce in italiano, ma questo non è un buon motivo per
// aprirsi in italiano davanti a chi ha il sistema in inglese.
function linguaIniziale() {
  try {
    const salvata = localStorage.getItem(CHIAVE_MEMORIA);
    if (salvata && TESTI[salvata]) return salvata;
  } catch {
    // localStorage può essere negato (navigazione privata, permessi): non è un errore
    // che meriti di fermare la pagina, si riparte dal browser.
  }
  const dal_browser = (navigator.language || '').slice(0, 2).toLowerCase();
  return TESTI[dal_browser] ? dal_browser : RIPIEGO;
}

let corrente = linguaIniziale();

export const lingua = () => corrente;

/** Una stringa dell'interfaccia, con i segnaposto `{nome}` sostituiti.
 *
 * `forzata` serve per il testo che appartiene a una **ricetta** e non alla pagina: le
 * intestazioni della scheda seguono la lingua in cui la ricetta è stata prodotta, come già
 * fanno gli export, così una ricetta inglese non si legge sotto un titolo italiano.
 */
export function t(chiave, dati = {}, forzata = null) {
  const catalogo = TESTI[forzata] || TESTI[corrente] || TESTI[RIPIEGO];
  const grezzo = catalogo[chiave] ?? TESTI[RIPIEGO][chiave] ?? chiave;
  return grezzo.replace(/\{(\w+)\}/g, (intero, nome) =>
    (nome in dati ? String(dati[nome]) : intero));
}

/** Riempie il markup statico: `data-i18n` per il testo, `data-i18n-html` dove la stringa
 *  contiene marcatura in linea, `data-i18n-<attributo>` per placeholder e title.
 *
 *  `data-i18n-html` esiste perché sostituire il `textContent` di un elemento che contiene
 *  altri nodi li cancella — e in un caso quel nodo era l'`<input type="file">` nascosto
 *  dentro la sua etichetta, cioè metà del modo di caricare un video.
 */
export function applicaTesti(radice = document) {
  radice.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  radice.querySelectorAll('[data-i18n-html]').forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  for (const attributo of ['placeholder', 'title', 'aria-label']) {
    const dato = `data-i18n-${attributo}`;
    radice.querySelectorAll(`[${dato}]`).forEach((el) => {
      el.setAttribute(attributo, t(el.getAttribute(dato)));
    });
  }
  document.documentElement.lang = corrente;
  document.title = t('titolo_pagina');
}

/** Cambia lingua e ridisegna il markup statico. Le parti costruite a runtime (scheda,
 *  libreria) le ridisegna chi le possiede, tramite `alCambioLingua`. */
export function impostaLingua(nuova) {
  if (!TESTI[nuova] || nuova === corrente) return;
  corrente = nuova;
  try {
    localStorage.setItem(CHIAVE_MEMORIA, nuova);
  } catch {
    // Se non si può ricordare la scelta, la si applica lo stesso per questa sessione.
  }
  applicaTesti();
  ascoltatori.forEach((f) => f(nuova));
}

const ascoltatori = [];
export const alCambioLingua = (f) => ascoltatori.push(f);
