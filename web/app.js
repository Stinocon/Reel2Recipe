// app.js — la logica della pagina. Moduli ES nativi, nessuna dipendenza, nessun build step.
//
// La stessa pipeline della CLI, guidata da qui. L'estrazione è lunga, quindi la pagina
// non aspetta la risposta HTTP: avvia il lavoro, riceve un id e segue l'avanzamento via
// Server-Sent Events. Così la barra Cook racconta cosa sta facendo, fase per fase.

import { icona, riempiIcone } from './icone.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// Ogni fase con la sua icona: il nome dice cosa sta succedendo, l'icona lo rende
// riconoscibile a colpo d'occhio mentre la barra avanza.
const FASI = {
  acquisizione: { icona: 'scarica', testo: 'Recupero del reel' },
  audio: { icona: 'video', testo: 'Estrazione audio' },
  trascrizione: { icona: 'microfono', testo: 'Trascrizione del parlato' },
  estrazione: { icona: 'modello', testo: 'Ricostruzione della ricetta' },
  conversione: { icona: 'bilancia', testo: 'Conversione delle quantità' },
  fatto: { icona: 'fatto', testo: 'Pronta' },
};

const PROVENIENZE_STIMA = new Set(['stimato:vaghe', 'indeterminato', 'assente']);

let ricettaCorrente = null;   // la ricetta appena estratta, non ancora rivista

// ---------------------------------------------------------------------------
// Utilità
// ---------------------------------------------------------------------------

function toast(messaggio, errore = false) {
  const t = $('#toast');
  t.textContent = messaggio;
  t.classList.toggle('errore', errore);
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.hidden = true), 3200);
}

