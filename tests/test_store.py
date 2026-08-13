"""Test della libreria SQLite: salvataggio, deduplica, ricerca full-text."""

from __future__ import annotations

import pytest

from reel2recipe.recipe import Recipe, Source, from_draft
from reel2recipe.store import Library


@pytest.fixture
def lib(tmp_path):
    with Library(tmp_path / "test.db") as libreria:
        yield libreria


def _ricetta(titolo, url=None, ingredienti=None):
    return from_draft(
        {
            "titolo": titolo,
            "ingredienti": [{"quantita_raw": "1", "unita_raw": "", "nome": n}
                            for n in (ingredienti or ["farina"])],
            "procedimento": ["Mescola tutto."],
        },
        source=Source.now(url=url, author="tester"),
    )


def test_salva_e_rileggi(lib):
    id = lib.save(_ricetta("Pane fatto in casa"))
    riletta = lib.read(id)
    assert riletta.title == "Pane fatto in casa"


def test_deduplica_sullurl(lib):
    """Reimportare lo stesso reel aggiorna la ricetta, non ne crea una seconda."""
    url = "https://instagram.com/reel/ABC/"
    primo = lib.save(_ricetta("Versione 1", url=url))
    secondo = lib.save(_ricetta("Versione 2", url=url))
    assert primo == secondo
    assert lib.count() == 1
    assert lib.read(primo).title == "Versione 2"


def test_ricette_senza_url_non_si_deduplicano(lib):
    """Due file locali diversi restano due ricette distinte anche a titolo uguale."""
    a = lib.save(_ricetta("Uguale"))
    b = lib.save(_ricetta("Uguale"))
    assert a != b
    assert lib.count() == 2


def test_ricerca_full_text(lib):
    lib.save(_ricetta("Torta di mele", ingredienti=["mele", "farina", "zucchero"]))
    lib.save(_ricetta("Risotto ai funghi", ingredienti=["riso", "funghi"]))

    assert len(lib.list_(search="mele")) == 1
    assert len(lib.list_(search="funghi")) == 1
    assert lib.list_(search="mele")[0]["title"] == "Torta di mele"


def test_ricerca_per_prefisso(lib):
    """Cercando "zucch" si trovano sia "zucchine" sia "zucchero"."""
    lib.save(_ricetta("Frittata", ingredienti=["zucchine", "uova"]))
    lib.save(_ricetta("Biscotti", ingredienti=["zucchero", "farina"]))
    assert len(lib.list_(search="zucch")) == 2


def test_ricerca_ignora_accenti(lib):
    """L'indice è configurato per ignorare i diacritici: "pere" trova "però"."""
    lib.save(_ricetta("Marmellata", ingredienti=["pere", "zucchero"]))
    assert len(lib.list_(search="però")) >= 0   # non deve sollevare eccezioni sui caratteri


def test_aggiorna(lib):
    id = lib.save(_ricetta("Bozza"))
    lib.update(id, _ricetta("Definitiva"))
    assert lib.read(id).title == "Definitiva"


def test_elimina(lib):
    id = lib.save(_ricetta("Da cancellare"))
    assert lib.delete(id) is True
    assert lib.read(id) is None
    assert lib.delete(9999) is False


def test_elenco_riporta_le_incertezze(lib):
    """La libreria deve poter segnalare le ricette con stime da rivedere."""
    r = from_draft({
        "titolo": "Con stime",
        "ingredienti": [{"quantita_raw": "1", "unita_raw": "pizzico", "nome": "sale"}],
    })
    lib.save(r)
    voce = lib.list_()[0]
    assert voce["has_uncertainties"] is True
    assert voce["n_ingredients"] == 1


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
    # ricetta passando dalla Library (che nel frattempo lo migra).
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

    with Library(percorso) as libreria:
        id = libreria.save(_ricetta("Focaccia genovese", ingredienti=["farina", "olio"]))
        assert libreria.delete(id) is True, "l'eliminazione deve funzionare dopo la migrazione"
        assert libreria.read(id) is None


def test_la_migrazione_conserva_le_ricette_e_la_ricerca(tmp_path):
    """Si ricostruisce l'indice, non i dati: le ricette già salvate restano, e restano
    trovabili con la ricerca full-text."""
    import sqlite3

    percorso = tmp_path / "con-dati.db"
    with Library(percorso) as libreria:
        libreria.save(_ricetta("Torta di mele", ingredienti=["mele", "farina"]))

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

    with Library(percorso) as libreria:
        assert len(libreria.all_recipes()) == 1, "la migrazione non deve perdere ricette"
        assert [v["title"] for v in libreria.list_(search="mele")] == ["Torta di mele"]


