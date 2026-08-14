// app.js — the page's logic. Native ES modules, no dependencies, no build step.
//
// The same pipeline as the CLI, driven from here. Extraction is slow, so the page does not
// wait for the HTTP response: it starts the job, receives an id and follows the progress over
// Server-Sent Events. That is how the Cook bar says what it is doing, stage by stage.
//
// The element ids and the CSS class names are still Italian, on purpose: they live across
// three files — `index.html`, `app.js` and `style.css` — and moving them is a step of its own
// (see docs/naming.md). `tests/test_web.py` guards both, in both directions.

import { icon, fillIcons } from './icons.js';
import { onLanguageChange, applyTexts, setLanguage, currentLanguage, t } from './i18n.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// Each stage with its icon: the name says what is happening, the icon makes it recognisable
// at a glance while the bar advances. The keys are the protocol with `pipeline.STAGES`.
const STAGES = {
  acquisition: { icon: 'scarica', key: 'stage_acquisition' },
  audio: { icon: 'video', key: 'stage_audio' },
  transcription: { icon: 'microfono', key: 'stage_transcription' },
  extraction: { icon: 'modello', key: 'stage_extraction' },
  conversion: { icon: 'bilancia', key: 'stage_conversion' },
  done: { icon: 'fatto', key: 'stage_done' },
};

const ESTIMATE_PROVENANCES = new Set(['estimated:vague', 'indeterminate', 'absent']);

let currentRecipe = null;   // the freshly extracted recipe, not yet reviewed
// These are needed to redraw the card when the language changes: without them the switch
// would lose the uncertainty warning and the model's name, which are not part of the recipe.
let currentWarnings = [];
let currentModel = '';

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function toast(message, isError = false) {
  // `element` and not `t`: `t` is now the imported translation function, and a local
  // variable by that name would make it invisible inside this function. It would not be
  // needed today, but the first line that did need it would fail in an unreadable way.
  const element = $('#toast');
  element.textContent = message;
  element.classList.toggle('error', isError);
  element.hidden = false;
  clearTimeout(element._timer);
  element._timer = setTimeout(() => (element.hidden = true), 3200);
}

