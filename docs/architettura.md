# Architettura

Il *perché* delle scelte. Per il *cosa* c'è il [README](../README.it.md); per gli aspetti legali
c'è [`legale.md`](legale.md).

---

## La pipeline

```
  URL reel ──┐
  file ──────┼──▶ acquire ──▶ Media (video/audio + didascalia + autore + url)
  cartella ──┘                    │
                                  ├──▶ audio ──▶ WAV 16kHz ──▶ asr ──▶ Trascrizione
                                  │                                        │
      didascalia + trascrizione ─┴────────────────────────────────────────┘
                     │
                     ▼
                 extract  (LLM locale via Ollama, uscita vincolata a schema JSON)
                     │
                     ▼   RecipeDraft — quantità GREZZE, mai convertite dal modello
                  units    ← data/unita.yaml + densita.yaml + vaghe.yaml (lingua × sistema)
                     │
                     ▼   Ricetta — quantità metriche + provenienza + lacune
              ┌──────┴──────┬─────────────┐
              ▼             ▼             ▼
            store         mela        documenti
          (SQLite)  (.melarecipe)   (.md / .pdf)
```

Ogni fase è un modulo indipendente in `src/reel2recipe/`. La catena è cablata una sola volta,
in `pipeline.py`, e la usano identica sia la CLI (`cli.py`) sia l'interfaccia web (`api.py`):
una sola implementazione, un solo posto dove correggere.

---

## Le decisioni che contano

### 1. L'LLM estrae, il codice converte

È il principio centrale, quello da cui discende la qualità percepita. Un LLM che converte
"1 cup di farina" in grammi produce un numero plausibile e spesso sbagliato, perché ricorda
invece di calcolare. Quindi:

- Il modello riporta la quantità **come compare** (`quantita_raw`, `unita_raw`) e non
  converte mai.
- `units.py` converte con tabelle deterministiche e versionate (`data/`).
- Senza densità nota per un ingrediente, la conversione volume→peso **non si fa**: si
  conserva il volume e si dichiara la lacuna. Mai una densità inventata.

Ogni quantità porta la sua **provenienza** (`dichiarato`, `convertito:densita`,
`stimato:vaghe`, `indeterminato`, …), che interfaccia ed export usano per distinguere a colpo
d'occhio un dato da una stima.

**La regola d'oro: non inventare.** Vale per il modello e per il codice, e non solo per le
quantità. Se un peso, un tempo o un passaggio non è deducibile dal materiale, non si completa
a caso: si lascia il buco e lo si dichiara fra le `lacune`. Una ricetta incompleta ma onesta
è utilizzabile; una completata a caso è dannosa, perché in cucina un peso sbagliato di cui non
sai che è sbagliato fa danni veri. Il prompt di `extract.py` lo impone al modello, `units.py`
e `recipe.py` lo rispettano nel codice, e `tests/test_modello.py` lo verifica sul modello
locale davvero installato — è il gate che protegge la promessa centrale del progetto.

Anche le tabelle seguono la stessa disciplina: **ogni densità in `data/densita.yaml` dichiara
la sua `fonte`**, e un test lo pretende. Un numero senza provenienza è un numero di cui non ci
si può fidare.

**Due assi, non uno: `sistema` e `lingua`.** Il prodotto lavora in italiano/inglese e in
metrico/imperiale, e i due assi restano separati perché non coincidono (un australiano legge
in inglese ma cucina in grammi). Il **sistema** decide i numeri — si fissa alla conversione,
in `units.py`, e si applica alla quantità *grezza*: verso l'imperiale non si attraversa la
densità e le quantità si scrivono a frazioni (`3/4 cup`), perché un misurino non ha lo 0,75.
La **lingua** decide le parole: etichette delle unità, misure a occhio e messaggi di lacuna.
Le prime due vivono in `data/` indicizzate per lingua e per sistema; i messaggi in `units.py`
(sono stringhe di programma, non dati). Le temperature seguono il sistema in entrambi i sensi
(°F↔°C). La traduzione dei nomi e del procedimento la fa il modello in `extract.py`, con un
prompt di sistema per lingua — ed è l'unico pezzo non deterministico del percorso, quindi il
meno affidabile.