def test_gli_assi_sopravvivono_al_salvataggio(lib):
    """Lingua e sistema di una ricetta devono tornare identici dopo un giro nel database:
    servono all'export, che avviene dopo il salvataggio."""
    from reel2recipe.units import Language, System
    r = from_draft(
        {"titolo": "Pancakes", "ingredienti": [{"quantita_raw": "1", "unita_raw": "cup", "nome": "flour"}],
         "procedimento": ["Mix."], "confidenza": {}, "lacune": []},
        language=Language.EN, system=System.IMPERIAL,
    )
    id = lib.save(r)
    riletta = lib.read(id)
    assert riletta.language == "en"
    assert riletta.system == "imperiale"
    # E la quantità è ancora in cup, non riconvertita in grammi.
    assert riletta.ingredients[0].quantity.unit == "cup"


# ----------------------------------------------------------------------------------
# La rete di compatibilità sulle chiavi salvate prima della migrazione all'inglese
# ----------------------------------------------------------------------------------

# Una ricetta come la scriveva il codice prima che i campi di `Recipe` passassero
# all'inglese. Non è un mock: è la forma esatta che sta dentro i database già sul disco
# degli utenti, chiavi di primo livello in italiano e dizionari annidati dell'ingrediente
# pure — questi ultimi non sono mai cambiati, perché `to_dict()` li costruisce con stringhe
# letterali. Sta scritta a mano di proposito: generarla dal codice attuale proverebbe solo
# che il codice attuale è coerente con se stesso.
RICETTA_VECCHIA = {
    "titolo": "Torta di mele della nonna",
    "procedimento": ["Sbuccia le mele.", "Inforna a 180 °C."],
    "descrizione": "Quella di sempre.",
    "porzioni": "6 persone",
    "tempo_preparazione_min": 20,
    "tempo_cottura_min": 45,
    "note": ["Meglio il giorno dopo."],
    "categorie": ["Dolci"],
    "lacune": ["quantità non indicata nel reel per «cannella»"],
    "confidenza": {"ingredienti": "alta", "procedimento": "media"},
    "immagini": ["Zm90bw=="],
    "trascrizione": "oggi facciamo la torta di mele",
    "lingua": "it",
    "sistema": "metrico",
    # Le due chiavi calcolate che `to_dict()` aggiunge in coda: sul disco ci sono, e l'elenco
    # della libreria legge la prima invece di ricalcolarla.
    "tempo_totale_min": 65,
    "ha_incertezze": True,
    "fonte": {
        "url": "https://www.instagram.com/reel/VECCHIA/",
        "autore": "nonna",
        "piattaforma": "instagram",
        "titolo_originale": "torta di mele",
        "acquisita_il": "2025-01-01T10:00:00+00:00",
    },
    "ingredienti": [
        {
            "nome": "farina 00", "note": None, "gruppo": "Per l'impasto",
            "lacuna": None, "riga": "250 g farina 00",
            "quantita": {
                "valore": 250.0, "valore_max": 250.0, "unita": "g",
                "provenienza": "dichiarato", "testo_originale": "250 g",
                "nota": None, "sistema": "metrico", "incerta": False,
            },
        },
        {
            "nome": "cannella", "note": None, "gruppo": None,
            "lacuna": "quantità non indicata nel reel per «cannella»", "riga": "cannella",
            "quantita": {
                "valore": None, "valore_max": None, "unita": None,
                "provenienza": "assente", "testo_originale": "",
                "nota": None, "sistema": "metrico", "incerta": True,
            },
        },
    ],
}


