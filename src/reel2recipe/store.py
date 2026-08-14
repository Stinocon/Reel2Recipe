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

**The SQL is English, and getting there needed a migration rather than a rename.** Table and
column names are not code, they are *format*: they are written inside every database already
on a user's disk, so `ricette`/`titolo`/`dati` could not simply be retyped as
`recipes`/`title`/`data` — a database written by an older version would have stopped opening,
which for a library whose whole point is finding a recipe six months later is the worst
failure available. `_migrate_italian_schema` below does the `ALTER TABLE` once, in place.

The migration reads the **schema itself** rather than a `user_version` stamp. A version
number is a second source of truth that can disagree with the thing it describes — restore a
backup, copy a file between machines, and it lies — whereas `sqlite_master` cannot be wrong
about what the tables are actually called. It also means the migration is idempotent by
construction: it looks for `ricette`, and after it has run there is none.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import paths
from .recipe import Recipe, stored_field

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    data              TEXT NOT NULL,      -- the whole Recipe as JSON
    url               TEXT,               -- source, used for deduplication
    author            TEXT,
    platform          TEXT,
    has_uncertainties INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_recipes_url
    ON recipes(url) WHERE url IS NOT NULL;

-- Full-text index. A standard FTS5 table (not "contentless"): it keeps its own copy of the
-- text and in exchange supports DELETE and UPDATE by rowid, which are needed when a recipe
-- is corrected or removed. Duplicating the text is irrelevant for a personal library.
-- `remove_diacritics 2` makes the search insensitive to accents.
CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
    title, ingredients, method, categories,
    tokenize='unicode61 remove_diacritics 2'
);
"""

# The Italian schema, as written by every version up to this one. The values are the columns
# it becomes; the table itself goes `ricette` -> `recipes` and the index with it.
#
# `url` and `id` are absent because they never changed — listing them would suggest they are
# part of the rename and invite the next reader to "complete" the map.
LEGACY_COLUMNS = {
    "titolo": "title",
    "dati": "data",
    "autore": "author",
    "piattaforma": "platform",
    "ha_incertezze": "has_uncertainties",
    "creata_il": "created_at",
    "aggiornata_il": "updated_at",
}


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
        # The rename comes **before** the schema is applied, and the order is not cosmetic:
        # `CREATE TABLE IF NOT EXISTS recipes` on an Italian database would create a second,
        # empty table next to the full `ricette`, and the rename would then fail against a
        # name already taken — leaving a library that opens and shows nothing.
        self._migrate_italian_schema()
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._rebuild_index_if_stale()

    def _migrate_italian_schema(self) -> None:
        """Renames the table and its columns from Italian to English, once, in place.

        `ALTER TABLE ... RENAME COLUMN` keeps the rows where they are: nothing is copied and
        nothing is rewritten, so a library of a thousand recipes costs the same as an empty
        one. The full-text index is the exception — a virtual table's columns cannot be
        renamed — so it is dropped here and rebuilt by `_rebuild_index_if_stale`, which finds
        it empty against a full `recipes` and refills it. Dropping the index is safe in a way
        that dropping the table would not be: it holds a *copy* of text whose original is in
        `recipes`.
        """
        names = {r["name"] for r in self._conn.execute("SELECT name FROM sqlite_master")}
        if "ricette" not in names or "recipes" in names:
            return

        with self._transaction() as c:
            c.execute("DROP INDEX IF EXISTS idx_ricette_url")
            c.execute("DROP TABLE IF EXISTS ricette_fts")
            c.execute("ALTER TABLE ricette RENAME TO recipes")
            present = {r["name"] for r in c.execute("PRAGMA table_info(recipes)")}
            for old, new in LEGACY_COLUMNS.items():
                # A column at a time, and only if it is there: a database from a version
                # halfway through this history is a real possibility, and the alternative
                # is a migration that raises on the one library it was written for.
                if old in present:
                    c.execute(f"ALTER TABLE recipes RENAME COLUMN {old} TO {new}")

    def _rebuild_index_if_stale(self) -> None:
        """Rebuilds the full-text index when it does not match the recipes.

        Two different histories end up here, and they need the same repair. **The old
        contentless index:** early versions created the FTS table with `content=''`, which
        does not allow DELETE — removing or correcting a recipe raised `cannot DELETE from
        contentless fts5 table`. The schema was fixed, but `CREATE VIRTUAL TABLE IF NOT
        EXISTS` does not touch a table that already exists, so databases created before
        stayed broken silently and only someone trying to delete something found out. **The
        rename above:** it drops the index, so it comes back empty against a full table.

        Comparing the two counts covers both without either having to know about the other,
        and it is the honest question anyway — an index that disagrees with the data is stale
        whatever made it so. Only the index is rebuilt; the recipes themselves are never
        touched.
        """
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='recipes_fts'"
        ).fetchone()
        contentless = bool(row) and "content=''" in (row["sql"] or "")
        if not contentless:
            indexed = self._conn.execute("SELECT COUNT(*) AS n FROM recipes_fts").fetchone()["n"]
            if indexed == self.count():
                return

        with self._transaction() as c:
            c.execute("DROP TABLE IF EXISTS recipes_fts")
            c.executescript(SCHEMA)
            for r in c.execute("SELECT id, data FROM recipes").fetchall():
                self._index(c, r["id"], Recipe.from_dict(json.loads(r["data"])))

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

    def save(self, recipe: Recipe, overwrite: bool = True) -> int:
        """Saves a recipe and returns its id.

        If a recipe with the same source URL already exists it is updated rather than
        creating a second one: re-importing the same reel has to correct the existing
        entry, not fill the library with duplicates.
        """
        url = recipe.source.url if recipe.source else None
        if url and (existing := self.id_for_url(url)) is not None:
            if not overwrite:
                return existing
            self.update(existing, recipe)
            return existing

        data = recipe.to_json(indent=None)
        now = _now()
        with self._transaction() as c:
            cursor = c.execute(
                """INSERT INTO recipes (title, data, url, author, platform,
                                       has_uncertainties, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recipe.title, data, url,
                    recipe.source.author if recipe.source else None,
                    recipe.source.platform if recipe.source else None,
                    int(recipe.has_uncertainties), now, now,
                ),
            )
            identifier = int(cursor.lastrowid)
            self._index(c, identifier, recipe)
        return identifier

    def update(self, identifier: int, recipe: Recipe) -> None:
        """Replaces an existing recipe — which is what happens when the user corrects an
        ingredient by hand in the interface."""
        with self._transaction() as c:
            changed = c.execute(
                """UPDATE recipes
                      SET title = ?, data = ?, author = ?, has_uncertainties = ?, updated_at = ?
                    WHERE id = ?""",
                (
                    recipe.title, recipe.to_json(indent=None),
                    recipe.source.author if recipe.source else None,
                    int(recipe.has_uncertainties), _now(), identifier,
                ),
            ).rowcount
            if not changed:
                raise LibraryError(f"No recipe with id {identifier}")
            c.execute("DELETE FROM recipes_fts WHERE rowid = ?", (identifier,))
            self._index(c, identifier, recipe)

    def delete(self, identifier: int) -> bool:
        with self._transaction() as c:
            deleted = c.execute("DELETE FROM recipes WHERE id = ?", (identifier,)).rowcount
            c.execute("DELETE FROM recipes_fts WHERE rowid = ?", (identifier,))
        return bool(deleted)

    @staticmethod
    def _index(c: sqlite3.Connection, identifier: int, recipe: Recipe) -> None:
        c.execute(
            "INSERT INTO recipes_fts (rowid, title, ingredients, method, categories) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                identifier,
                recipe.title,
                " ".join(i.name for i in recipe.ingredients),
                " ".join(recipe.method),
                " ".join(recipe.categories),
            ),
        )

    # ---- reading ------------------------------------------------------------------

    def read(self, identifier: int) -> Recipe | None:
        row = self._conn.execute(
            "SELECT data FROM recipes WHERE id = ?", (identifier,)
        ).fetchone()
        return Recipe.from_dict(json.loads(row["data"])) if row else None

    def id_for_url(self, url: str) -> int | None:
        row = self._conn.execute("SELECT id FROM recipes WHERE url = ?", (url,)).fetchone()
        return int(row["id"]) if row else None

    def list_(self, search: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
        """Summary listing for the library. With `search` set, it uses the full-text index.

        Each entry holds the minimum needed to draw a card: id, title, author, number of
        ingredients and whether there are uncertainties to review.

        The keys of what comes out are English, and they moved in the same commit as
        `Recipe`'s fields and `web/app.js`, which is the only thing that reads them. They were
        never *format* — nothing on disk was ever keyed this way — which is why they could
        move on their own, a release before the SQL columns above needed a migration to.

        What is read out of the stored JSON goes through `stored_field`, for the same reason
        `Recipe.from_dict` does: a recipe saved before the migration still has Italian keys in
        its blob, and the listing is exactly where that would show up as a library full of
        cards with no servings and no cover.
        """
        if search and search.strip():
            rows = self._conn.execute(
                """SELECT r.id, r.title, r.author, r.url, r.platform,
                          r.has_uncertainties, r.created_at, r.data
                     FROM recipes_fts f
                     JOIN recipes r ON r.id = f.rowid
                    WHERE recipes_fts MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?""",
                (_fts_query(search), limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, title, author, url, platform, has_uncertainties, created_at, data
                     FROM recipes ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

        result = []
        for row in rows:
            data = json.loads(row["data"])
            result.append({
                "id": row["id"],
                "title": row["title"],
                "author": row["author"],
                "url": row["url"],
                "platform": row["platform"],
                "has_uncertainties": bool(row["has_uncertainties"]),
                "created_at": row["created_at"],
                "servings": stored_field(data, "servings"),
                "total_time_min": stored_field(data, "total_time_min"),
                "categories": stored_field(data, "categories") or [],
                "n_ingredients": len(stored_field(data, "ingredients") or []),
                "cover": (stored_field(data, "images") or [None])[0],
            })
        return result

    def all_recipes(self) -> list[Recipe]:
        rows = self._conn.execute("SELECT data FROM recipes ORDER BY created_at DESC").fetchall()
        return [Recipe.from_dict(json.loads(r["data"])) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM recipes").fetchone()["n"])


def _fts_query(search: str) -> str:
    """Turns a user's search into a safe FTS5 query.

    Terms are quoted (so FTS5's special characters do not accidentally become syntax) and
    `*` is appended for prefix matching: searching "courg" finds both "courgette" and
    "courgettes".
    """
    terms = [t for t in search.replace('"', " ").split() if t]
    return " ".join(f'"{t}"*' for t in terms) if terms else '""'