**Un terzo asse, che non appartiene a questa coppia: la lingua *parlata* nel reel.** Riguarda
l'ingresso, non l'uscita, e per questo si chiama `lingua_audio` e non `lingua`: serve solo a
Whisper. Il predefinito è `None`, cioè *riconoscila da sé*, che è ciò che Whisper sa fare
nativamente e riporta in `Trascrizione.lingua`. **Non si deduce dalla lingua di uscita**: un
reel inglese che diventa una ricetta italiana è il caso normale, non l'eccezione, e legare i
due assi significherebbe dichiarare a Whisper una lingua falsa ogni volta che si traduce.
Qui c'era un `"it"` cablato che nessuna opzione poteva togliere, e il danno non era una
traduzione storta ma una **trascrizione** storta — parole italiane forzate su suoni inglesi,
con tutto il resto della catena che lavorava su quella. Invisibile a valle, perché il modello
locale produce comunque una ricetta plausibile.

### 2. La lettura viene prima della conversione

Sei estrazioni su reel veri hanno prodotto quattro difetti, e **nessuno era nel motore di
conversione**. Erano tutti casi in cui il modello metteva la cosa giusta nel campo sbagliato e
il codice la leggeva alla lettera. È una distinzione che vale la pena tenere a mente, perché
davanti a un numero sbagliato la tentazione è mettere le mani in `units.py` — e quattro volte
su quattro sarebbe stata l'analisi sbagliata.

Per questo `normalizza_ingrediente` è un **involucro** che rimette in sesto l'ingresso prima
di chiamare `_normalizza_ingrediente`, che è il motore vero. Con una coppia coerente il motore
fa già la cosa giusta, e la parte più delicata del progetto resta intatta.

Cosa raddrizza l'involucro:

