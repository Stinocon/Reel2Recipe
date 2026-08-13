// i18n.js — the interface's words, in the languages it exists in.
//
// Same shape as `icons.js`: an ES module with no dependencies, carrying its own data. The
// catalogue lives here and not in the server on purpose — whoever writes the string owns it.
// The words on the *buttons* are the frontend's; the progress lines and the errors are
// written by Python and stay over there (`pipeline.py`, `api.py`). Keeping them all in the
// server would force the page into a network round trip before it could draw itself, with a
// flash of untranslated text on every load, and would put the interface's text far from the
// interface.
//
// THREE AXES, NOT TWO. To the pair that already exists (the recipe's language, the system of
// measurement) one is added that comes before them: the language **of the interface**. The
// three form a chain, each with the previous one as its fallback — the interface decides the
// recipe's language, which decides the system — so anyone who touches nothing gets a coherent
// set, and anyone who wants to cross them still can.

// The keys are English; the values obviously are not. It is the same split as the Python
// catalogues (`units.MESSAGES`, `pipeline.TEXTS`): the key is code, the value is what a
// person reads.

const FALLBACK = 'it';

const TEXTS = {
  it: {
    // -- header and status ------------------------------------------------------------
    page_title: 'Reel2Recipe — dai reel al ricettario',
    subtitle: 'Dai reel di cucina al tuo ricettario. Tutto sul tuo computer.',
    interface_language: 'Lingua dell’interfaccia',
    status_title: 'Stato dei componenti locali',
    status_checking: 'verifica…',
    status_ollama_down: 'Ollama spento',
    status_no_model: 'nessun modello LLM',
    status_ready_captions: 'pronto (solo didascalie)',
    status_all_ready: 'tutto pronto',
    status_unreachable: 'server non raggiungibile',
    note_no_model:
      'Nessun modello di linguaggio disponibile. Se l’installazione è appena avvenuta '
      + 'può essere ancora in scaricamento: sono diversi GB e il registro lo dice. '
      + 'Su un’installazione locale: ollama pull {model}',
    note_ollama_down:
      'Ollama non risponde. Nell’add-on parte da solo, quindi conviene guardare il '
      + 'registro; su un’installazione locale avvialo con: ollama serve',

    // -- the Cook bar -----------------------------------------------------------------
    url_placeholder: 'Incolla il link di un reel di cucina…',
    cook: 'Cook',
    drop_hint: 'oppure trascina qui un video, o <span class="sottolineato">scegli un file</span>',
    release_here: 'Rilascia qui il video del reel',
    options_open: 'Opzioni ▾',
    options_close: 'Opzioni ▴',
    cancel: 'Annulla',

    // -- options --------------------------------------------------------------------
    lbl_transcription: 'Trascrizione',
    asr_auto: 'Automatica (consigliata)',
    asr_mlx: 'Accelerata (Mac Apple Silicon)',
    asr_cpu: 'Portabile (CPU)',
    lbl_spoken_language: 'Lingua parlata nel reel',
    spoken_auto: 'Riconoscila da sé',
    lbl_model: 'Modello di linguaggio',
    model_best: 'Il migliore installato',
    lbl_recipe_language: 'Lingua della ricetta',
    language_as_interface: 'Come l’interfaccia',
    lbl_measures: 'Misure',
    measures_as_language: 'Come la lingua',
    measures_metric: 'Metriche (g, ml)',
    measures_imperial: 'Imperiali (cup, oz)',
    opt_no_audio: 'Usa solo la didascalia (salta l’audio)',

    // -- processing stages -----------------------------------------------------
    stage_acquisition: 'Recupero del reel',
    stage_audio: 'Estrazione audio',
    stage_transcription: 'Trascrizione del parlato',
    stage_extraction: 'Ricostruzione della ricetta',
    stage_conversion: 'Conversione delle quantità',
    stage_done: 'Pronta',

    // -- the recipe card -------------------------------------------------------------
    card_note: 'Nota:',
    card_ingredients: 'Ingredienti',
    card_method: 'Procedimento',
    card_to_check: 'Da verificare',
    tag_estimate: 'stima',
    btn_save: 'Salva nel ricettario',
    btn_edit: 'Correggi',
    btn_mela: 'Scarica per Mela',
    btn_pdf: 'PDF',
    btn_markdown: 'Markdown',
    btn_delete: 'Elimina',

    // -- editing -------------------------------------------------------------------
    modal_title: 'Correggi la ricetta',
    modal_hint:
      'Un ingrediente per riga (es. "200 g farina 00"), un passo per riga. '
      + 'Usa "# Titolo" per iniziare un gruppo di ingredienti.',
    field_title: 'Titolo',
    field_servings: 'Porzioni',
    field_ingredients: 'Ingredienti',
    field_method: 'Procedimento',
    btn_save_edits: 'Salva le correzioni',

    // -- library -------------------------------------------------------------------
    library_title: 'Il tuo ricettario',
    search_placeholder: 'Cerca fra le ricette…',
    export_all: 'Esporta tutto per Mela',
    library_empty: 'Il ricettario è vuoto. Incolla il link di un reel qui sopra e premi Cook per iniziare.',
    library_no_results: 'Nessuna ricetta trovata per «{search}».',
    card_ingredient_count: '{how_many} ingr.',
    card_to_review: 'da rivedere',
    minutes: '{how_many} min',

    // -- transient messages ----------------------------------------------------------
    toast_http_link: 'Incolla un link che inizia con http.',
    toast_extraction_failed: 'Estrazione non riuscita.',
    toast_connection: 'Connessione interrotta durante l’estrazione.',
    toast_saved: 'Salvata nel ricettario.',
    toast_deleted: 'Ricetta eliminata.',
    toast_edits: 'Correzioni applicate. Ricordati di salvare.',
    confirm_delete: 'Eliminare «{title}» dal ricettario?\n\nL’operazione non è reversibile.',
    http_error: 'Errore {status}',

    // -- footer --------------------------------------------------------------
    footer_local: 'Interamente locale · nessuna IA online · nessun payload lascia il computer · '
      + 'esporta in <strong>Mela</strong>, PDF e Markdown',
    footer_warning: 'Le quantità convertite vengono da tabelle verificate, ma l’estrazione '
      + 'è automatica: <strong>controlla la ricetta prima di cucinarla.</strong> '
      + 'Le lacune sono sempre dichiarate, mai riempite a caso.',
    footer_code: 'Codice sorgente',
    footer_terms: 'Condizioni d’uso',
    footer_licence: 'Licenza MIT',
  },

  en: {
    // -- header and status ------------------------------------------------------------
    page_title: 'Reel2Recipe — from reels to your recipe book',
    subtitle: 'From cooking reels to your recipe book. All on your own computer.',
    interface_language: 'Interface language',
    status_title: 'State of the local components',
    status_checking: 'checking…',
    status_ollama_down: 'Ollama is down',
    status_no_model: 'no LLM installed',
    status_ready_captions: 'ready (captions only)',
    status_all_ready: 'all ready',
    status_unreachable: 'server unreachable',
    note_no_model:
      'No language model available. If you have just installed it, it may still be '
      + 'downloading: it is several GB and the log says so. '
      + 'On a local install: ollama pull {model}',
    note_ollama_down:
      'Ollama is not answering. Inside the add-on it starts on its own, so the log is the '
      + 'place to look; on a local install start it with: ollama serve',

    // -- the Cook bar -----------------------------------------------------------------
    url_placeholder: 'Paste the link of a cooking reel…',
    cook: 'Cook',
    drop_hint: 'or drag a video here, or <span class="sottolineato">choose a file</span>',
    release_here: 'Drop the reel video here',
    options_open: 'Options ▾',
    options_close: 'Options ▴',
    cancel: 'Cancel',

    // -- options --------------------------------------------------------------------
    lbl_transcription: 'Transcription',
    asr_auto: 'Automatic (recommended)',
    asr_mlx: 'Accelerated (Mac Apple Silicon)',
    asr_cpu: 'Portable (CPU)',
    lbl_spoken_language: 'Language spoken in the reel',
    spoken_auto: 'Detect it',
    lbl_model: 'Language model',
    model_best: 'The best one installed',
    lbl_recipe_language: 'Recipe language',
    language_as_interface: 'Same as the interface',
    lbl_measures: 'Measurements',
    measures_as_language: 'Same as the language',
    measures_metric: 'Metric (g, ml)',
    measures_imperial: 'Imperial (cup, oz)',
    opt_no_audio: 'Use the caption only (skip the audio)',

    // -- processing stages -----------------------------------------------------
    stage_acquisition: 'Fetching the reel',
    stage_audio: 'Extracting the audio',
    stage_transcription: 'Transcribing the speech',
    stage_extraction: 'Reconstructing the recipe',
    stage_conversion: 'Converting the amounts',
    stage_done: 'Ready',

    // -- the recipe card -------------------------------------------------------------
    card_note: 'Note:',
    card_ingredients: 'Ingredients',
    card_method: 'Method',
    card_to_check: 'To check',
    tag_estimate: 'estimate',
    btn_save: 'Save to the recipe book',
    btn_edit: 'Correct',
    btn_mela: 'Download for Mela',
    btn_pdf: 'PDF',
    btn_markdown: 'Markdown',
    btn_delete: 'Delete',

    // -- editing -------------------------------------------------------------------
    modal_title: 'Correct the recipe',
    modal_hint:
      'One ingredient per line (e.g. "200 g plain flour"), one step per line. '
      + 'Use "# Title" to start a group of ingredients.',
    field_title: 'Title',
    field_servings: 'Servings',
    field_ingredients: 'Ingredients',
    field_method: 'Method',
    btn_save_edits: 'Save the corrections',

    // -- library -------------------------------------------------------------------
    library_title: 'Your recipe book',
    search_placeholder: 'Search the recipes…',
    export_all: 'Export everything for Mela',
    library_empty: 'The recipe book is empty. Paste the link of a reel above and press Cook to start.',
    library_no_results: 'No recipe found for «{search}».',
    card_ingredient_count: '{how_many} ingr.',
    card_to_review: 'to review',
    minutes: '{how_many} min',

    // -- transient messages ----------------------------------------------------------
    toast_http_link: 'Paste a link starting with http.',
    toast_extraction_failed: 'Extraction failed.',
    toast_connection: 'The connection dropped during the extraction.',
    toast_saved: 'Saved to the recipe book.',
    toast_deleted: 'Recipe deleted.',
    toast_edits: 'Corrections applied. Remember to save.',
    confirm_delete: 'Delete «{title}» from the recipe book?\n\nThis cannot be undone.',
    http_error: 'Error {status}',

    // -- footer --------------------------------------------------------------
    footer_local: 'Entirely local · no online AI · no data leaves your computer · '
      + 'exports to <strong>Mela</strong>, PDF and Markdown',
    footer_warning: 'Converted amounts come from verified tables, but the extraction is '
      + 'automatic: <strong>check the recipe before you cook it.</strong> '
      + 'Gaps are always declared, never filled in at random.',
    footer_code: 'Source code',
    footer_terms: 'Terms of use',
    footer_licence: 'MIT licence',
  },
};

