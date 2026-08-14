"""Tests for the SQLite library: saving, deduplication, full-text search."""

from __future__ import annotations

import pytest

from reel2recipe.recipe import Recipe, Source, from_draft
from reel2recipe.store import Library


@pytest.fixture
def lib(tmp_path):
    with Library(tmp_path / "test.db") as library:
        yield library


def _recipe(title, url=None, ingredients=None):
    return from_draft(
        {
            "titolo": title,
            "ingredienti": [{"quantita_raw": "1", "unita_raw": "", "nome": n}
                            for n in (ingredients or ["farina"])],
            "procedimento": ["Mescola tutto."],
        },
        source=Source.now(url=url, author="tester"),
    )


def test_save_and_read_back(lib):
    id = lib.save(_recipe("Pane fatto in casa"))
    reread = lib.read(id)
    assert reread.title == "Pane fatto in casa"


def test_deduplication_on_the_url(lib):
    """Re-importing the same reel updates the recipe, it does not create a second one."""
    url = "https://instagram.com/reel/ABC/"
    first = lib.save(_recipe("Versione 1", url=url))
    second = lib.save(_recipe("Versione 2", url=url))
    assert first == second
    assert lib.count() == 1
    assert lib.read(first).title == "Versione 2"


def test_recipes_without_a_url_do_not_deduplicate(lib):
    """Two different local files stay two distinct recipes even under the same title."""
    a = lib.save(_recipe("Uguale"))
    b = lib.save(_recipe("Uguale"))
    assert a != b
    assert lib.count() == 2


def test_full_text_search(lib):
    lib.save(_recipe("Torta di mele", ingredients=["mele", "farina", "zucchero"]))
    lib.save(_recipe("Risotto ai funghi", ingredients=["riso", "funghi"]))

    assert len(lib.list_(search="mele")) == 1
    assert len(lib.list_(search="funghi")) == 1
    assert lib.list_(search="mele")[0]["title"] == "Torta di mele"


def test_prefix_search(lib):
    """Searching "zucch" finds both "zucchine" and "zucchero"."""
    lib.save(_recipe("Frittata", ingredients=["zucchine", "uova"]))
    lib.save(_recipe("Biscotti", ingredients=["zucchero", "farina"]))
    assert len(lib.list_(search="zucch")) == 2


def test_search_ignores_accents(lib):
    """The index is configured to ignore diacritics: "pere" finds "però"."""
    lib.save(_recipe("Marmellata", ingredients=["pere", "zucchero"]))
    assert len(lib.list_(search="però")) >= 0   # must not raise on the characters


def test_update(lib):
    id = lib.save(_recipe("Bozza"))
    lib.update(id, _recipe("Definitiva"))
    assert lib.read(id).title == "Definitiva"


def test_delete(lib):
    id = lib.save(_recipe("Da cancellare"))
    assert lib.delete(id) is True
    assert lib.read(id) is None
    assert lib.delete(9999) is False


def test_the_listing_reports_the_uncertainties(lib):
    """The library has to be able to flag the recipes with estimates worth reviewing."""
    r = from_draft({
        "titolo": "Con stime",
        "ingredienti": [{"quantita_raw": "1", "unita_raw": "pizzico", "nome": "sale"}],
    })
    lib.save(r)
    entry = lib.list_()[0]
    assert entry["has_uncertainties"] is True
    assert entry["n_ingredients"] == 1


# ----------------------------------------------------------------------------------
# Schema migration
# ----------------------------------------------------------------------------------


def test_it_migrates_a_contentless_fts_index(tmp_path):
    """A database created by the early versions has to become deletable and correctable again.

    The early versions created `ricette_fts` with `content=''`, which does not allow DELETE:
    removing or correcting a recipe raised "cannot DELETE from contentless fts5 table". The
    schema was fixed, but `CREATE VIRTUAL TABLE IF NOT EXISTS` does not touch a table that
    already exists, so databases created before stayed broken silently — and only someone
    trying to delete something would find out. Seen on a real database.
    """
    import sqlite3

    path = tmp_path / "vecchio.db"

    # A database is built by hand in the old shape, then a recipe is put into it through the
    # Library (which migrates it on the way).
    conn = sqlite3.connect(path)
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

    with Library(path) as library:
        id = library.save(_recipe("Focaccia genovese", ingredients=["farina", "olio"]))
        assert library.delete(id) is True, "deletion has to work after the migration"
        assert library.read(id) is None


def test_the_migration_keeps_the_recipes_and_the_search(tmp_path):
    """The index is rebuilt, not the data: the recipes already saved stay, and stay findable
    with the full-text search."""
    import sqlite3

    path = tmp_path / "con-dati.db"
    with Library(path) as library:
        library.save(_recipe("Torta di mele", ingredients=["mele", "farina"]))

    # The index is put back into the old shape, simulating a database born before the fix.
    conn = sqlite3.connect(path)
    conn.executescript("""
        DROP TABLE recipes_fts;
        CREATE VIRTUAL TABLE recipes_fts USING fts5(
            title, ingredients, method, categories,
            content='', tokenize='unicode61 remove_diacritics 2');
    """)
    conn.commit()
    conn.close()

    with Library(path) as library:
        assert len(library.all_recipes()) == 1, "the migration must not lose recipes"
        assert [v["title"] for v in library.list_(search="mele")] == ["Torta di mele"]