- **Quantità e unità che si contraddicono.** Le didascalie scrivono spesso la stessa dose due
  volte — «1¼ cups (300 ml) water» — e il modello ne mescola i pezzi. Ne usciva "1 ml" d'acqua
  al posto di 300, con provenienza `dichiarato`: un numero sbagliato presentato come certo.
  **Vince la coppia internamente coerente** («1¼» e «cups» stanno nello stesso pezzo di testo,
  il «ml» viene da un'altra parte della frase) e **la discrepanza si dichiara comunque**, anche
  quando la scelta azzecca il valore: lì la fonte era ambigua e chi cucina deve saperlo. Fuori
  da questo caso la politica non cambia: se il modello ha isolato l'unità, la sua resta quella
  buona.
- **Una parola fra parentesi di solito non è un'unità — ma va guardata dentro.**
  «1 melanzana bianca (facoltativa)» diventava «1 (facoltativa) melanzana bianca». La prima
  versione di questa regola diceva «nessuna unità di misura si scrive fra parentesi» e si
  fermava lì, perché sembra un criterio più economico e più sicuro di un vocabolario. Era
  falsa: il modello scrive anche `unita_raw="(g)"`, e siccome la normalizzazione toglie già
  le parentesi, prima di quel controllo «200» + «(g)» si convertiva correttamente.
  Degradarlo a nota faceva di «200 g di farina» un conteggio di duecento farine, **senza
  nemmeno una lacuna** — la regressione è durata mezza giornata ed è stata trovata da una
  rilettura a freddo, non dai test. Ora si guarda il contenuto: se è un'unità nota, non si
  tocca niente.
- **Una misura finita nel campo sbagliato è comunque un'indicazione.** Il modello ha tre modi
  di sbagliare campo, visti tutti e tre: dentro il nome («semi di sesamo q.b.»), fra parentesi
  nel nome («sale (un pizzico)») e — quando proprio non sa dove metterla — nelle `note`. In
  tutti e tre i casi la quantità arrivava vuota e la ricetta dichiarava «quantità non indicata
  nel reel»: **una lacuna falsa**. Diventano una quantità indeterminata o una stima dichiarata.
  Il criterio è che il testo sia una misura **nota** a `vaghe.yaml`, non che stia in un certo
  campo: «burro (a temperatura ambiente)» resta una nota. E il confronto è **esatto e ancorato
  in coda**, mai per contenimento, o «pomodori poco maturi» diventerebbe una quantità
  indeterminata perché una parola vaga compare nel mezzo. Fra parentesi si pretendono inoltre
  **almeno due parole**: molte voci di `vaghe.yaml` hanno alias di una parola sola — noce,
  tazza, bicchiere, filo — che dopo un nome ne indicano la varietà o il recipiente, non la
  dose. «frutta secca (noce)» non è dieci grammi di frutta secca.

Il filo comune è il criterio più importante emerso da quelle prove: **una lacuna falsa è
peggio di nessuna lacuna**, perché insegna a non fidarsi nemmeno di quelle vere — e su quel
meccanismo poggia l'onestà dell'intero prodotto.

Questi difetti erano stati scoperti solo perché qualcuno stava guardando: nessun test copriva
il prompt e lo schema di `extract.py`. Ora li copre `tests/test_modello.py`, con didascalie
**sintetiche** che riproducono i pattern senza portare in repo materiale di terzi. Non è
teoria: la quarta variante — «q.b.» finito nelle `note` — l'ha trovata quella suite alla sua
prima esecuzione, non un reel.

### 3. Quando il prompt e lo schema si contraddicono, vince lo schema

`porzioni` e i tempi uscivano sempre vuoti, anche da fonti che dicevano «Serves 2» o «180° per
25'-30'». Il prompt insisteva, il mapping era corretto: il colpevole era lo **schema JSON**,
dove quei campi erano opzionali. Con l'uscita vincolata a schema un campo opzionale il modello
è libero di ometterlo, e `qwen2.5:14b` lo ometteva sistematicamente. Il prompt chiede, lo
schema concede: **lo schema è il vincolo meccanico sulla decodifica, il prompt è una
preghiera.**

Ma il rimedio ha un costo simmetrico. Reso obbligatorio, `tempo_preparazione_min` veniva
**inventato** — 15 e 30 minuti su fonti che non dichiaravano alcuna preparazione, spezzando un
intervallo di cottura fra i due campi. Quindi si obbliga solo dove il dato è di norma presente
nelle fonti: `porzioni` e `tempo_cottura_min` sì, `tempo_preparazione_min` no. Si perde
qualche tempo di preparazione realmente dichiarato, e va bene così: **un tempo mancante è meno
dannoso di uno inventato.**

**Obbligare un campo non basta: bisogna anche dirgli che forma avere.** `porzioni` è diventato
obbligatorio ma i prompt non ne parlavano affatto, e il modello improvvisava una frase intera —
«These ingredients make 6 burgers.» invece di «6 burger», in un campo che le app di ricette
mostrano accanto al titolo. Una riga di istruzione con tre esempi ha chiuso la questione su
cinque fonti su cinque. Vale la regola generale: se un campo esce sistematicamente in una forma
sbagliata, prima di dare la colpa al modello si controlla se qualcuno gli ha mai detto cosa
scriverci.

### 4. Tutto locale, per scelta e non per ripiego

Trascrizione con Whisper sulla macchina, strutturazione con un LLM via Ollama. Nessun
servizio a pagamento, nessuna chiave API, nessun dato che esce dal PC. Il vincolo è esplicito
dell'utente: il prodotto deve continuare a funzionare anche se domani si smette di pagare
qualsiasi abbonamento. Ne consegue che il "cervello" è Ollama (obbligatorio) e non un'API
remota.

### 5. La pipeline degrada, non si ferma

Se l'audio manca, o la trascrizione fallisce, o un backend non è installato, la lavorazione
**prosegue con la sola didascalia** e lo dichiara. Moltissimi reel di cucina hanno la ricetta
completa nel testo del post: rinunciare per un problema audio significherebbe perdere una
ricetta recuperabile. Ogni fallimento non fatale diventa un'*avvertenza*, non un'eccezione.

### 6. Trascrizione con doppio backend e fallback

`asr.py` espone un'interfaccia unica su due implementazioni locali:

- **mlx-whisper** — GPU dei Mac Apple Silicon (Metal), molto più veloce dove disponibile.
- **faster-whisper** — CPU, portabile ovunque, il riferimento.

Con `backend="auto"` si usa il più veloce disponibile e si ripiega sull'altro se il primo
fallisce a runtime. Anche questo era una richiesta esplicita: massima copertura.

### 7. Frontend statico, niente build

L'interfaccia è una pagina sola (HTML + CSS + JS a moduli ES, in `web/`), servita da FastAPI.
Niente React, niente Vite, niente `node_modules`, niente toolchain da mantenere. PersonalFinance
usa React perché ha decine di pagine; qui sarebbe sovradimensionato. Se un domani servirà, si
migra allora.

L'estrazione è lunga (download + trascrizione + LLM), quindi non blocca la richiesta HTTP:
parte in un thread e l'avanzamento arriva alla pagina via Server-Sent Events. La barra *Cook*
racconta le fasi in tempo reale.

**L'interfaccia è bilingue, e il suo catalogo sta nel frontend** (`web/i18n.js`), non nel
server. Il criterio è *chi scrive la stringa la possiede*: le parole dei bottoni le scrive la
pagina, quelle dell'avanzamento e degli errori le scrive Python e restano in `pipeline.py` e
`api.py`. Portarle tutte nel server costringerebbe la pagina a un giro di rete prima di
potersi disegnare, con un lampo di testo non tradotto a ogni caricamento.

I due lati seguono però assi diversi, e la differenza è deliberata. La **pagina** segue la
lingua dell'interfaccia, che viaggia su ogni chiamata come `lingua_ui` — nome distinto da
`lingua`, che su `/api/cook` significa già un'altra cosa: in che lingua *produrre la ricetta*.
L'**avanzamento e le avvertenze** seguono invece la lingua della ricetta, perché finiscono
accanto alle `lacune`, che nella lingua della ricetta ci sono salvate dentro; farli divergere
darebbe una scheda mezza in una lingua e mezza nell'altra. Nell'uso normale i due valori
coincidono comunque, perché la lingua della ricetta segue quella dell'interfaccia.

Le chiamate all'API partono dalla base della pagina (`document.baseURI`) e non dalla radice
del sito. In locale è la stessa cosa; sotto l'Ingress di Home Assistant no, perché lì la
pagina vive dietro un prefisso con token e un `/api/stato` assoluto finirebbe sull'API di
Home Assistant invece che sulla nostra. Una riga di differenza, un guasto che altrimenti si
manifesta solo in produzione.

### 8. SQLite con ricerca full-text per la libreria

Il vero problema che il progetto risolve non è "estrarre una ricetta" ma **ritrovarla mesi
dopo**. Per questo la libreria è un database ricercabile (`store.py`, FTS5) e non una cartella
di file: cercare "zucchine" o "senza glutine" fra titoli, ingredienti e procedimenti è
esattamente ciò che serve quando si apre il frigo. La deduplica sull'URL di origine fa sì che
reimportare lo stesso reel aggiorni la ricetta invece di duplicarla.

L'indice FTS5 è una tabella standard (non *contentless*): tiene una copia del testo, in cambio
supporta la cancellazione e la modifica per riga — necessarie quando l'utente corregge una
ricetta. La duplicazione del testo è irrilevante per una libreria personale.

### 9. La revisione manuale è parte del flusso, non un ripiego

L'LLM propone, l'utente corregge, e **solo poi** si esporta. L'interfaccia permette di
modificare la ricetta prima di salvarla o esportarla; l'API espone `PUT /api/ricette/{id}`
per lo stesso scopo. Un modello locale da 7-14 miliardi di parametri sbaglia più spesso di
uno di frontiera: dare all'utente l'ultima parola non è una toppa, è il modo giusto di usare
uno strumento che assiste senza pretendere di essere infallibile.

### 10. Una sola decisione su dove vivono i dati

`paths.py` decide la radice di `workspace/` per tutti: libreria, media scaricati, export.
Prima la stessa riga (`parents[2] / "workspace"`) compariva identica in `store.py`,
`pipeline.py` e `api.py` — tre copie di un fatto solo, cioè tre occasioni di divergere.

Ce n'era anche una quarta, che la prima consolidazione si era lasciata sfuggire: il
predefinito di `r2r export --out`, per giunta **relativo**, quindi risolto rispetto alla
cartella corrente invece che al progetto. Nel container avrebbe scritto accanto al codice
mentre l'export dell'interfaccia web finiva sul volume persistente — due comandi che fanno
la stessa cosa in due posti diversi. È il modo tipico in cui una consolidazione resta a
metà: si accorpano le copie che si somigliano e sopravvive quella scritta in un'altra forma.

Serve perché la radice non è sempre accanto al repo. Dentro un container il codice sta in
sola lettura e i dati devono finire sul volume persistente: `R2R_WORKSPACE` lo dice senza che
il codice debba sapere dove sta girando. Le altre variabili (`R2R_COOKIES`,
`R2R_TIMEOUT_LLM`) rispondono alla stessa domanda per i cookie e per la pazienza da
concedere a un modello che gira su CPU; sono elencate nel README.

Il confine di sicurezza non si sposta con la radice: qualunque sia la cartella, lì dentro
c'è materiale di terzi e non si committa.

---

## Formato Mela — i due dettagli che rompono in silenzio

Il formato è documentato dall'autore su <https://mela.recipes/fileformat/>. Due cose vanno
sapute, perché sbagliarle non dà errore ma un import sbagliato:

1. `ingredients` e `instructions` sono **stringhe separate da `\n`**, non array. Una riga che
   inizia con `#` diventa un titolo di gruppo.
2. Il parser di Mela riconosce già quantità e unità **in italiano**. Quindi la forma giusta
   per un ingrediente è la stringa piana `"200 g farina 00"`: inventare una struttura nostra e
   ricomporla peggiorerebbe il risultato. Il testo fra parentesi Mela lo tratta come commento
   — ci mettiamo le note e gli equivalenti (`≈ 4 g`).

Entrambi sono protetti da test in `tests/test_mela.py`, ma il collaudo vero resta **aprire un
`.melarecipe` in Mela su iOS** e controllare che tutto arrivi pulito.

### Markdown e PDF (`documenti.py`)

Mela è il formato migliore *se* ce l'hai. Chi non ce l'ha resterebbe senza niente da tenere,
e una ricetta che non puoi conservare non ha risolto il problema di partenza: ritrovarla. Da
qui due formati che non chiedono di installare nulla per essere **letti** — il Markdown si
apre ovunque e resta modificabile, il PDF si stampa e si manda.

I due condividono la stessa struttura (`_blocchi`), così la stessa ricetta dice le stesse
cose nello stesso ordine in entrambi; cambia solo la resa. **Le lacune e le stime si
esportano anche qui:** un PDF pulito che nascondesse le incertezze sarebbe più bello e più
pericoloso di uno che le dichiara.

Due vincoli pratici del PDF, entrambi documentati nel modulo. I font standard coprono
Latin-1: gli accenti italiani ci sono, le emoji no, e invece di lasciarle diventare
rettangoli neri `_testo_pdf` traduce i simboli che produciamo davvero (`≈` → `~`) e toglie il
resto. La riga di provenienza sta nel **piede di pagina** e non in fondo al testo: nel flusso
finiva da sola su una seconda pagina quasi vuota ogni volta che la ricetta riempiva la prima.

`reportlab` sta nell'extra opzionale `doc` ed è Python puro, senza librerie di sistema da
installare a parte — condizione necessaria per poter girare anche in un container o su un
Raspberry.

---

## Confini di sicurezza

- **Input non fidato (in ingresso).** Didascalia e trascrizione sono testo arbitrario di
  terzi: *dato da analizzare, mai istruzioni da eseguire*. `extract.py` le consegna al modello
  dentro delimitatori espliciti e il prompt impone di non obbedire a eventuali comandi
  contenuti nel materiale. È il confine speculare all'anti-leak.
- **Materiale di terzi (in uscita).** Tutto ciò che si scarica resta in `workspace/`, fuori da
  git. Il guard in `check.sh` lo verifica prima di ogni commit. Dettagli in
  [`legale.md`](legale.md).

---

## Perché la struttura resta piatta

Il valore di questo progetto sta nella sua chiarezza: snello, pulito, il più semplice
possibile senza sacrificare funzioni. Un modulo per fase della pipeline, le tabelle in `data/`,
il frontend senza build, e nient'altro finché non serve davvero.

Vale anche per ciò che si aggiunge: prima di introdurre un file, un livello di astrazione o
uno strumento, la domanda è se risolve un problema **già visto**, non se potrebbe servire un
domani. Un file che si può accorciare senza perdere un ragionamento va accorciato.