export const LANGUAGES = Object.keys(TEXTS);

const STORAGE_KEY = 'r2r-lingua';

// The starting language: the one chosen last time, otherwise the browser's, otherwise
// Italian. The project was born in Italian, but that is no reason to open in Italian in
// front of someone whose system is in English.
function linguaIniziale() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && TEXTS[saved]) return saved;
  } catch {
    // localStorage can be denied (private browsing, permissions): not an error worth
    // stopping the page for, so we fall back to the browser.
  }
  const from_browser = (navigator.language || '').slice(0, 2).toLowerCase();
  return TEXTS[from_browser] ? from_browser : FALLBACK;
}

let current = linguaIniziale();

export const currentLanguage = () => current;

/** A string of the interface, with the `{name}` placeholders filled in.
 *
 * `forced` is there for text belonging to a **recipe** rather than to the page: the card's
 * headings follow the language the recipe was produced in, as the exports already do, so an
 * English recipe is not read under an Italian heading.
 */
export function t(key, data = {}, forced = null) {
  const catalogue = TEXTS[forced] || TEXTS[current] || TEXTS[FALLBACK];
  const raw = catalogue[key] ?? TEXTS[FALLBACK][key] ?? key;
  return raw.replace(/\{(\w+)\}/g, (intero, name) =>
    (name in data ? String(data[name]) : intero));
}