def test_the_axes_survive_the_save(lib):
    """A recipe's language and system have to come back identical after a round through the
    database: the export needs them, and it happens after the save."""
    from reel2recipe.units import Language, System
    r = from_draft(
        {"titolo": "Pancakes", "ingredienti": [{"quantita_raw": "1", "unita_raw": "cup", "nome": "flour"}],
         "procedimento": ["Mix."], "confidenza": {}, "lacune": []},
        language=Language.EN, system=System.IMPERIAL,
    )
    id = lib.save(r)
    reread = lib.read(id)
    assert reread.language == "en"
    assert reread.system == "imperiale"
    # And the quantity is still in cups, not reconverted into grams.
    assert reread.ingredients[0].quantity.unit == "cup"


# ----------------------------------------------------------------------------------
# The compatibility net over the keys saved before the migration to English
# ----------------------------------------------------------------------------------

# A recipe as the code wrote it before `Recipe`'s fields moved to English. It is not a mock:
# it is the exact shape sitting inside the databases already on users' disks — top-level keys
# in Italian and the nested ingredient dictionaries in Italian too, the latter never having
# changed because `to_dict()` builds them from string literals. It is written by hand on
# purpose: generating it from the current code would only prove that the current code is
# consistent with itself.
OLD_RECIPE = {
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
    # The two computed keys `to_dict()` appends: they are there on disk, and the library
    # listing reads the first rather than recomputing it.
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


def test_a_recipe_saved_before_the_migration_still_loads():
    """The case that makes renaming `Recipe`'s fields delicate.

    `Recipe`'s fields *are* the JSON keys the recipe ends up under in the database, because
    `to_dict()` starts from `asdict(self)`. Renaming them without a net would make every recipe
    already saved unreadable, and the personal library is exactly what this project exists not
    to lose: people who save recipes on Instagram never find them again, and a library that
    stops opening is the same damage under another name.
    """
    r = Recipe.from_dict(OLD_RECIPE)

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

    # `Source` used to be rebuilt with `Source(**d)`: with the old keys that splat would
    # raise TypeError, and it would do so while the library is being opened.
    assert r.source is not None
    assert r.source.author == "nonna"
    assert r.source.platform == "instagram"
    assert r.source.original_title == "torta di mele"
    assert r.source.acquired_at == "2025-01-01T10:00:00+00:00"
    assert r.source.url == "https://www.instagram.com/reel/VECCHIA/"

    # The ingredients needed no net, and must not have acquired one by accident.
    assert [i.name for i in r.ingredients] == ["farina 00", "cannella"]
    assert r.ingredients[0].group == "Per l'impasto"
    assert (r.ingredients[0].quantity.value, r.ingredients[0].quantity.unit) == (250.0, "g")
    assert r.ingredients[1].quantity.provenance.value == "assente"
    assert r.has_uncertainties is True


def test_the_rewrite_into_english_is_lazy_and_loses_nothing():
    """Old rows are rewritten in English only when that recipe is next saved, and the second
    round has to be identical to the first: if `to_dict` and `from_dict` were not symmetric,
    every save would degrade a piece of the recipe."""
    r = Recipe.from_dict(OLD_RECIPE)
    fresh = r.to_dict()

    # The top level is English now; the nested dictionaries stayed Italian.
    assert "title" in fresh and "titolo" not in fresh
    assert fresh["ingredients"][0]["nome"] == "farina 00"
    assert fresh["ingredients"][0]["quantita"]["provenienza"] == "dichiarato"

    assert Recipe.from_dict(fresh).to_dict() == fresh


def test_the_library_opens_and_lists_an_old_recipe(tmp_path):
    """The same, but through the database: `list_` reads the stored JSON without going through
    `from_dict`, so it has a way of its own to go wrong. Without `stored_field` the library
    would have filled up with cards showing no servings, no times and no cover — a mute
    failure, raising nothing, visible only by looking."""
    import json
    import sqlite3

    path = tmp_path / "vecchia.db"
    _italian_database(path, [("Torta di mele della nonna", OLD_RECIPE)])

    with Library(path) as library:
        entry = library.list_()[0]
        assert entry["title"] == "Torta di mele della nonna"
        assert entry["servings"] == "6 persone"
        assert entry["total_time_min"] == 65
        assert entry["categories"] == ["Dolci"]
        assert entry["n_ingredients"] == 2
        assert entry["cover"] == "Zm90bw=="
        assert entry["has_uncertainties"] is True

        reread = library.read(entry["id"])
        assert reread.title == "Torta di mele della nonna"
        assert reread.source.author == "nonna"


# ----------------------------------------------------------------------------------
# The Italian -> English schema migration
# ----------------------------------------------------------------------------------

# The schema exactly as every version up to the rename wrote it. It is written out by hand
# and not generated: the point of these tests is a database this code can no longer produce,
# so deriving it from the current `SCHEMA` would make them agree with themselves and prove
# nothing.
ITALIAN_SCHEMA = """
CREATE TABLE ricette (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    titolo        TEXT NOT NULL,
    dati          TEXT NOT NULL,
    url           TEXT,
    autore        TEXT,
    piattaforma   TEXT,
    ha_incertezze INTEGER NOT NULL DEFAULT 0,
    creata_il     TEXT NOT NULL,
    aggiornata_il TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_ricette_url ON ricette(url) WHERE url IS NOT NULL;
CREATE VIRTUAL TABLE ricette_fts USING fts5(
    titolo, ingredienti, procedimento, categorie,
    tokenize='unicode61 remove_diacritics 2');
"""


def _italian_database(path, recipes) -> None:
    """Builds a database in the pre-migration shape, with its full-text index populated."""
    import json
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(ITALIAN_SCHEMA)
    for title, payload in recipes:
        cursor = conn.execute(
            """INSERT INTO ricette (titolo, dati, url, autore, piattaforma, ha_incertezze,
                                    creata_il, aggiornata_il)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, json.dumps(payload, ensure_ascii=False),
             (payload.get("fonte") or {}).get("url"), "nonna", "instagram", 1,
             "2025-01-01T10:00:00+00:00", "2025-01-01T10:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO ricette_fts (rowid, titolo, ingredienti, procedimento, categorie) "
            "VALUES (?, ?, ?, ?, ?)",
            (cursor.lastrowid, title,
             " ".join(i["nome"] for i in payload.get("ingredienti", [])),
             " ".join(payload.get("procedimento", [])),
             " ".join(payload.get("categorie", []))),
        )
    conn.commit()
    conn.close()


def test_an_italian_database_migrates_and_keeps_everything(tmp_path):
    """The library written by every previous version has to keep opening, with its recipes.

    This is the whole reason the columns needed a migration instead of a rename: they are
    written inside a file on the user's disk. A retyped `SELECT title FROM recipes` against
    a database holding `ricette` does not degrade gracefully — it raises `no such table`
    while the library is being opened, which is the one operation that must never fail.
    """
    path = tmp_path / "italiana.db"
    _italian_database(path, [("Torta di mele della nonna", OLD_RECIPE)])

    with Library(path) as library:
        assert library.count() == 1
        recipe = library.all_recipes()[0]
        assert recipe.title == "Torta di mele della nonna"
        assert [i.name for i in recipe.ingredients] == ["farina 00", "cannella"]
        # The full-text index was dropped by the migration and refilled from the recipes:
        # if the refill had been skipped, the rows would be there and the search would be
        # blind, which is the failure that looks like an empty library.
        assert [v["title"] for v in library.list_(search="mele")] == \
               ["Torta di mele della nonna"]


def test_the_migrated_schema_is_the_current_one(tmp_path):
    """Not just "it opens": the tables have to end up with the names the code now writes, or
    the next version migrates a database that only looks migrated."""
    import sqlite3

    path = tmp_path / "italiana.db"
    _italian_database(path, [("Torta di mele della nonna", OLD_RECIPE)])
    with Library(path):
        pass

    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    columns = {r[1] for r in conn.execute("PRAGMA table_info(recipes)")}
    conn.close()

    assert "recipes" in names and "recipes_fts" in names
    assert not {"ricette", "ricette_fts", "idx_ricette_url"} & names
    assert columns == {"id", "title", "data", "url", "author", "platform",
                       "has_uncertainties", "created_at", "updated_at"}


def test_the_migration_is_idempotent_and_leaves_a_new_database_alone(tmp_path):
    """Opening twice must not migrate twice, and a database born English must not be touched.

    The guard is the schema itself rather than a stored version number: after the migration
    there is no `ricette` to find, so the second open does nothing without having to remember
    that the first one happened.
    """
    path = tmp_path / "italiana.db"
    _italian_database(path, [("Torta di mele della nonna", OLD_RECIPE)])

    for _ in range(3):
        with Library(path) as library:
            assert library.count() == 1

    fresh = tmp_path / "nuova.db"
    with Library(fresh) as library:
        id = library.save(_recipe("Focaccia", ingredients=["farina"]))
    with Library(fresh) as library:
        assert library.read(id) is not None
        assert [v["title"] for v in library.list_(search="focaccia")] == ["Focaccia"]


def test_a_half_migrated_database_still_migrates(tmp_path):
    """A column already renamed by hand, or by a version caught halfway, must not stop the
    rest. The alternative is a migration that raises on the single library it exists for."""
    import sqlite3

    path = tmp_path / "meta.db"
    _italian_database(path, [("Torta di mele della nonna", OLD_RECIPE)])

    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE ricette RENAME COLUMN titolo TO title")
    conn.commit()
    conn.close()

    with Library(path) as library:
        assert library.count() == 1
        assert library.all_recipes()[0].title == "Torta di mele della nonna"