// Sotto l'Ingress di Home Assistant la pagina non è servita dalla radice ma da dietro un
// prefisso con token (/api/hassio_ingress/<token>/). Un percorso assoluto come `/api/stato`
// uscirebbe dal prefisso e finirebbe sulla API di Home Assistant, non sulla nostra. Tutte le
// chiamate partono quindi dalla base della pagina, che in locale resta semplicemente `/`.
// `new URL('.', …)` e non un taglio a mano dell'ultimo segmento: quello inciampa su una
// query string, che finirebbe dentro il prefisso di ogni chiamata.
//
// Resta un caso che nessuna delle due forme risolve: una base senza slash finale
// (…/hassio_ingress/<token>), dove per definizione l'ultimo segmento è un file e va tolto.
// Non è aggirabile dall'URL, e non serve: senza quello slash sarebbero già irraggiungibili
// `style.css` e `app.js`, che sono relativi da sempre. Se la pagina si vede, la base è buona.
const BASE = new URL('.', document.baseURI).href;
const indirizzo = (percorso) => BASE + percorso.replace(/^\//, '');

async function api(percorso, opzioni = {}) {
  const risposta = await fetch(indirizzo(percorso), opzioni);
  if (!risposta.ok) {
    let dettaglio = `Errore ${risposta.status}`;
    try { dettaglio = (await risposta.json()).detail || dettaglio; } catch {}
    throw new Error(dettaglio);
  }
  return risposta.status === 204 ? null : risposta.json();
}

// ---------------------------------------------------------------------------
// Stato dei componenti
// ---------------------------------------------------------------------------

async function aggiornaStato() {
  try {
    const s = await api('/api/stato');
    const pallino = $('#pallino-stato');
    const testo = $('#testo-stato');

    // Popola i modelli disponibili nell'opzione dedicata.
    const select = $('#opt-modello');
    if (s.modelli_llm?.length && select.options.length <= 1) {
      s.modelli_llm.forEach((m) => select.add(new Option(m, m)));
    }

    if (!s.pronto) {
      pallino.className = 'pallino ko';
      testo.textContent = s.ollama_attivo ? 'nessun modello LLM' : 'Ollama spento';
      // Il messaggio non dà per scontato di girare su una macchina di sviluppo: dentro
      // l'add-on Home Assistant non c'è una shell dove digitare `ollama pull`, e il modello
      // se lo scarica l'add-on da solo — dire «esegui» lì è un consiglio che non si può
      // seguire. Prima si dichiara lo stato, poi il comando, per chi ha dove darlo.
      $('#cook-nota').textContent = s.ollama_attivo
        ? `Nessun modello di linguaggio disponibile. Se l'installazione è appena avvenuta `
          + `può essere ancora in scaricamento: sono diversi GB e il registro lo dice. `
          + `Su un'installazione locale: ollama pull ${s.modello_consigliato}`
        : `Ollama non risponde. Nell'add-on parte da solo, quindi conviene guardare il `
          + `registro; su un'installazione locale avvialo con: ollama serve`;
      $('#cook-nota').classList.add('errore');
    } else if (!s.asr_pronto) {
      pallino.className = 'pallino parziale';
      testo.textContent = 'pronto (solo didascalie)';
    } else {
      pallino.className = 'pallino ok';
      testo.textContent = 'tutto pronto';
    }
  } catch {
    $('#pallino-stato').className = 'pallino ko';
    $('#testo-stato').textContent = 'server non raggiungibile';
  }
}

// ---------------------------------------------------------------------------
// Avvio di un'estrazione
// ---------------------------------------------------------------------------

// Le opzioni del pannello, nella forma che l'API si aspetta. Vale per entrambe le strade
// (link e file): quello che si sceglie qui deve arrivare al server, sempre.
//
// `lingua` e `sistema` erano disegnate in index.html ma non venivano lette: il menu c'era,
// la scelta si poteva fare, e ogni estrazione usciva comunque in italiano metrico. Un
// comando che non fa niente è peggio di un comando assente, perché insegna a non fidarsi.
function opzioniScelte() {
  return {
    backend_asr: $('#opt-asr').value,
    // Vuoto = la riconosce Whisper. È un fatto dell'ingresso e non segue la lingua della
    // ricetta: un reel inglese che diventa una ricetta italiana è il caso più comune.
    lingua_audio: $('#opt-lingua-parlato').value || null,
    modello_llm: $('#opt-modello').value || null,
    salta_audio: $('#opt-no-audio').checked,
    lingua: $('#opt-lingua').value,
    // Vuoto significa «come la lingua», e a decidere è il server: la regola sta in un
    // punto solo (`RichiestaCook.assi()`), non anche qui.
    sistema: $('#opt-sistema').value || null,
  };
}

// Le stesse opzioni come query string, per il caricamento di un file: lì il corpo della
// richiesta è già occupato dal multipart. Un valore nullo non si manda affatto, così il
// predefinito del server resta l'unica regola di ripiego.
function queryOpzioni() {
  const q = new URLSearchParams();
  for (const [chiave, valore] of Object.entries(opzioniScelte())) {
    if (valore !== null && valore !== '') q.set(chiave, valore);
  }
  return q.toString();
}

async function cookDaUrl() {
  const url = $('#input-url').value.trim();
  if (!url) { $('#input-url').focus(); return; }
  if (!/^https?:\/\//.test(url)) { toast('Incolla un link che inizia con http.', true); return; }

  avviaUI();
  try {
    const { job } = await api('/api/cook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, ...opzioniScelte() }),
    });
    seguiLavoro(job);
  } catch (e) {
    fineUI();
    toast(e.message, true);
  }
}

async function cookDaFile(file) {
  avviaUI();
  const modulo = new FormData();
  modulo.append('file', file);
  try {
    const { job } = await api(`/api/cook-file?${queryOpzioni()}`, { method: 'POST', body: modulo });
    seguiLavoro(job);
  } catch (e) {
    fineUI();
    toast(e.message, true);
  }
}

function seguiLavoro(job) {
  const sorgente = new EventSource(indirizzo(`/api/cook/${job}/eventi`));
  sorgente.onmessage = (ev) => {
    const dato = JSON.parse(ev.data);
    if (dato.tipo === 'avanzamento') {
      segnaFase(dato.fase, dato.messaggio);
    } else if (dato.tipo === 'fine') {
      sorgente.close();
      fineUI();
      if (dato.ok) {
        mostraRicetta(dato.ricetta, dato.avvertenze, dato.modello);
        caricaLibreria();
      } else {
        toast(dato.errore || 'Estrazione non riuscita.', true);
        $('#cook-nota').textContent = dato.errore || '';
        $('#cook-nota').classList.add('errore');
      }
    }
  };
  sorgente.onerror = () => {
    sorgente.close();
    fineUI();
    toast('Connessione interrotta durante l\'estrazione.', true);
  };
}

// ---------------------------------------------------------------------------
// Interfaccia dell'avanzamento
// ---------------------------------------------------------------------------

function avviaUI() {
  $('#cook-nota').textContent = '';
  $('#cook-nota').classList.remove('errore');
  $('#scheda-ricetta').hidden = true;
  $('#btn-cook').disabled = true;
  $('#btn-cook').classList.add('in-corso');

  const contenitore = $('#fasi');
  contenitore.innerHTML = '';
  for (const [chiave, fase] of Object.entries(FASI)) {
    if (chiave === 'fatto') continue;
    const riga = document.createElement('div');
    riga.className = 'fase';
    riga.dataset.fase = chiave;
    riga.innerHTML =
      `<span class="fase-icona">${icona(fase.icona, 16)}</span>` +
      `<span class="fase-testo">${fase.testo}</span>`;
    contenitore.appendChild(riga);
  }
  $('#pannello-avanzamento').hidden = false;
  $('#pannello-avanzamento').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function segnaFase(fase, messaggio) {
  const righe = [...$$('#fasi .fase')];
  const indice = righe.findIndex((r) => r.dataset.fase === fase);
  righe.forEach((r, i) => {
    r.classList.remove('attiva');
    // Una fase conclusa mostra la spunta al posto della propria icona; quella in corso
    // tiene la sua e si accende (il CSS ci mette il colore e la pulsazione).
    if (i < indice) {
      r.classList.add('fatta');
      r.querySelector('.fase-icona').innerHTML = icona('spunta', 16);
    } else if (i === indice) {
      r.classList.add('attiva');
    }
  });
  if (indice >= 0 && messaggio) righe[indice].querySelector('.fase-testo').textContent = messaggio;
}

function fineUI() {
  $('#btn-cook').disabled = false;
  $('#btn-cook').classList.remove('in-corso');
  $('#pannello-avanzamento').hidden = true;
}

// ---------------------------------------------------------------------------
// Scheda ricetta
// ---------------------------------------------------------------------------

function mostraRicetta(ricetta, avvertenze = [], modello = '') {
  ricettaCorrente = ricetta;
  const scheda = $('#scheda-ricetta');

  const copertina = ricetta.immagini?.[0]
    ? `<img class="scheda-copertina" src="data:image/jpeg;base64,${ricetta.immagini[0]}" alt="" />`
    : '';

  const meta = [];
  if (ricetta.porzioni) meta.push(`<span>${icona('piatto', 16)} ${esc(ricetta.porzioni)}</span>`);
  if (ricetta.tempo_totale_min) meta.push(`<span>${icona('tempo', 16)} ${ricetta.tempo_totale_min} min</span>`);
  if (ricetta.fonte?.autore) meta.push(`<span>${icona('autore', 16)} ${esc(ricetta.fonte.autore)}</span>`);

  scheda.innerHTML = `
    ${copertina}
    <div class="scheda-corpo">
      <h2 class="scheda-titolo">${esc(ricetta.titolo)}</h2>
      <div class="scheda-meta">${meta.join('')}${modello ? `<span class="badge-fonte">${icona('modello', 16)} ${esc(modello)}</span>` : ''}</div>
      ${avvertenze?.length ? `<div class="avviso-incertezze"><strong>Nota:</strong> ${avvertenze.map(esc).join(' ')}</div>` : ''}
      <h3 class="sezione-titolo">Ingredienti</h3>
      ${renderIngredienti(ricetta)}
      <h3 class="sezione-titolo">Procedimento</h3>
      <ol class="lista-procedimento">${(ricetta.procedimento || []).map((p) => `<li class="passo">${esc(p)}</li>`).join('')}</ol>
      ${renderLacune(ricetta)}
      <div class="scheda-azioni">
        <button class="btn-primario" id="btn-salva-scheda">${icona('salva')} Salva nel ricettario</button>
        <button class="btn-secondario" id="btn-modifica-scheda">${icona('correggi')} Correggi</button>
        <button class="btn-secondario" id="btn-export-scheda">${icona('scarica')} Scarica per Mela</button>
        <button class="btn-secondario" id="btn-export-pdf">${icona('pdf')} PDF</button>
        <button class="btn-secondario" id="btn-export-md">${icona('markdown')} Markdown</button>
        ${ricetta.id ? `<button class="btn-pericolo" id="btn-elimina-scheda">${icona('elimina')} Elimina</button>` : ''}
      </div>
    </div>`;

  scheda.hidden = false;
  scheda.scrollIntoView({ behavior: 'smooth', block: 'start' });

  $('#btn-salva-scheda').onclick = salvaRicettaCorrente;
  $('#btn-modifica-scheda').onclick = () => apriModifica(ricettaCorrente);
  $('#btn-export-scheda').onclick = () => exportRicettaCorrente('mela');
  $('#btn-export-pdf').onclick = () => exportRicettaCorrente('pdf');
  $('#btn-export-md').onclick = () => exportRicettaCorrente('markdown');
  // Presente solo per le ricette già salvate: non si elimina ciò che non è ancora nel
  // ricettario — per quello basta non salvarlo.
  if ($('#btn-elimina-scheda')) $('#btn-elimina-scheda').onclick = () => eliminaRicettaCorrente();
}

function renderIngredienti(ricetta) {
  const gruppi = [...new Set((ricetta.ingredienti || []).map((i) => i.gruppo))];
  const mostraGruppi = gruppi.filter(Boolean).length > 0 && gruppi.length > 1;
  let html = '<ul class="lista-ingredienti">';
  for (const gruppo of gruppi) {
    if (mostraGruppi && gruppo) html += `<li class="gruppo-titolo">${esc(gruppo)}</li>`;
    for (const ing of ricetta.ingredienti.filter((i) => i.gruppo === gruppo)) {
      const incerta = PROVENIENZE_STIMA.has(ing.quantita?.provenienza);
      const tag = incerta
        ? `<span class="tag-provenienza stima">stima</span>`
        : '';
      html += `<li class="ingrediente${incerta ? ' incerta' : ''}">
        <span>${esc(ing.riga)}</span>${tag}</li>`;
    }
  }
  return html + '</ul>';
}

function renderLacune(ricetta) {
  if (!ricetta.lacune?.length) return '';
  return `<h3 class="sezione-titolo">Da verificare</h3>
    <ul class="lista-lacune">${ricetta.lacune.map((l) => `<li class="lacuna">${esc(l)}</li>`).join('')}</ul>`;
}

// ---------------------------------------------------------------------------
// Salvataggio, modifica, export
// ---------------------------------------------------------------------------

async function salvaRicettaCorrente() {
  try {
    const { id } = await api('/api/ricette', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ricettaCorrente),
    });
    ricettaCorrente.id = id;
    toast('Salvata nel ricettario.');
    caricaLibreria();
  } catch (e) { toast(e.message, true); }
}

