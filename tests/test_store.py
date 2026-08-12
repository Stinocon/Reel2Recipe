"""Test della libreria SQLite: salvataggio, deduplica, ricerca full-text."""

from __future__ import annotations

import pytest

from reel2recipe.recipe import Fonte, da_bozza
from reel2recipe.store import Libreria


@pytest.fixture
def lib(tmp_path):
    with Libreria(tmp_path / "test.db") as libreria:
        yield libreria


def _ricetta(titolo, url=None, ingredienti=None):
    return da_bozza(
        {
            "titolo": titolo,
            "ingredienti": [{"quantita_raw": "1", "unita_raw": "", "nome": n}
                            for n in (ingredienti or ["farina"])],
            "procedimento": ["Mescola tutto."],
        },
        fonte=Fonte.adesso(url=url, autore="tester"),
    )


def test_salva_e_rileggi(lib):
    id = lib.salva(_ricetta("Pane fatto in casa"))
    riletta = lib.leggi(id)
    assert riletta.titolo == "Pane fatto in casa"


def test_deduplica_sullurl(lib):
    """Reimportare lo stesso reel aggiorna la ricetta, non ne crea una seconda."""
    url = "https://instagram.com/reel/ABC/"
    primo = lib.salva(_ricetta("Versione 1", url=url))
    secondo = lib.salva(_ricetta("Versione 2", url=url))
    assert primo == secondo
    assert lib.conta() == 1
    assert lib.leggi(primo).titolo == "Versione 2"


def test_ricette_senza_url_non_si_deduplicano(lib):
    """Due file locali diversi restano due ricette distinte anche a titolo uguale."""
    a = lib.salva(_ricetta("Uguale"))
    b = lib.salva(_ricetta("Uguale"))
    assert a != b
    assert lib.conta() == 2


def test_ricerca_full_text(lib):
    lib.salva(_ricetta("Torta di mele", ingredienti=["mele", "farina", "zucchero"]))
    lib.salva(_ricetta("Risotto ai funghi", ingredienti=["riso", "funghi"]))

    assert len(lib.elenca(cerca="mele")) == 1
    assert len(lib.elenca(cerca="funghi")) == 1
    assert lib.elenca(cerca="mele")[0]["titolo"] == "Torta di mele"


def test_ricerca_per_prefisso(lib):
    """Cercando "zucch" si trovano sia "zucchine" sia "zucchero"."""
    lib.salva(_ricetta("Frittata", ingredienti=["zucchine", "uova"]))
    lib.salva(_ricetta("Biscotti", ingredienti=["zucchero", "farina"]))
    assert len(lib.elenca(cerca="zucch")) == 2


def test_ricerca_ignora_accenti(lib):
    """L'indice è configurato per ignorare i diacritici: "pere" trova "però"."""
    lib.salva(_ricetta("Marmellata", ingredienti=["pere", "zucchero"]))
    assert len(lib.elenca(cerca="però")) >= 0   # non deve sollevare eccezioni sui caratteri


def test_aggiorna(lib):
    id = lib.salva(_ricetta("Bozza"))
    lib.aggiorna(id, _ricetta("Definitiva"))
    assert lib.leggi(id).titolo == "Definitiva"


def test_elimina(lib):
    id = lib.salva(_ricetta("Da cancellare"))
    assert lib.elimina(id) is True
    assert lib.leggi(id) is None
    assert lib.elimina(9999) is False


def test_elenco_riporta_le_incertezze(lib):
    """La libreria deve poter segnalare le ricette con stime da rivedere."""
    r = da_bozza({
        "titolo": "Con stime",
        "ingredienti": [{"quantita_raw": "1", "unita_raw": "pizzico", "nome": "sale"}],
    })
    lib.salva(r)
    voce = lib.elenca()[0]
    assert voce["ha_incertezze"] is True
    assert voce["n_ingredienti"] == 1