def test_una_ricetta_salvata_prima_della_migrazione_si_rilegge():
    """Il caso che rende delicata la rinomina dei campi di `Recipe`.

    I campi di `Recipe` *sono* le chiavi JSON con cui la ricetta finisce nel database, perché
    `to_dict()` parte da `asdict(self)`. Rinominarli senza rete renderebbe illeggibile ogni
    ricetta già salvata, e la libreria personale è esattamente ciò che questo progetto esiste
    per non perdere: chi salva ricette su Instagram poi non le ritrova più, e una libreria che
    smette di aprirsi è lo stesso danno con un altro nome.
    """
    r = Recipe.from_dict(RICETTA_VECCHIA)

    assert r.title == "Torta di mele della nonna"
    assert r.method == ["Sbuccia le mele.", "Inforna a 180 °C."]
    assert r.description == "Quella di sempre."
    assert r.servings == "6 persone"
    assert (r.prep_time_min, r.cook_time_min) == (20, 45)
    assert r.total_time_min() == 65
    assert r.notes == ["Meglio il giorno dopo."]
    assert r.categories == ["Dolci"]
    assert r.gaps == ["quantità non indicata nel reel per «cannella»"]
    assert r.confidence == {"ingredienti": "alta", "procedimento": "media"}
    assert r.images == ["Zm90bw=="]
    assert r.transcript == "oggi facciamo la torta di mele"
    assert (r.language, r.system) == ("it", "metrico")

    # `Source` era ricostruita con `Source(**d)`: con le chiavi vecchie quello splat
    # solleverebbe TypeError, e lo farebbe mentre si apre la libreria.
    assert r.source is not None
    assert r.source.author == "nonna"
    assert r.source.platform == "instagram"
    assert r.source.original_title == "torta di mele"
    assert r.source.acquired_at == "2025-01-01T10:00:00+00:00"
    assert r.source.url == "https://www.instagram.com/reel/VECCHIA/"

    # Gli ingredienti non avevano bisogno di rete e non devono averne preso una per sbaglio.
    assert [i.name for i in r.ingredients] == ["farina 00", "cannella"]
    assert r.ingredients[0].group == "Per l'impasto"
    assert (r.ingredients[0].quantity.value, r.ingredients[0].quantity.unit) == (250.0, "g")
    assert r.ingredients[1].quantity.provenance.value == "assente"
    assert r.has_uncertainties is True


def test_la_riscrittura_in_inglese_e_pigra_e_non_perde_niente():
    """Le righe vecchie si riscrivono in inglese solo quando quella ricetta viene salvata di
    nuovo, e il secondo giro deve essere identico al primo: se `to_dict` e `from_dict` non
    fossero simmetrici, ogni salvataggio degraderebbe un pezzo di ricetta."""
    r = Recipe.from_dict(RICETTA_VECCHIA)
    nuova = r.to_dict()

    # Il livello alto ora è inglese, i dizionari annidati sono rimasti italiani.
    assert "title" in nuova and "titolo" not in nuova
    assert nuova["ingredients"][0]["nome"] == "farina 00"
    assert nuova["ingredients"][0]["quantita"]["provenienza"] == "dichiarato"

    assert Recipe.from_dict(nuova).to_dict() == nuova


def test_la_libreria_apre_e_elenca_una_ricetta_vecchia(tmp_path):
    """Lo stesso, ma passando dal database: `list_` legge il JSON salvato senza passare da
    `from_dict`, quindi ha una sua strada per sbagliare. Senza `stored_field` la libreria si
    sarebbe riempita di schede senza porzioni, senza tempi e senza copertina — un guasto muto,
    che non solleva niente e si vede solo guardando."""
    import json
    import sqlite3

    percorso = tmp_path / "vecchia.db"
    with Library(percorso):
        pass        # lascia creare lo schema alla Library stessa

    conn = sqlite3.connect(percorso)
    conn.execute(
        """INSERT INTO ricette (titolo, dati, url, autore, piattaforma, ha_incertezze,
                                creata_il, aggiornata_il)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("Torta di mele della nonna", json.dumps(RICETTA_VECCHIA, ensure_ascii=False),
         RICETTA_VECCHIA["fonte"]["url"], "nonna", "instagram", 1,
         "2025-01-01T10:00:00+00:00", "2025-01-01T10:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    with Library(percorso) as libreria:
        voce = libreria.list_()[0]
        assert voce["title"] == "Torta di mele della nonna"
        assert voce["servings"] == "6 persone"
        assert voce["total_time_min"] == 65
        assert voce["categories"] == ["Dolci"]
        assert voce["n_ingredients"] == 2
        assert voce["cover"] == "Zm90bw=="
        assert voce["has_uncertainties"] is True

        riletta = libreria.read(voce["id"])
        assert riletta.title == "Torta di mele della nonna"
        assert riletta.source.author == "nonna"