async function eliminaRicettaCorrente() {
  if (!ricettaCorrente?.id) return;
  // Conferma esplicita: è l'unica azione distruttiva dell'interfaccia e non si può
  // annullare. Il titolo nel messaggio evita di cancellare la ricetta sbagliata.
  if (!confirm(`Eliminare «${ricettaCorrente.titolo}» dal ricettario?\n\nL'operazione non è reversibile.`)) return;
  try {
    await api(`/api/ricette/${ricettaCorrente.id}`, { method: 'DELETE' });
    $('#scheda-ricetta').hidden = true;
    ricettaCorrente = null;
    toast('Ricetta eliminata.');
    caricaLibreria();
  } catch (e) { toast(e.message, true); }
}

async function exportRicettaCorrente(formato = 'mela') {
  // Una ricetta si scarica solo se è già nel ricettario: l'export parte dal database,
  // non da quello che c'è a schermo.
  if (!ricettaCorrente.id) await salvaRicettaCorrente();
  window.location.href = indirizzo(`/api/ricette/${ricettaCorrente.id}/export?formato=${formato}`);
}

function apriModifica(ricetta) {
  const contenuto = $('#modale-contenuto');
  // Modifica testuale: ingredienti e passi uno per riga. Semplice e diretto — chi corregge
  // vuole aggiustare due parole, non compilare un form a venti campi.
  const righeIng = (ricetta.ingredienti || []).map((i) => i.riga).join('\n');
  const righeProc = (ricetta.procedimento || []).join('\n');

  contenuto.innerHTML = `
    <h2 class="scheda-titolo">Correggi la ricetta</h2>
    <p class="suggerimento-modifica">Un ingrediente per riga (es. "200 g farina 00"), un passo per riga.
       Usa "# Titolo" per iniziare un gruppo di ingredienti.</p>
    <div class="campo-modifica">
      <label>Titolo</label>
      <input id="mod-titolo" value="${esc(ricetta.titolo)}" />
    </div>
    <div class="campo-modifica">
      <label>Porzioni</label>
      <input id="mod-porzioni" value="${esc(ricetta.porzioni || '')}" />
    </div>
    <div class="campo-modifica">
      <label>Ingredienti</label>
      <textarea id="mod-ingredienti">${esc(righeIng)}</textarea>
    </div>
    <div class="campo-modifica">
      <label>Procedimento</label>
      <textarea id="mod-procedimento">${esc(righeProc)}</textarea>
    </div>
    <div class="scheda-azioni">
      <button class="btn-primario" id="btn-salva-modifica">Salva le correzioni</button>
      <button class="btn-testo" id="btn-chiudi-modale">Annulla</button>
    </div>`;

  $('#modale').hidden = false;
  $('#btn-chiudi-modale').onclick = () => ($('#modale').hidden = true);
  $('#btn-salva-modifica').onclick = () => applicaModifiche(ricetta);
}