// Under Home Assistant's Ingress the page is not served from the root but from behind a
// token prefix (/api/hassio_ingress/<token>/). An absolute path like `/api/status` would leave
// the prefix and land on Home Assistant's API, not ours. Every call therefore starts from the
// page's base, which locally is simply `/`. `new URL('.', …)` and not a hand-made cut of the
// last segment: that one trips over a query string, which would end up inside the prefix of
// every call.
//
// One case neither form solves: a base with no trailing slash (…/hassio_ingress/<token>),
// where by definition the last segment is a file and has to go. It cannot be worked around
// from the URL, and it does not need to be: without that slash `style.css` and `app.js` would
// already be unreachable, and they have always been relative. If the page renders, the base
// is good.
const BASE = new URL('.', document.baseURI).href;
const address = (path) => BASE + path.replace(/^\//, '');

// The interface's language travels with every call, so the server's errors arrive in the
// right language too. It is called `ui_language` and not `language` on purpose: `/api/cook`
// already has a `language` meaning something else — which language to produce the recipe in.
// Endpoints with no use for it ignore it.
function withUILanguage(path) {
  const url = new URL(address(path));
  url.searchParams.set('ui_language', currentLanguage());
  return url.href;
}

async function api(path, options = {}) {
  const response = await fetch(withUILanguage(path), options);
  if (!response.ok) {
    let detail = t('http_error', { status: response.status });
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

// ---------------------------------------------------------------------------
// State of the components
// ---------------------------------------------------------------------------

async function refreshStatus() {
  try {
    const s = await api('/api/status');
    const dot = $('#status-dot');
    const label = $('#status-text');

    // Fills the available models into their option.
    const select = $('#opt-model');
    if (s.llm_models?.length && select.options.length <= 1) {
      s.llm_models.forEach((m) => select.add(new Option(m, m)));
    }

    if (!s.ready) {
      dot.className = 'dot ko';
      label.textContent = t(s.ollama_up ? 'status_no_model' : 'status_ollama_down');
      // The message does not assume it is running on a development machine: inside the Home
      // Assistant add-on there is no shell to type `ollama pull` into, and the add-on
      // downloads the model itself — saying "run" there is advice that cannot be followed.
      // State first, command second, for whoever has somewhere to type it.
      $('#cook-note').textContent = s.ollama_up
        ? t('note_no_model', { model: s.recommended_model })
        : t('note_ollama_down');
      $('#cook-note').classList.add('error');
    } else if (!s.asr_ready) {
      dot.className = 'dot partial';
      label.textContent = t('status_ready_captions');
    } else {
      dot.className = 'dot ok';
      label.textContent = t('status_all_ready');
    }
  } catch {
    $('#status-dot').className = 'dot ko';
    $('#status-text').textContent = t('status_unreachable');
  }
}

// ---------------------------------------------------------------------------
// Starting an extraction
// ---------------------------------------------------------------------------

// The panel's options, in the shape the API expects. It holds for both roads (link and
// file): whatever is chosen here has to reach the server, always.
//
// The language and system menus were drawn in index.html but never read: the menu was there,
// the choice could be made, and every extraction came out in Italian metric anyway. A control
// that does nothing is worse than a missing one, because it teaches you not to trust the
// interface.
function chosenOptions() {
  return {
    asr_backend: $('#opt-asr').value,
    // Empty = Whisper recognises it. It is a fact about the input and does not follow the
    // recipe's language: an English reel becoming an Italian recipe is the commonest case.
    audio_language: $('#opt-spoken-language').value || null,
    llm_model: $('#opt-model').value || null,
    skip_audio: $('#opt-no-audio').checked,
    // Empty = "same as the interface". It is the first link of the three-axis chain:
    // interface → recipe → measures, each with the previous one as its fallback.
    language: $('#opt-language').value || currentLanguage(),
    // Empty means "same as the language", and the server decides: the rule lives in one
    // place (`CookRequest.axes()`), not here as well.
    system: $('#opt-system').value || null,
  };
}

// The same options as a query string, for the file upload: there the request body is already
// taken by the multipart. A null value is not sent at all, so the server's default stays the
// only fallback rule.
function optionsQuery() {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(chosenOptions())) {
    if (value !== null && value !== '') q.set(key, value);
  }
  return q.toString();
}

async function cookFromUrl() {
  const url = $('#input-url').value.trim();
  if (!url) { $('#input-url').focus(); return; }
  if (!/^https?:\/\//.test(url)) { toast(t('toast_http_link'), true); return; }

  startUI();
  try {
    const { job } = await api('/api/cook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, ...chosenOptions() }),
    });
    followJob(job);
  } catch (e) {
    endUI();
    toast(e.message, true);
  }
}

async function cookFromFile(file) {
  startUI();
  const form = new FormData();
  form.append('file', file);
  try {
    const { job } = await api(`/api/cook-file?${optionsQuery()}`, { method: 'POST', body: form });
    followJob(job);
  } catch (e) {
    endUI();
    toast(e.message, true);
  }
}

function followJob(job) {
  const source = new EventSource(withUILanguage(`/api/cook/${job}/events`));
  source.onmessage = (ev) => {
    const payload = JSON.parse(ev.data);
    if (payload.kind === "progress") {
      markStage(payload.stage, payload.message);
    } else if (payload.kind === "end") {
      source.close();
      endUI();
      if (payload.ok) {
        showRecipe(payload.recipe, payload.warnings, payload.model);
        loadLibrary();
      } else {
        toast(payload.error || t('toast_extraction_failed'), true);
        $('#cook-note').textContent = payload.error || '';
        $('#cook-note').classList.add('error');
      }
    }
  };
  source.onerror = () => {
    source.close();
    endUI();
    toast(t('toast_connection'), true);
  };
}

// ---------------------------------------------------------------------------
// The progress interface
// ---------------------------------------------------------------------------

function startUI() {
  $('#cook-note').textContent = '';
  $('#cook-note').classList.remove('error');
  $('#recipe-card').hidden = true;
  $('#btn-cook').disabled = true;
  $('#btn-cook').classList.add('in-progress');

  const container = $('#stages');
  container.innerHTML = '';
  for (const [key, stage] of Object.entries(STAGES)) {
    if (key === 'fatto') continue;
    const row = document.createElement('div');
    row.className = 'stage';
    row.dataset.stage = key;
    row.innerHTML =
      `<span class="stage-icon">${icon(stage.icon, 16)}</span>` +
      `<span class="stage-text">${t(stage.key)}</span>`;
    container.appendChild(row);
  }
  $('#progress-panel').hidden = false;
  $('#progress-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function markStage(stage, message) {
  const rows = [...$$('#fasi .stage')];
  const index = rows.findIndex((r) => r.dataset.stage === stage);
  rows.forEach((r, i) => {
    r.classList.remove('active');
    // A finished stage shows the tick in place of its own icon; the one under way keeps its
    // own and lights up (the CSS supplies the colour and the pulse).
    if (i < index) {
      r.classList.add('done');
      r.querySelector('.stage-icon').innerHTML = icon('tick', 16);
    } else if (i === index) {
      r.classList.add('active');
    }
  });
  if (index >= 0 && message) rows[index].querySelector('.stage-text').textContent = message;
}

function endUI() {
  $('#btn-cook').disabled = false;
  $('#btn-cook').classList.remove('in-progress');
  $('#progress-panel').hidden = true;
}

// ---------------------------------------------------------------------------
// The recipe card
// ---------------------------------------------------------------------------

function showRecipe(recipe, warnings = [], model = '', scroll = true) {
  currentRecipe = recipe;
  currentWarnings = warnings;
  currentModel = model;
  const card = $('#recipe-card');

  // The card's headings follow the language **of the recipe**, not of the page: the same
  // choice already made for the exports in `mela.py` and `documents.py`, and for the `gaps`,
  // which are saved in the recipe's language. An English recipe under an "Ingredienti"
  // heading would be a card half in one language and half in the other.
  const lr = recipe.language || currentLanguage();

  const cover = recipe.images?.[0]
    ? `<img class="card-cover" src="data:image/jpeg;base64,${recipe.images[0]}" alt="" />`
    : '';

  const meta = [];
  if (recipe.servings) meta.push(`<span>${icon('plate', 16)} ${esc(recipe.servings)}</span>`);
  if (recipe.total_time_min) meta.push(`<span>${icon('time', 16)} ${t('minutes', { how_many: recipe.total_time_min }, lr)}</span>`);
  if (recipe.source?.author) meta.push(`<span>${icon('author', 16)} ${esc(recipe.source.author)}</span>`);

  card.innerHTML = `
    ${cover}
    <div class="card-body">
      <h2 class="card-title">${esc(recipe.title)}</h2>
      <div class="card-meta">${meta.join('')}${model ? `<span class="source-badge">${icon('model', 16)} ${esc(model)}</span>` : ''}</div>
      ${warnings?.length ? `<div class="uncertainty-warning"><strong>${esc(t('card_note', {}, lr))}</strong> ${warnings.map(esc).join(' ')}</div>` : ''}
      <h3 class="section-title">${esc(t('card_ingredients', {}, lr))}</h3>
      ${renderIngredients(recipe, lr)}
      <h3 class="section-title">${esc(t('card_method', {}, lr))}</h3>
      <ol class="method-list">${(recipe.method || []).map((p) => `<li class="step">${esc(p)}</li>`).join('')}</ol>
      ${renderGaps(recipe, lr)}
      <div class="card-actions">
        <button class="btn-primary" id="btn-save-card">${icon('save')} ${esc(t('btn_save'))}</button>
        <button class="btn-secondary" id="btn-edit-card">${icon('edit')} ${esc(t('btn_edit'))}</button>
        <button class="btn-secondary" id="btn-export-card">${icon('download')} ${esc(t('btn_mela'))}</button>
        <button class="btn-secondary" id="btn-export-pdf">${icon('pdf')} ${esc(t('btn_pdf'))}</button>
        <button class="btn-secondary" id="btn-export-md">${icon('markdown')} ${esc(t('btn_markdown'))}</button>
        ${recipe.id ? `<button class="btn-danger" id="btn-delete-card">${icon('delete')} ${esc(t('btn_delete'))}</button>` : ''}
      </div>
    </div>`;

  card.hidden = false;
  // Not when merely redrawing for a language change: there the page is where the user left
  // it, and moving it out from under them would be a surprise.
  if (scorri) card.scrollIntoView({ behavior: 'smooth', block: 'start' });

  $('#btn-save-card').onclick = saveCurrentRecipe;
  $('#btn-edit-card').onclick = () => openEditor(currentRecipe);
  $('#btn-export-card').onclick = () => exportCurrentRecipe('mela');
  $('#btn-export-pdf').onclick = () => exportCurrentRecipe('pdf');
  $('#btn-export-md').onclick = () => exportCurrentRecipe('markdown');
  // Present only for recipes already saved: you do not delete what is not yet in the recipe
  // book — for that it is enough not to save it.
  if ($('#btn-delete-card')) $('#btn-delete-card').onclick = () => deleteCurrentRecipe();
}

function renderIngredients(recipe, lr) {
  const groups = [...new Set((recipe.ingredients || []).map((i) => i.group))];
  const showGroups = groups.filter(Boolean).length > 0 && groups.length > 1;
  let html = '<ul class="ingredient-list">';
  for (const group of groups) {
    if (showGroups && group) html += `<li class="group-title">${esc(group)}</li>`;
    for (const ing of recipe.ingredients.filter((i) => i.group === group)) {
      const uncertain = ESTIMATE_PROVENANCES.has(ing.quantity?.provenance);
      const tag = uncertain
        ? `<span class="tag-provenance estimate">${esc(t('tag_estimate', {}, lr))}</span>`
        : '';
      html += `<li class="ingredient${uncertain ? ' uncertain' : ''}">
        <span>${esc(ing.line)}</span>${tag}</li>`;
    }
  }
  return html + '</ul>';
}

function renderGaps(recipe, lr) {
  if (!recipe.gaps?.length) return '';
  return `<h3 class="section-title">${esc(t('card_to_check', {}, lr))}</h3>
    <ul class="gap-list">${recipe.gaps.map((l) => `<li class="gap">${esc(l)}</li>`).join('')}</ul>`;
}

// ---------------------------------------------------------------------------
// Saving, editing, exporting
// ---------------------------------------------------------------------------

async function saveCurrentRecipe() {
  try {
    const { id } = await api('/api/recipes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentRecipe),
    });
    currentRecipe.id = id;
    toast(t('toast_saved'));
    loadLibrary();
  } catch (e) { toast(e.message, true); }
}

async function deleteCurrentRecipe() {
  if (!currentRecipe?.id) return;
  // Explicit confirmation: it is the interface's only destructive action and it cannot be
  // undone. The title in the message stops the wrong recipe being deleted.
  if (!confirm(t('confirm_delete', { title: currentRecipe.title }))) return;
  try {
    await api(`/api/recipes/${currentRecipe.id}`, { method: 'DELETE' });
    $('#recipe-card').hidden = true;
    currentRecipe = null;
    toast(t('toast_deleted'));
    loadLibrary();
  } catch (e) { toast(e.message, true); }
}

async function exportCurrentRecipe(format = 'mela') {
  // A recipe is downloaded only once it is in the recipe book: the export starts from the
  // database, not from what is on screen.
  if (!currentRecipe.id) await saveCurrentRecipe();
  window.location.href = address(`/api/recipes/${currentRecipe.id}/export?format=${format}`);
}

function openEditor(recipe) {
  const content = $('#modal-content');
  // Textual editing: ingredients and steps one per line. Simple and direct — someone
  // correcting wants to fix two words, not fill in a twenty-field form.
  const ingredientRows = (recipe.ingredients || []).map((i) => i.line).join('\n');
  const methodRows = (recipe.method || []).join('\n');

  content.innerHTML = `
    <h2 class="card-title">${esc(t('modal_title'))}</h2>
    <p class="edit-hint">${esc(t('modal_hint'))}</p>
    <div class="edit-field">
      <label>${esc(t('field_title'))}</label>
      <input id="edit-title" value="${esc(recipe.title)}" />
    </div>
    <div class="edit-field">
      <label>${esc(t('field_servings'))}</label>
      <input id="edit-servings" value="${esc(recipe.servings || '')}" />
    </div>
    <div class="edit-field">
      <label>${esc(t('field_ingredients'))}</label>
      <textarea id="edit-ingredients">${esc(ingredientRows)}</textarea>
    </div>
    <div class="edit-field">
      <label>${esc(t('field_method'))}</label>
      <textarea id="edit-method">${esc(methodRows)}</textarea>
    </div>
    <div class="card-actions">
      <button class="btn-primary" id="btn-save-edit">${esc(t('btn_save_edits'))}</button>
      <button class="btn-text" id="btn-close-modal">${esc(t('cancel'))}</button>
    </div>`;

  $('#modal').hidden = false;
  $('#btn-close-modal').onclick = () => ($('#modal').hidden = true);
  $('#btn-save-edit').onclick = () => applyEdits(recipe);
}

function applyEdits(recipe) {
  // The textual corrections replace the extraction: the edited lines become each
  // ingredient's "riga" text. The conversion has already happened; here the user has the
  // last word, and their word wins.
  recipe.title = $('#edit-title').value.trim() || recipe.title;
  recipe.servings = $('#edit-servings').value.trim() || null;

  let group = null;
  recipe.ingredients = $('#edit-ingredients').value.split('\n')
    .map((r) => r.trim()).filter(Boolean)
    .map((row) => {
      if (row.startsWith('#')) { group = row.replace(/^#\s*/, ''); return null; }
      // The shape has to be the one `to_dict()` writes, key for key: what comes out of the
      // editor goes straight to `PUT /api/recipes/{id}` and is stored as it stands.
      return {
        name: row, group,
        notes: null, gap: null, line: row,
        quantity: { provenance: 'declared', value: null, value_max: null, unit: null,
                    original_text: row, note: null, system: 'metric', uncertain: false },
      };
    })
    .filter(Boolean);

  recipe.method = $('#edit-method').value.split('\n').map((r) => r.trim()).filter(Boolean);

  $('#modal').hidden = true;
  showRecipe(recipe, [], '');
  toast(t('toast_edits'));
}

// ---------------------------------------------------------------------------
// The library
// ---------------------------------------------------------------------------

async function loadLibrary(search = '') {
  try {
    const entries = await api('/api/recipes' + (search ? `?search=${encodeURIComponent(search)}` : ''));
    const grid = $('#recipe-grid');
    $('#library-empty').hidden = entries.length > 0;
    $('#library-empty').textContent = search
      ? t('library_no_results', { search: search })
      : t('library_empty');

    grid.innerHTML = entries.map((v) => {
      const cover = v.cover
        ? `style="background-image:url('data:image/jpeg;base64,${v.cover}')"`
        : '';
      const meta = [
        v.servings, v.total_time_min ? t('minutes', { how_many: v.total_time_min }) : null,
        t('card_ingredient_count', { how_many: v.n_ingredients }),
      ].filter(Boolean).join(' · ');
      return `<article class="recipe-tile" data-id="${v.id}">
        <div class="tile-cover" ${cover}>${v.cover ? '' : icon('plate', 34)}</div>
        <div class="tile-body">
          <div class="tile-title">${esc(v.title)}</div>
          <div class="tile-meta">
            <span>${esc(meta)}</span>
            ${v.has_uncertainties ? `<span class="tile-badge-uncertain">${icon('warning', 14)} ${esc(t('card_to_review'))}</span>` : ''}
          </div>
        </div>
      </article>`;
    }).join('');

    $$('.carta-recipe').forEach((c) => c.onclick = () => openFromLibrary(c.dataset.id));
  } catch (e) { toast(e.message, true); }
}

async function openFromLibrary(id) {
  try {
    const recipe = await api(`/api/recipes/${id}`);
    showRecipe(recipe, [], '');
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------------------
// Small utilities
// ---------------------------------------------------------------------------

function esc(label) {
  const d = document.createElement('div');
  d.textContent = label ?? '';
  return d.innerHTML;
}

let _cercaTimer;
function searchLibrary(valore) {
  clearTimeout(_cercaTimer);
  _cercaTimer = setTimeout(() => loadLibrary(valore.trim()), 250);
}

// ---------------------------------------------------------------------------
// Wiring up the events
// ---------------------------------------------------------------------------

function wireUp() {
  $('#btn-cook').onclick = cookFromUrl;

  // The selector starts from the language already in use — remembered from last time or
  // deduced from the browser — and not from whichever happens to be written first in the
  // markup.
  const languageSelector = $('#opt-ui-language');
  languageSelector.value = currentLanguage();
  languageSelector.onchange = () => setLanguage(languageSelector.value);
  $('#input-url').addEventListener('keydown', (e) => { if (e.key === 'Enter') cookFromUrl(); });

  $('#btn-options').onclick = () => {
    const o = $('#options');
    o.hidden = !o.hidden;
    $('#btn-options').textContent = t(o.hidden ? 'options_open' : 'options_close');
  };

  $('#input-file').onchange = (e) => { if (e.target.files[0]) cookFromFile(e.target.files[0]); };
  $('#input-search').addEventListener('input', (e) => searchLibrary(e.target.value));
  $('#btn-export-all').onclick = () => (window.location.href = address('/api/export'));

  // Drag and drop over the whole page.
  const overlay = $('#drop-overlay');
  let counter = 0;
  window.addEventListener('dragenter', (e) => { e.preventDefault(); if (++counter === 1) overlay.hidden = false; });
  window.addEventListener('dragleave', (e) => { e.preventDefault(); if (--counter === 0) overlay.hidden = true; });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault(); counter = 0; overlay.hidden = true;
    if (e.dataTransfer.files[0]) cookFromFile(e.dataTransfer.files[0]);
  });

  // Close the modal by clicking the backdrop.
  $('#modal').addEventListener('click', (e) => { if (e.target.id === 'modale') $('#modal').hidden = true; });
}

// ---------------------------------------------------------------------------
// Start-up
// ---------------------------------------------------------------------------

// Words first, icons second: `applyTexts` rewrites the content of some elements, and the
// icons of the static pieces have to land on top of that, not underneath.
applyTexts();
fillIcons();   // the icons of index.html's static pieces (logo, Cook, drop area)
wireUp();

// The static markup is redrawn by `i18n.js`; here we redraw what is built at runtime. The
// recipe card is rebuilt only if one is on screen, and its headings stay in the recipe's
// language: what changes is the buttons around it.
onLanguageChange(() => {
  $('#btn-options').textContent = t($('#options').hidden ? 'options_open' : 'options_close');
  refreshStatus();
  loadLibrary($('#input-search').value.trim());
  if (currentRecipe && !$('#recipe-card').hidden) {
    showRecipe(currentRecipe, currentWarnings, currentModel, false);
  }
});

refreshStatus();
loadLibrary();
