<p align="center">
  <img src="docs/brand/banner.svg" alt="Reel2Recipe" width="860">
</p>

<p align="center">
  <a href="README.md">English</a> · <strong>Italiano</strong>
</p>

# Reel2Recipe

> **Da leggere prima.** Progetto **personale**, pubblicato così com'è e **senza garanzie**:
> non è un prodotto finito né commerciale, e non lo diventerà. È scritto in gran parte **con
> un assistente IA**, sotto guida e revisione umana — era anche il punto.
>
> L'estrazione è automatica e può sbagliare. Il progetto è costruito per rendere visibili le
> incertezze invece di nasconderle, ma **rileggi la ricetta prima di cucinarla**, soprattutto
> pesi e tempi; e se hai allergie, torna alla fonte originale, che è sempre citata.
> Dettagli in [`docs/condizioni-uso.md`](docs/condizioni-uso.md).

**Dai reel di cucina di Instagram a un ricettario ordinato, importabile in [Mela](https://mela.recipes).**
Incolli un link, premi *Cook*, e ottieni una ricetta pulita — con gli ingredienti in grammi
e millilitri, il procedimento in italiano e la fonte originale sempre citata.

Nato da un problema concreto: si salvano decine di ricette su Instagram e poi non si
ritrovano più. Reel2Recipe le estrae, le rende ricercabili e le porta nell'app che usi
davvero per cucinare.

> **Tutto succede sul tuo computer.** Nessuna intelligenza artificiale online, nessun
> abbonamento, nessuna chiave API, nessun dato che lascia la macchina. Se un domani smetti
> di pagare qualsiasi servizio, Reel2Recipe continua a funzionare esattamente come prima.

## Lingue

**Italiano e inglese, su entrambi i lati dello strumento.**

- **L'interfaccia** esiste in tutte e due. Il selettore sta in alto a destra; la scelta viene
  ricordata, e alla prima apertura segue la lingua del browser.
- **Le ricette** si possono produrre nell'una o nell'altra, indipendentemente
  dall'interfaccia, e con misure **metriche** o **imperiali**.
- **Il reel di partenza** può essere parlato in entrambe, e non devi dire quale: la riconosce
  Whisper. Un reel inglese può diventare una ricetta italiana, e viceversa.

Sono tre assi distinti, descritti in
[Lingua e sistema di misura](#lingua-e-sistema-di-misura). Un limite da conoscere prima di
farci affidamento: tradurre i **nomi degli ingredienti** è la parte meno affidabile di tutta
la catena — vedi [la nota sui limiti](#onest%C3%A0-sui-limiti). I numeri restano giusti; sono
le parole a scivolare.

> **Una nota su questa documentazione.** Questo README e quello dell'add-on esistono in
> inglese e in italiano, due copie che si muovono insieme. Tutto il resto sta in una lingua
> sola, decisa dal suo pubblico: [`docs/architecture.md`](docs/architecture.md) è in inglese,
> perché spiega un codice i cui identificatori e commenti sono in inglese. I due documenti
> legali restano **facenti fede in italiano**, con un riassunto inglese non vincolante in
> testa: due versioni legali entrambe pubblicate che divergono sono un problema vero, non
> una questione di stile.

---

## Cosa fa, in breve

1. **Prende un reel** — da un link, da un file video che hai già salvato, o da un'intera
   cartella (modalità batch, per smaltire l'arretrato).
2. **Legge tutto** — la didascalia del post e il parlato del video (trascritto con Whisper,
   in locale).
3. **Ricostruisce la ricetta** — con un modello di linguaggio locale (via [Ollama](https://ollama.com)):
   titolo, ingredienti, procedimento, porzioni e tempo di cottura. Il tempo di *preparazione*
   si estrae solo quando la fonte lo dichiara in modo netto: costringere il modello a
   riempirlo lo portava a inventarlo, e un tempo mancante è meno dannoso di uno sbagliato.
4. **Converte le quantità** — "1 cup di farina" diventa "120 g", "2 tbsp d'olio" diventa
   "2 cucchiai (≈ 30 ml)". La conversione è **deterministica**, basata su tabelle di densità
   verificate, non indovinata dal modello (v. [Il principio](#il-principio-che-conta)).
5. **Archivia e cerca** — tutte le ricette in un ricettario locale ricercabile.
6. **Esporta per Mela** — in formato `.melarecipe`, con gruppi di ingredienti, tempi e link
   alla fonte.

---

## Installazione

Serve **[uv](https://docs.astral.sh/uv/)** (il resto lo installa lo script).
Da terminale, nella cartella del progetto:

```bash
./install.sh
```

Lo script controlla e, dove può, installa da sé tutto il necessario:

| Componente | A cosa serve | Obbligatorio? |
|---|---|---|
| **uv** | gestore del progetto Python | sì |
| **Ollama** + un modello | il "cervello" che struttura la ricetta | sì |
| **ffmpeg** | estrae l'audio dai video | per il parlato (senza, usi le didascalie) |
| **Whisper** (locale) | trascrive il parlato | per il parlato |

Dove non può installare da solo (per esempio se manca Homebrew su macOS), lo script ti dice
esattamente cosa fare. Puoi rilanciarlo quante volte vuoi: è idempotente.

Per controllare in ogni momento cosa è pronto:

```bash
uv run r2r check
```

---

## Uso

### Interfaccia web (consigliata)

```bash
uv run r2r serve
```

Poi apri **http://localhost:8500**. Incolla il link di un reel nella barra, premi *Cook*, e
segui l'estrazione fase per fase. Quando la ricetta è pronta puoi **correggerla a mano**
(il modello propone, tu hai l'ultima parola), salvarla nel ricettario o scaricarla per Mela.

Puoi anche **trascinare un video** direttamente nella pagina.

### Da terminale

```bash
# Estrai una ricetta da un link e salvala in libreria
uv run r2r cook https://www.instagram.com/reel/XXXXX/

# Da un file già salvato, con la didascalia incollata
uv run r2r cook ~/Video/reel.mp4 --caption "1 cup farina, 2 uova..."

# Molti reel in serie: una cartella di video, o un .txt con un URL per riga
uv run r2r batch ~/Video/reel-da-lavorare/ --export workspace/export/
# (i file audio che Reel2Recipe estrae da sé vengono saltati: niente doppie lavorazioni)

# Cerca nel ricettario
uv run r2r list --search "zucchine"

# Esporta
uv run r2r export 42                    # una ricetta, per Mela
uv run r2r export --all                 # l'intero ricettario in un .melarecipes
uv run r2r export 42 --format pdf       # oppure markdown, o più formati insieme
uv run r2r export 42 --format markdown pdf mela

# Elimina una ricetta dal ricettario (chiede conferma; --yes per saltarla)
uv run r2r delete 42
```

> **I nomi dei comandi e delle opzioni sono in inglese**, come il resto della superficie
> pubblica. I vecchi nomi italiani restano accettati come alias — `--lingua`, `--sistema`,
> `--didascalia`, `--modello`, `--cerca`, `--formato`, `--tutte`, `--si`, `--porta` e il
> comando `elimina`, oltre alla variabile `R2R_PORTA` — quindi quello che hai già scritto o
> messo in uno script continua a funzionare.

### Se non usi Mela

`.melarecipe` è il formato migliore *se* hai Mela. Altrimenti la stessa ricetta esce in
**Markdown** (si apre ovunque e resta modificabile) o in **PDF** (si stampa e si manda),
dalla riga di comando con `--format` o dai bottoni sotto la scheda nell'interfaccia web.

Tutti e tre i formati riportano anche le **lacune** e le quantità che sono stime nostre: un
PDF pulito che nascondesse le incertezze sarebbe più bello e più pericoloso. Il Markdown non
richiede nulla; il PDF usa `reportlab`, che `./install.sh` installa da sé (a mano:
`uv sync --extra doc`).

### Lingua e sistema di misura

**L'interfaccia è bilingue**, italiano e inglese. Il selettore sta in testata, in alto a
destra: la scelta viene ricordata, e alla prima apertura si parte dalla lingua del browser.

Da quella scelta scende una catena di tre anelli, ciascuno con il precedente come ripiego:
l'**interfaccia** decide la lingua della **ricetta**, che decide il **sistema di misura**.
Chi non tocca nulla ottiene un insieme coerente; chi vuole incrociarli può farlo a ogni
anello — interfaccia in inglese e ricette in italiano è una combinazione legittima, e per
chi cucina in una lingua e vive in un'altra è anzi quella giusta.

Da riga di comando l'interfaccia non c'è, quindi gli assi sono due e partono dalla ricetta:

```bash
uv run r2r cook <url> --language en                    # ricetta in inglese, misure imperiali
uv run r2r cook <url> --language en --system metric    # inglese, ma con grammi e ml
uv run r2r cook <url> --system imperial                # italiano, ma con cup e once
```

Nell'interfaccia web gli stessi due selettori stanno nelle *Opzioni*, e di base seguono
l'anello che li precede. Il sistema, se non lo scegli, segue la lingua (italiano → metrico,
inglese → imperiale), ma puoi incrociarli: un inglese o un australiano legge in inglese e
cucina in grammi.

C'è poi un terzo asse che non c'entra con questi due, perché riguarda l'**ingresso**: la
lingua *parlata* nel reel, che serve a Whisper per trascrivere. Di base non gliela si dichiara
affatto — la riconosce da sé, che è la cosa che sa fare — e questo è ciò che permette di
lavorare un reel inglese e ottenerne una ricetta italiana. Non segue la lingua di uscita,
perché tradurre è il caso normale. Si può forzare quando il riconoscimento sbaglia, per
esempio su un audio molto corto o rumoroso:

```bash
uv run r2r cook <url> --spoken-language en    # è parlato in inglese, non indovinare
```

La differenza fra i due assi è netta. Il **sistema** cambia i numeri e lo fa il codice, in
modo deterministico: "1 cup di farina" diventa 120 g in metrico e resta "1 cup" in imperiale,
scritto a frazioni ("2 1/2 cup"), come su un misurino. La **lingua** cambia le parole. Le
etichette delle misure, le sezioni degli export e i messaggi sono sempre tradotti; i nomi
degli ingredienti e il procedimento li traduce il modello locale al momento dell'estrazione,
ed è la parte meno solida — vedi la nota qui sotto.

#### Onestà sui limiti

> La traduzione dei nomi e del procedimento è la parte meno affidabile,
> ed è l'unica non deterministica dell'intero percorso. Su una fonte **già italiana** la
> qualità è ottima. Su una fonte **inglese** i nomi degli ingredienti sbagliano con una certa
> regolarità: `berries` è diventato "fragole", `flax seeds` "semi di lecithia" (parola
> inesistente), `a pinch` "una pizzetta". Una didascalia **bilingue** peggiora le cose, perché
> il modello pesca da entrambe le lingue: da un post inglese-tedesco è uscito "dinkel fette".
> **Verso l'inglese**, da un testo tutto italiano, `qwen2.5:14b` tende a restare ancorato
> all'italiano: traduce il titolo ma non sempre l'elenco.
>
> In tutti questi casi **le quantità restano corrette**: sbagliano le parole, non i numeri.
> È la ragione per cui la conversione non è affidata al modello, e per cui la revisione prima
> dell'export non è un ripiego ma parte del flusso.

### Reel privati

Per i reel che richiedono l'accesso, passa i cookie del browser in cui hai effettuato il login:

```bash
uv run r2r cook <url> --cookies chrome    # o safari, firefox
```

Dove un browser non c'è — dentro un container, per esempio — esporta i cookie in formato
Netscape e indica il file con `R2R_COOKIES=/percorso/cookies.txt`. Se la variabile punta a un
file che non esiste, l'errore lo dice subito invece di far fallire il download senza motivo
apparente.

### Variabili d'ambiente

Poche, e servono tutte a far girare il prodotto dove i percorsi predefiniti non vanno bene.

| variabile | effetto |
|-----------|---------|
| `R2R_WORKSPACE` | Sposta la radice dei dati (libreria, media, export). Predefinito: `workspace/` accanto al repo |
| `R2R_COOKIES` | File di cookie in formato Netscape per i reel che richiedono l'accesso. Non viene mai modificato: se ne usa una copia temporanea, cancellata a fine scaricamento |
| `R2R_TIMEOUT_LLM` | Secondi concessi al modello per una risposta — solo la cifra. Predefinito 300: da alzare su CPU senza acceleratore |
| `R2R_PORT` | Porta dell'interfaccia avviata da `tools/serve.sh`. Predefinito 8500. Il vecchio `R2R_PORTA` viene ancora letto |

### Home Assistant

C'è un add-on che fa girare tutto — interfaccia, Whisper e Ollama — su un server sempre
acceso, con l'interfaccia nel pannello laterale:
**[Stinocon/addons](https://github.com/Stinocon/addons/tree/master/reel2recipe)**. Serve una
macchina amd64 con 16 GB di RAM: l'inferenza gira su CPU.

---

## Come importare in Mela

Reel2Recipe produce file `.melarecipe` (una ricetta) o `.melarecipes` (più ricette, in uno
zip). Per importarli:

1. Salva il file esportato dove Mela può raggiungerlo (AirDrop, iCloud Drive, email a te
   stesso…).
2. Aprilo su iPhone/iPad/Mac: Mela lo riconosce e propone l'importazione.

Il parser di Mela legge già le quantità in italiano, quindi gli ingredienti arrivano con la
loro misura e i gruppi ("Per la base", "Per la crema") vengono rispettati. Il **link alla
fonte** è sempre incluso, così puoi tornare al reel originale.

---

## Il principio che conta

Il pezzo di cui questo progetto va più fiero è la **conversione delle quantità**, ed è dove
si distingue da un semplice "chiedi a un'IA di trascrivere la ricetta".

Un modello di linguaggio a cui chiedi "quanti grammi sono una tazza di farina?" ti dà un
numero *plausibile*. A volte 120, a volte 128, a volte 150 — e per lo zucchero magari
ripete lo stesso numero della farina, che è sbagliato del **67%** (stesso volume, densità
diverse). Il modello non sta calcolando: sta ricordando male.

Reel2Recipe fa una cosa diversa:

- Il modello riporta la quantità **esattamente come compare** nel reel ("1", "cup") e **non
  la converte mai**.
- La conversione la fa un modulo deterministico, con **tabelle di densità verificate** (una
  per ingrediente). Ogni densità cita la fonte da cui viene — il database USDA FoodData
  Central o la tabella dei pesi di King Arthur Baking — con il peso per cup da cui è
  calcolata, così puoi andare a controllarla.
- Se non conosciamo la densità di un ingrediente, la quantità **non viene convertita in
  peso**: si conserva il volume e si dichiara la cosa. Non si inventa mai un numero.

Il risultato: ogni quantità porta con sé la sua provenienza — *dichiarata* dal reel,
*convertita* da tabella, o *stimata* (per le misure a occhio come "un pizzico"). Le stime
sono sempre segnalate, così sai di quali fidarti. **Una lacuna dichiarata vale più di un
numero inventato**: in cucina un peso sbagliato di cui non sai che è sbagliato fa danni.

Le tabelle sono in [`data/`](data/) e sono leggibili e modificabili: se una densità non ti
convince, la correggi lì — dichiarando la fonte, che i test pretendono.

---

## Cosa è lecito, cosa no

Reel2Recipe è pensato per **uso personale**, su contenuti che **tu hai già salvato**.
Le condizioni rivolte a chi usa lo strumento stanno in
[`docs/condizioni-uso.md`](docs/condizioni-uso.md); l'analisi giuridica che sta dietro alle
scelte di progetto in [`docs/legale.md`](docs/legale.md). Entrambi fanno fede in italiano e
si aprono con un riassunto inglese. In breve:

- **Gli elenchi di ingredienti non sono protetti da copyright**: estrarli e riformattarli è
  lecito.
- **Il testo descrittivo di un creator sì**: per questo Reel2Recipe *riformula* il
  procedimento invece di copiarlo, e cita **sempre** la fonte originale.
- **Scaricare un reel da Instagram viola i Termini d'Uso della piattaforma.** È il motivo
  per cui questo strumento gira in locale, per uso personale: non è un servizio pubblico che
  scarica per conto di altri. Se lo userai su reel altrui, fallo con buon senso e per te.
- **I file scaricati restano sul tuo computer**: la cartella `workspace/` è esclusa da git e
  non viene mai condivisa.

---

## Struttura del progetto

```
src/reel2recipe/     il codice
  acquire.py         recupero del reel (URL, file, cartella)
  audio.py           estrazione audio con ffmpeg
  asr.py             trascrizione locale (Whisper) con fallback
  extract.py         strutturazione con LLM locale (Ollama)
  units.py           conversione deterministica delle quantità — il cuore del progetto
  recipe.py          il modello di una ricetta
  mela.py            export nel formato Mela
  documents.py       export in Markdown e PDF, per chi non usa Mela
  store.py           il ricettario (SQLite + ricerca full-text)
  paths.py           dove vivono i dati (una sola decisione, spostabile con R2R_WORKSPACE)
  pipeline.py        la catena completa
  api.py             l'interfaccia web
  cli.py             i comandi da terminale
data/                le tabelle di conversione (leggibili e modificabili)
web/                 l'interfaccia (HTML/CSS/JS, senza build)
  i18n.js            le parole dell'interfaccia, in italiano e in inglese
  icons.js           le icone SVG, incorporate (nessun CDN)
tools/               script di supporto (avvio di Ollama e dell'interfaccia, guard di confine)
docs/                documentazione: architettura in inglese, i due legali in italiano
tests/               i test
workspace/           i tuoi dati — mai condivisi (in .gitignore)
```

Documentazione tecnica: [`docs/architecture.md`](docs/architecture.md), in inglese come il codice.

### Se stai leggendo il codice

**Il codice è in inglese** — identificatori, commenti, test, script e documento di
architettura, le chiavi JSON sul disco, lo schema SQL, gli id e le classi del frontend e il
registro dell'add-on. L'italiano che resta è deliberato e sta in tre gruppi:

- **I prompt che legge il modello locale** — i due prompt di sistema di `extract.py` restano
  ciascuno nella propria lingua, perché un modello locale segue la lingua in cui gli si parla,
  e i delimitatori che recintano l'input non fidato restano italiani perché sono un confine di
  sicurezza tarato così. I **nomi dei campi** dello schema sono inglesi: sono struttura, non
  prosa. Qualsiasi cosa in quel file si muove solo insieme a una nuova esecuzione del gate.
- **Il vocabolario di cucina, che è dato** — `cucchiaio`, `farina 00`, `q.b.` in `data/*.yaml`,
  con gli alias inglesi accanto, e i pattern che rilevano le injection scritte in italiano.
- **Gli alias italiani della CLI**, tenuti come *sinonimi* e non come unica grafia (`--porta`,
  `--lingua`, `elimina`, e i valori `metrico`/`imperiale`), per chi li avesse in uno script o
  nella cronologia della shell.

Un quarto gruppo c'era e non c'è più: il **formato scritto sul disco**. Colonne SQL, chiavi
annidate delle ricette salvate, valori di `Provenance` e `System` sono passati all'inglese —
non con una rinomina ma con una migrazione e una rete di compatibilità permanente, perché
quella roba sta dentro la libreria dell'utente. Le URL e i parametri di query hanno lasciato
il gruppo degli alias per una ragione opposta e più semplice: l'unico client è `web/app.js`,
che viaggia nello stesso commit, e nemmeno l'add-on ci dipende più — la sua riga di avvio usa
`--port`.

[`docs/naming.md`](docs/naming.md) è la mappa: cosa si è spostato, cosa no, e perché.

---

## Domande frequenti

**Devo pagare qualcosa?** No. Tutto gira in locale ed è gratuito. L'unico costo è lo spazio
su disco per il modello di Ollama (~5 GB) e per quello di Whisper (~1,5 GB), scaricati una
volta sola.

**Funziona senza connessione?** Dopo l'installazione, sì — tranne per scaricare un nuovo
reel da un URL, che ovviamente richiede internet. Un reel già salvato si lavora offline.

**Le ricette in altre lingue?** Un reel in inglese può diventare una ricetta in italiano
oppure restare in inglese, come preferisci — nomi e procedimento tradotti, unità convertite,
i Fahrenheit portati a Celsius. Come lingue di *uscita* sono previste solo italiano e
inglese; il parlato in ingresso può essere qualunque cosa Whisper riconosca, tenendo presente
che più ci si allontana da quelle due più la traduzione scivola. Vedi
*[Lingua e sistema di misura](#lingua-e-sistema-di-misura)*.

**E se un reel non ha la ricetta scritta né detta chiaramente?** Reel2Recipe estrae ciò che
può e **dichiara le lacune** invece di riempirle a caso. Poi puoi completare a mano.

---

## Licenza

Reel2Recipe è distribuito con licenza **MIT** (v. [`LICENSE`](LICENSE)): puoi usarlo,
modificarlo e ridistribuirlo liberamente, anche per scopi commerciali, tenendo
l'attribuzione.

Il materiale di terzi che il progetto include o usa — le icone Material Symbols incorporate
nell'interfaccia, gli strumenti che vengono installati a parte, le fonti delle densità — è
elencato in [`NOTICE.md`](NOTICE.md) con le rispettive licenze. Vale lo stesso criterio delle
densità in `data/`: un'attribuzione che nessuno può verificare non è un'attribuzione.