/** Fills the static markup: `data-i18n` for text, `data-i18n-html` where the string
 *  contains inline markup, `data-i18n-<attribute>` for placeholders and titles.
 *
 *  `data-i18n-html` exists because replacing the `textContent` of an element that contains
 *  other nodes deletes them — and in one case that node was the `<input type="file">` hidden
 *  inside its label, i.e. half of the way to upload a video.
 */
export function applyTexts(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  root.querySelectorAll('[data-i18n-html]').forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  for (const attribute of ['placeholder', 'title', 'aria-label']) {
    const marker = `data-i18n-${attribute}`;
    root.querySelectorAll(`[${marker}]`).forEach((el) => {
      el.setAttribute(attribute, t(el.getAttribute(marker)));
    });
  }
  document.documentElement.lang = current;
  document.title = t('page_title');
}

/** Switches language and redraws the static markup. The parts built at runtime (the card,
 *  the library) are redrawn by whoever owns them, through `onLanguageChange`. */
export function setLanguage(next) {
  if (!TEXTS[next] || next === current) return;
  current = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // If the choice cannot be remembered, it is applied for this session anyway.
  }
  applyTexts();
  listeners.forEach((f) => f(next));
}

const listeners = [];
export const onLanguageChange = (f) => listeners.push(f);
