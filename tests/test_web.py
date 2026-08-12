"""test_web.py — guard strutturali sul frontend.

Non eseguono JavaScript: la suite è pytest e il frontend non ha (né vuole) una toolchain.
Controllano invece la sola cosa che si può verificare leggendo i file, ed è esattamente la
classe di difetto che è passata inosservata: **un comando disegnato che nessuno legge.**

`index.html` dichiarava `#opt-lingua` e `#opt-sistema`, l'utente li vedeva e li usava, e
`app.js` non li interrogava mai — quindi ogni lavorazione usciva in italiano metrico. Un
controllo che non fa niente è peggio di un controllo assente: il primo insegna a non
fidarsi dell'interfaccia, il secondo almeno è onesto.
"""

from __future__ import annotations

import re

from reel2recipe.percorsi import RADICE_REPO

CARTELLA_WEB = RADICE_REPO / "web"
INDEX = (CARTELLA_WEB / "index.html").read_text(encoding="utf-8")
APP = (CARTELLA_WEB / "app.js").read_text(encoding="utf-8")

# Gli id definiti nel markup statico e quelli creati a runtime da `app.js` (la scheda
# ricetta e la modale nascono da template letterali dentro il JS).
ID_DEFINITI = set(re.findall(r'id="([\w-]+)"', INDEX)) | set(re.findall(r'id="([\w-]+)"', APP))

# I selettori per id effettivamente usati da `app.js`.
ID_USATI = set(re.findall(r"""\$\$?\('#([\w-]+)'\)""", APP))


def test_ogni_controllo_delle_opzioni_viene_letto():
    """Ogni `#opt-…` disegnato nel pannello deve essere interrogato da `app.js`.

    È il guard che avrebbe fatto scattare il difetto della lingua: il menu esisteva da
    subito, la lettura no.
    """
    disegnati = {i for i in set(re.findall(r'id="([\w-]+)"', INDEX)) if i.startswith("opt-")}
    assert disegnati, "nessun controllo delle opzioni trovato: il guard si è scollegato"
    non_letti = sorted(disegnati - ID_USATI)
    assert not non_letti, (
        f"controlli disegnati in index.html ma mai letti da app.js: {non_letti}. "
        "Un comando che non fa niente va collegato o tolto."
    )


def test_nessun_selettore_punta_nel_vuoto():
    """Il verso opposto: un `$('#tipo-sbagliato')` non fallisce, restituisce `null` — e il
    difetto si manifesta molto più tardi, come una riga che non reagisce."""
    inesistenti = sorted(ID_USATI - ID_DEFINITI)
    assert not inesistenti, (
        f"app.js interroga id che nessuno definisce: {inesistenti}"
    )
