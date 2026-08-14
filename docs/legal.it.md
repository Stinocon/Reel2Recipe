# Copyright, brevetti e Termini d'Uso

<p align="right"><strong>Italiano</strong> · <a href="legal.md">English</a></p>

> **Questa è la versione facente fede.** Il documento esiste in due lingue e le due dicono la
> stessa cosa. Dove sembrassero divergere, prevale questa: è quella scritta per prima e porta
> le citazioni nella loro formulazione originale. Dirlo apertamente è meglio che far finta che
> due testi non possano scostarsi — possono, e nominare quale vince è ciò che rende un
> documento legale bilingue utilizzabile invece che ambiguo.

Questa nota spiega perché Reel2Recipe è costruito come è costruito. Non è consulenza legale:
è la ricognizione onesta che ha guidato le scelte di progetto. Le conclusioni condizionano
il codice, non stanno a margine.

Riassunto in una riga: **estrarre una ricetta per uso personale è lecito; ridistribuire la
prosa di un creator no; scaricare da Instagram viola i Termini d'Uso della piattaforma.**

---

## 1. Gli elenchi di ingredienti non sono protetti da copyright

Un elenco di ingredienti è **informazione**, non opera dell'ingegno. Manca del carattere
creativo che la legge italiana sul diritto d'autore (L. 633/1941, art. 1) richiede per la
tutela: è un fatto, come una ricetta chimica o una formula.

La stessa conclusione vale negli Stati Uniti: in *Publications International v. Meredith
Corp.* (7th Circuit, 1996) la corte stabilì che «the identification of ingredients necessary
for the preparation of a dish is a statement of facts [...] there is no expressive element
deserving copyright protection».

**Conseguenza per Reel2Recipe:** estrarre l'elenco degli ingredienti da un reel e
riformattarlo (convertendo le quantità, raggruppandolo, traducendolo) è lecito.

---

## 2. Il testo descrittivo di un creator è invece protetto

La narrazione, l'aneddoto, il fraseggio con cui un creator racconta il procedimento sono
**espressione creativa** e sono tutelati dal diritto d'autore. Copiarli parola per parola e
ripubblicarli sarebbe una violazione.

**Conseguenza per Reel2Recipe — due scelte di design concrete:**

1. `extract.py` **riformula** il procedimento con parole proprie, in forma di istruzioni
   brevi e operative. Non trascrive il testo del creator: ne estrae le azioni. Il prompt del
   modello lo impone esplicitamente.
2. Il campo `link` di ogni ricetta esportata punta **sempre** al reel originale, quando
   disponibile. L'attribuzione all'autore non è un optional: è il modo corretto di usare il
   suo lavoro. La ricetta rimanda alla fonte, non la sostituisce.

---

## 3. I brevetti non c'entrano

Le ricette di cucina domestica **non sono invenzioni brevettabili**: non hanno il carattere
di novità e applicazione industriale che il brevetto tutela. La preoccupazione sui brevetti,
in questo contesto, non ha un corrispettivo reale.

(Esistono brevetti su *processi industriali* alimentari — un metodo di pastorizzazione, un
macchinario — ma sono un altro mondo, estraneo all'uso domestico di questo strumento.)

---

## 4. I Termini d'Uso di Instagram — qui sta il punto vero

È l'aspetto giuridicamente più rilevante, e non riguarda il copyright.

I **Termini d'Uso di Instagram** vietano la raccolta automatizzata di contenuti dalla
piattaforma senza autorizzazione. Scaricare un reel con uno strumento come `yt-dlp` è una
**violazione contrattuale dei Termini d'Uso** — non un reato, non una violazione di
copyright, ma pur sempre una violazione dell'accordo che si accetta usando Instagram.

Questa è la ragione per cui Reel2Recipe è progettato come è progettato:

- **È uno strumento locale, per uso personale.** Non è un servizio pubblico che scarica
  reel per conto di terzi su richiesta. La differenza è sostanziale: un uso personale e
  limitato su contenuti che si è scelto di consultare è cosa diversa da una raccolta
  sistematica e su scala.
- **Il download è una scelta esplicita dell'utente**, non un comportamento nascosto: la
  funzione da URL usa `yt-dlp` solo quando l'utente incolla un link e preme *Cook*.
- **Rimane sempre disponibile l'alternativa senza download**: caricare un file video che si
  possiede già, o incollare la sola didascalia. Questa strada non tocca affatto i Termini
  d'Uso.

**Se un domani questo progetto venisse pubblicato** come applicazione web accessibile a
tutti, la versione pubblica dovrebbe accettare **solo file forniti dall'utente**, senza la
funzione di scaricamento da URL: un servizio pubblico che scarica da Instagram per conto
degli utenti attirerebbe su di sé la responsabilità della violazione, moltiplicata per ogni
utente. Per l'uso locale e personale a cui il progetto è destinato oggi, il confine è quello
descritto sopra.

---

## 5. Il materiale scaricato non lascia il computer

Ogni video, audio, fotogramma e didascalia scaricato finisce in `workspace/`, che è escluso
da git (`.gitignore`). Questo materiale:

- **non viene mai committato** nel repository;
- **non viene mai ridistribuito** o caricato online;
- **non viene mai usato per addestrare modelli** (i modelli girano in locale e non inviano
  nulla all'esterno).

Nel repository pubblico va **solo il codice** e le tabelle di conversione impersonali. Il
guard anti-leak in `check.sh` verifica meccanicamente, prima di ogni commit, che nessun file
di `workspace/` sia finito sotto git per errore.

---

## In sintesi

| Aspetto | Stato | Come lo gestiamo |
|---|---|---|
| Elenco ingredienti | Non protetto | Estratto e riformattato liberamente |
| Prosa del procedimento | Protetta | Riformulata, mai copiata; fonte sempre citata |
| Brevetti | Non pertinenti | — |
| Termini d'Uso di Instagram | Il download li viola | Strumento locale, uso personale, alternativa senza download |
| Materiale scaricato | Di terzi | Solo locale, mai condiviso, guard anti-leak |
