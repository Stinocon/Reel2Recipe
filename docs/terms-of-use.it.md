# Condizioni d'uso

<p align="right"><strong>Italiano</strong> · <a href="terms-of-use.md">English</a></p>

> **Questa è la versione facente fede.** Il documento esiste in due lingue e le due dicono la
> stessa cosa. Dove sembrassero divergere, prevale questa. Tenere allineate due versioni
> legalmente operative è un impegno, non un automatismo: la clausola di prevalenza esiste
> perché quell'impegno abbia una risoluzione definita se un giorno viene meno.

Questo è il testo rivolto a **chi usa** Reel2Recipe. L'analisi giuridica che sta dietro alle
scelte di progetto è un'altra cosa e vive in [`legal.it.md`](legal.it.md).

## Cos'è, e cosa non è

Reel2Recipe è un **progetto personale**, messo insieme per uso proprio e pubblicato così
com'è. Non è un prodotto finito, non è commerciale e non lo diventerà. È stato scritto in
gran parte **con l'aiuto di un assistente IA**, sotto guida e revisione umana: era anche il
punto: capire fin dove arrivano questi strumenti facendone uscire qualcosa di utile davvero,
invece di una dimostrazione.

Viene distribuito **senza garanzie di alcun tipo** (v. [`LICENSE`](../LICENSE)): contiene
plausibilmente errori e casi limite a cui nessuno ha ancora pensato.

## La cosa più importante: controlla le quantità

L'estrazione è automatica. Un modello ascolta il parlato e legge la didascalia, e può
sbagliare: capire male una parola, saltare un ingrediente, attribuire una dose a chi non ce
l'aveva.

Il progetto è costruito per **ridurre** quel rischio e per **renderlo visibile**:

- le quantità non le converte il modello ma il codice, con tabelle di densità che citano la
  loro fonte (USDA FoodData Central, King Arthur Baking) — puoi andare a controllarle;
- quando una densità non è nota, la conversione **non si fa**: resta il volume, e la cosa
  viene dichiarata;
- ogni quantità porta la sua provenienza — dichiarata dal reel, convertita da tabella, o
  **stimata** (le misure a occhio come "un pizzico");
- le lacune finiscono in tutti gli export, PDF compreso, invece di essere nascoste.

Resta però una regola che nessun software può prendere al posto tuo: **rileggi la ricetta
prima di cucinarla**, soprattutto pesi e tempi. Una lacuna dichiarata la gestisci; un peso
sbagliato di cui non sai che è sbagliato, no.

Se hai **allergie o intolleranze**, non fidarti dell'elenco estratto: torna alla fonte
originale, che è sempre citata nella ricetta.

## Uso personale, e responsabilità sulle piattaforme

Lo strumento è pensato per **uso personale**, su contenuti che ti interessano davvero.

Scaricare un reel da Instagram **viola i Termini d'Uso della piattaforma**, indipendentemente
da cosa ne fai. È il motivo per cui Reel2Recipe gira in locale e non è un servizio pubblico,
e per cui **l'alternativa senza download è sempre disponibile**: puoi passargli un file che
hai già, o incollare la didascalia a mano.

La scelta di usare il recupero da URL, e le conseguenze di quella scelta nei confronti della
piattaforma, **restano tue**. Chi mantiene questo progetto non se ne assume la responsabilità.

## Le ricette non sono tue

Una ricetta estratta resta **il lavoro di chi l'ha pubblicata**. Reel2Recipe è costruito per
rispettarlo:

- l'elenco degli ingredienti è mera informazione e non è protetto da copyright: estrarlo e
  riformattarlo è lecito;
- il testo del procedimento invece **lo è**, e per questo viene *riformulato* con parole
  proprie e mai trascritto parola per parola;
- il **link alla fonte** viene incluso sempre, in ogni formato di export.

Non togliere l'attribuzione, e non ridistribuire le ricette estratte come se fossero tue.
Tenerle per te, o condividerle citando l'autore, è un altro discorso.

## I tuoi dati

Non escono dalla tua macchina. Non c'è telemetria, non ci sono chiamate a servizi remoti per
il funzionamento del prodotto, nessun modello viene addestrato su ciò che estrai. Video,
audio, didascalie e ricettario vivono in `workspace/`, che è escluso da git: se pubblichi una
tua copia del repository, quel materiale non parte con essa.

## Licenza

Il **codice** è MIT (v. [`LICENSE`](../LICENSE)): usalo, modificalo e ridistribuiscilo
liberamente, anche commercialmente, mantenendo l'attribuzione. Il materiale di terzi incluso
o usato è elencato in [`NOTICE.md`](../NOTICE.md) con le rispettive licenze.

La licenza copre il software, **non** le ricette che ci estrai: quelle seguono le regole del
paragrafo qui sopra.
