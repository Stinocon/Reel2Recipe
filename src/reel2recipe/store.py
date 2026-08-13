"""store.py — the recipe library. SQLite with full-text search.

This module solves the problem the project was born from: not "extracting a recipe", but
**finding it again six months later**. A recipe extracted and then lost in an export folder
is no better than a reel saved on Instagram.

Why SQLite and not one file per recipe: search. FTS5 makes it possible to look for
"courgettes" or "gluten free" across titles, ingredients and methods in one go, which is
exactly what is wanted when you open the fridge and want to know what to cook.

The database lives in `workspace/`, so outside git: it holds third-party material. Where
`workspace/` actually is, is `paths.py`'s decision — in the add-on's container it is a
persistent volume, not a folder next to the repo.

**The SQL below stays in Italian, deliberately.** Table and column names are not code, they
are *format*: they are written inside every database already on a user's disk. Renaming them
would mean an `ALTER TABLE` over live data, which is exactly the destructive migration this
rename is built to avoid (see docs/naming.md). The same goes for the keys of the dictionary
`list_` returns: they mirror the stored JSON, and they change when `Recipe`'s fields do, in
one commit together with the frontend that reads them.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import paths
from .recipe import Ricetta

SCHEMA = """
CREATE TABLE IF NOT EXISTS ricette (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    titolo        TEXT NOT NULL,
    dati          TEXT NOT NULL,          -- the whole Recipe as JSON
    url           TEXT,                   -- source, used for deduplication
    autore        TEXT,
    piattaforma   TEXT,
    ha_incertezze INTEGER NOT NULL DEFAULT 0,
    creata_il     TEXT NOT NULL,
    aggiornata_il TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ricette_url
    ON ricette(url) WHERE url IS NOT NULL;

-- Full-text index. A standard FTS5 table (not "contentless"): it keeps its own copy of the
-- text and in exchange supports DELETE and UPDATE by rowid, which are needed when a recipe
-- is corrected or removed. Duplicating the text is irrelevant for a personal library.
-- `remove_diacritics 2` makes the search insensitive to accents.
CREATE VIRTUAL TABLE IF NOT EXISTS ricette_fts USING fts5(
    titolo, ingredienti, procedimento, categorie,
    tokenize='unicode61 remove_diacritics 2'
);
"""


class LibraryError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_path() -> Path:
    """`workspace/ricette.db`, next to the repo and outside git — or wherever
    `R2R_WORKSPACE` says."""
    return paths.database_path()


class Library:
    """Access to the library. Usable as a context manager."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate_contentless_fts()

    def _migrate_contentless_fts(self) -> None:
        """Rebuilds the full-text index if it is still in the old "contentless" shape.

        Early versions created `ricette_fts` with `content=''`, which does not allow
        DELETE: removing or correcting a recipe raised `cannot DELETE from contentless
        fts5 table`. The schema was fixed, but `CREATE VIRTUAL TABLE IF NOT EXISTS` does
        not touch a table that already exists — so databases created before stayed broken
        silently, and only someone trying to delete something would find out.

        The index is rebuilt, not the recipes: the real data is in `ricette` and is not
        touched. It costs one reindex, once.
        """
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ricette_fts'"
        ).fetchone()
        if not row or "content=''" not in (row["sql"] or ""):
            return

        with self._transaction() as c:
            c.execute("DROP TABLE ricette_fts")
            c.executescript(SCHEMA)
            for r in c.execute("SELECT id, dati FROM ricette").fetchall():
                self._index(c, r["id"], Ricetta.from_dict(json.loads(r["dati"])))

    # ---- lifecycle ----------------------------------------------------------------

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ---- writing ------------------------------------------------------------------

    def save(self, recipe: Ricetta, overwrite: bool = True) -> int:
        """Saves a recipe and returns its id.

        If a recipe with the same source URL already exists it is updated rather than
        creating a second one: re-importing the same reel has to correct the existing
        entry, not fill the library with duplicates.
        """
        url = recipe.fonte.url if recipe.fonte else None
        if url and (existing := self.id_for_url(url)) is not None:
            if not overwrite:
                return existing
            self.update(existing, recipe)
            return existing

        data = recipe.to_json(indent=None)
        now = _now()
        with self._transaction() as c:
            cursor = c.execute(
                """INSERT INTO ricette (titolo, dati, url, autore, piattaforma,
                                        ha_incertezze, creata_il, aggiornata_il)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recipe.titolo, data, url,
                    recipe.fonte.autore if recipe.fonte else None,
                    recipe.fonte.piattaforma if recipe.fonte else None,
                    int(recipe.ha_incertezze), now, now,
                ),
            )
            identifier = int(cursor.lastrowid)
            self._index(c, identifier, recipe)
        return identifier

    def update(self, identifier: int, recipe: Ricetta) -> None:
        """Replaces an existing recipe — which is what happens when the user corrects an
        ingredient by hand in the interface."""
        with self._transaction() as c:
            changed = c.execute(
                """UPDATE ricette
                      SET titolo = ?, dati = ?, autore = ?, ha_incertezze = ?, aggiornata_il = ?
                    WHERE id = ?""",
                (
                    recipe.titolo, recipe.to_json(indent=None),
                    recipe.fonte.autore if recipe.fonte else None,
                    int(recipe.ha_incertezze), _now(), identifier,
                ),
            ).rowcount
            if not changed:
                raise LibraryError(f"No recipe with id {identifier}")
            c.execute("DELETE FROM ricette_fts WHERE rowid = ?", (identifier,))
            self._index(c, identifier, recipe)

    def delete(self, identifier: int) -> bool:
        with self._transaction() as c:
            deleted = c.execute("DELETE FROM ricette WHERE id = ?", (identifier,)).rowcount
            c.execute("DELETE FROM ricette_fts WHERE rowid = ?", (identifier,))
        return bool(deleted)

    @staticmethod
    def _index(c: sqlite3.Connection, identifier: int, recipe: Ricetta) -> None:
        c.execute(
            "INSERT INTO ricette_fts (rowid, titolo, ingredienti, procedimento, categorie) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                identifier,
                recipe.titolo,
                " ".join(i.name for i in recipe.ingredienti),
                " ".join(recipe.procedimento),
                " ".join(recipe.categorie),
            ),
        )

    # ---- reading ------------------------------------------------------------------

    def read(self, identifier: int) -> Ricetta | None:
        row = self._conn.execute(
            "SELECT dati FROM ricette WHERE id = ?", (identifier,)
        ).fetchone()
        return Ricetta.from_dict(json.loads(row["dati"])) if row else None

    def id_for_url(self, url: str) -> int | None:
        row = self._conn.execute("SELECT id FROM ricette WHERE url = ?", (url,)).fetchone()
        return int(row["id"]) if row else None

    def list_(self, search: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
        """Summary listing for the library. With `search` set, it uses the full-text index.

        Each entry holds the minimum needed to draw a card: id, title, author, number of
        ingredients and whether there are uncertainties to review.

        The keys are still Italian on purpose: they mirror the stored JSON, and they change
        together with `Recipe`'s fields, in one commit with the frontend that reads them.
        """
        if search and search.strip():
            rows = self._conn.execute(
                """SELECT r.id, r.titolo, r.autore, r.url, r.piattaforma,
                          r.ha_incertezze, r.creata_il, r.dati
                     FROM ricette_fts f
                     JOIN ricette r ON r.id = f.rowid
                    WHERE ricette_fts MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?""",
                (_fts_query(search), limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, titolo, autore, url, piattaforma, ha_incertezze, creata_il, dati
                     FROM ricette ORDER BY creata_il DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

        result = []
        for row in rows:
            data = json.loads(row["dati"])
            result.append({
                "id": row["id"],
                "titolo": row["titolo"],
                "autore": row["autore"],
                "url": row["url"],
                "piattaforma": row["piattaforma"],
                "ha_incertezze": bool(row["ha_incertezze"]),
                "creata_il": row["creata_il"],
                "porzioni": data.get("porzioni"),
                "tempo_totale_min": data.get("tempo_totale_min"),
                "categorie": data.get("categorie") or [],
                "n_ingredienti": len(data.get("ingredienti") or []),
                "copertina": (data.get("immagini") or [None])[0],
            })
        return result

    def all_recipes(self) -> list[Ricetta]:
        rows = self._conn.execute("SELECT dati FROM ricette ORDER BY creata_il DESC").fetchall()
        return [Ricetta.from_dict(json.loads(r["dati"])) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM ricette").fetchone()["n"])


def _fts_query(search: str) -> str:
    """Turns a user's search into a safe FTS5 query.

    Terms are quoted (so FTS5's special characters do not accidentally become syntax) and
    `*` is appended for prefix matching: searching "courg" finds both "courgette" and
    "courgettes".
    """
    terms = [t for t in search.replace('"', " ").split() if t]
    return " ".join(f'"{t}"*' for t in terms) if terms else '""'