function applicaModifiche(ricetta) {
  // Le correzioni testuali sostituivano l'estratto: le righe modificate diventano il
  // testo "riga" di ciascun ingrediente. La conversione è già avvenuta; qui l'utente
  // ha l'ultima parola, e la sua parola vince.
  ricetta.titolo = $('#mod-titolo').value.trim() || ricetta.titolo;
  ricetta.porzioni = $('#mod-porzioni').value.trim() || null;

  let gruppo = null;
  ricetta.ingredienti = $('#mod-ingredienti').value.split('\n')
    .map((r) => r.trim()).filter(Boolean)
    .map((riga) => {
      if (riga.startsWith('#')) { gruppo = riga.replace(/^#\s*/, ''); return null; }
      return {
        nome: riga, gruppo,
        note: null, lacuna: null, riga,
        quantita: { provenienza: 'dichiarato', valore: null, unita: null,
                    testo_originale: riga, nota: null, incerta: false },
      };
    })
    .filter(Boolean);

  ricetta.procedimento = $('#mod-procedimento').value.split('\n').map((r) => r.trim()).filter(Boolean);

  $('#modale').hidden = true;
  mostraRicetta(ricetta, [], '');
  toast('Correzioni applicate. Ricordati di salvare.');
}

// ---------------------------------------------------------------------------
// Libreria
// ---------------------------------------------------------------------------

async function caricaLibreria(cerca = '') {
  try {
    const voci = await api('/api/ricette' + (cerca ? `?cerca=${encodeURIComponent(cerca)}` : ''));
    const griglia = $('#griglia-ricette');
    $('#libreria-vuota').hidden = voci.length > 0;
    $('#libreria-vuota').textContent = cerca
      ? `Nessuna ricetta trovata per «${cerca}».`
      : 'Il ricettario è vuoto. Incolla il link di un reel qui sopra e premi Cook per iniziare.';

    griglia.innerHTML = voci.map((v) => {
      const copertina = v.copertina
        ? `style="background-image:url('data:image/jpeg;base64,${v.copertina}')"`
        : '';
      const meta = [
        v.porzioni, v.tempo_totale_min ? `${v.tempo_totale_min} min` : null,
        `${v.n_ingredienti} ingr.`,
      ].filter(Boolean).join(' · ');
      return `<article class="carta-ricetta" data-id="${v.id}">
        <div class="carta-copertina" ${copertina}>${v.copertina ? '' : icona('piatto', 34)}</div>
        <div class="carta-corpo">
          <div class="carta-titolo">${esc(v.titolo)}</div>
          <div class="carta-meta">
            <span>${esc(meta)}</span>
            ${v.ha_incertezze ? `<span class="carta-badge-incerta">${icona('avviso', 14)} da rivedere</span>` : ''}
          </div>
        </div>
      </article>`;
    }).join('');

    $$('.carta-ricetta').forEach((c) => c.onclick = () => apriDallaLibreria(c.dataset.id));
  } catch (e) { toast(e.message, true); }
}

async function apriDallaLibreria(id) {
  try {
    const ricetta = await api(`/api/ricette/${id}`);
    mostraRicetta(ricetta, [], '');
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------------------
// Piccole utilità
// ---------------------------------------------------------------------------

function esc(testo) {
  const d = document.createElement('div');
  d.textContent = testo ?? '';
  return d.innerHTML;
}

let _cercaTimer;
function ricercaLibreria(valore) {
  clearTimeout(_cercaTimer);
  _cercaTimer = setTimeout(() => caricaLibreria(valore.trim()), 250);
}

// ---------------------------------------------------------------------------
// Collegamenti degli eventi
// ---------------------------------------------------------------------------

function collega() {
  $('#btn-cook').onclick = cookDaUrl;
  $('#input-url').addEventListener('keydown', (e) => { if (e.key === 'Enter') cookDaUrl(); });

  $('#btn-opzioni').onclick = () => {
    const o = $('#opzioni');
    o.hidden = !o.hidden;
    $('#btn-opzioni').textContent = o.hidden ? 'Opzioni ▾' : 'Opzioni ▴';
  };

  $('#input-file').onchange = (e) => { if (e.target.files[0]) cookDaFile(e.target.files[0]); };
  $('#input-cerca').addEventListener('input', (e) => ricercaLibreria(e.target.value));
  $('#btn-export-tutte').onclick = () => (window.location.href = indirizzo('/api/export'));

  // Trascina-e-rilascia su tutta la pagina.
  const overlay = $('#drop-overlay');
  let contatore = 0;
  window.addEventListener('dragenter', (e) => { e.preventDefault(); if (++contatore === 1) overlay.hidden = false; });
  window.addEventListener('dragleave', (e) => { e.preventDefault(); if (--contatore === 0) overlay.hidden = true; });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault(); contatore = 0; overlay.hidden = true;
    if (e.dataTransfer.files[0]) cookDaFile(e.dataTransfer.files[0]);
  });

  // Chiudi la modale cliccando sullo sfondo.
  $('#modale').addEventListener('click', (e) => { if (e.target.id === 'modale') $('#modale').hidden = true; });
}

// ---------------------------------------------------------------------------
// Avvio
// ---------------------------------------------------------------------------

riempiIcone();   // le icone dei pezzi statici di index.html (marchio, Cook, area di rilascio)
collega();
aggiornaStato();
caricaLibreria();