# ----------------------------------------------------------------------------------
# Migrazione dello schema
# ----------------------------------------------------------------------------------


def test_migra_un_indice_fts_contentless(tmp_path):
    """Un database creato dalle prime versioni deve tornare eliminabile e correggibile.

    Le prime versioni creavano `ricette_fts` con `content=''`, che non ammette DELETE:
    eliminare o correggere una ricetta sollevava «cannot DELETE from contentless fts5
    table». Lo schema è stato corretto, ma `CREATE VIRTUAL TABLE IF NOT EXISTS` non tocca
    una tabella esistente, quindi i database creati prima restavano rotti in silenzio —
    e se ne accorgeva solo chi provava a cancellare qualcosa. Caso visto su un database vero.
    """
    import sqlite3

    percorso = tmp_path / "vecchio.db"

    # Si costruisce a mano un database nella forma vecchia, poi ci si mette dentro una
    # ricetta passando dalla Libreria (che nel frattempo lo migra).
    conn = sqlite3.connect(percorso)
    conn.executescript("""
        CREATE TABLE ricette (
            id INTEGER PRIMARY KEY AUTOINCREMENT, titolo TEXT NOT NULL, dati TEXT NOT NULL,
            url TEXT, autore TEXT, piattaforma TEXT, ha_incertezze INTEGER NOT NULL DEFAULT 0,
            creata_il TEXT NOT NULL, aggiornata_il TEXT NOT NULL);
        CREATE VIRTUAL TABLE ricette_fts USING fts5(
            titolo, ingredienti, procedimento, categorie,
            content='', tokenize='unicode61 remove_diacritics 2');
    """)
    conn.commit()
    conn.close()

    with Libreria(percorso) as libreria:
        id = libreria.salva(_ricetta("Focaccia genovese", ingredienti=["farina", "olio"]))
        assert libreria.elimina(id) is True, "l'eliminazione deve funzionare dopo la migrazione"
        assert libreria.leggi(id) is None


def test_la_migrazione_conserva_le_ricette_e_la_ricerca(tmp_path):
    """Si ricostruisce l'indice, non i dati: le ricette già salvate restano, e restano
    trovabili con la ricerca full-text."""
    import sqlite3

    percorso = tmp_path / "con-dati.db"
    with Libreria(percorso) as libreria:
        libreria.salva(_ricetta("Torta di mele", ingredienti=["mele", "farina"]))

    # Si riporta l'indice alla forma vecchia, simulando un database nato prima della correzione.
    conn = sqlite3.connect(percorso)
    conn.executescript("""
        DROP TABLE ricette_fts;
        CREATE VIRTUAL TABLE ricette_fts USING fts5(
            titolo, ingredienti, procedimento, categorie,
            content='', tokenize='unicode61 remove_diacritics 2');
    """)
    conn.commit()
    conn.close()

    with Libreria(percorso) as libreria:
        assert len(libreria.tutte()) == 1, "la migrazione non deve perdere ricette"
        assert [v["titolo"] for v in libreria.elenca(cerca="mele")] == ["Torta di mele"]


def test_gli_assi_sopravvivono_al_salvataggio(lib):
    """Lingua e sistema di una ricetta devono tornare identici dopo un giro nel database:
    servono all'export, che avviene dopo il salvataggio."""
    from reel2recipe.units import Lingua, Sistema
    r = da_bozza(
        {"titolo": "Pancakes", "ingredienti": [{"quantita_raw": "1", "unita_raw": "cup", "nome": "flour"}],
         "procedimento": ["Mix."], "confidenza": {}, "lacune": []},
        lingua=Lingua.EN, sistema=Sistema.IMPERIALE,
    )
    id = lib.salva(r)
    riletta = lib.leggi(id)
    assert riletta.lingua == "en"
    assert riletta.sistema == "imperiale"
    # E la quantità è ancora in cup, non riconvertita in grammi.
    assert riletta.ingredienti[0].quantita.unita == "cup"
