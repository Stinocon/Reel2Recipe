"""store.py — la libreria delle ricette. SQLite con ricerca full-text.

Questo modulo risolve il problema che ha fatto nascere il progetto: non "estrarre una
ricetta", ma **ritrovarla sei mesi dopo**. Una ricetta estratta e poi persa in una cartella
di export non è meglio di un reel salvato su Instagram.

Perché SQLite e non un file per ricetta: la ricerca. FTS5 permette di cercare "zucchine"
o "senza glutine" fra titoli, ingredienti e procedimenti in un colpo solo, che è
esattamente ciò che serve quando si apre il frigo e si vuole sapere cosa cucinare.

Il database vive in `workspace/`, quindi fuori da git: contiene materiale di terzi. Dove sia
davvero `workspace/` lo decide `paths.py` — nel container dell'addon è un volume
persistente, non una cartella accanto al repo.
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
    dati          TEXT NOT NULL,          -- la Ricetta completa in JSON
    url           TEXT,                   -- fonte, usata per la deduplica
    autore        TEXT,
    piattaforma   TEXT,
    ha_incertezze INTEGER NOT NULL DEFAULT 0,
    creata_il     TEXT NOT NULL,
    aggiornata_il TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ricette_url
    ON ricette(url) WHERE url IS NOT NULL;

-- Indice full-text. Tabella FTS5 standard (non "contentless"): mantiene una propria
-- copia del testo e in cambio supporta DELETE e UPDATE per rowid, che servono quando
-- una ricetta viene corretta o cancellata. La duplicazione del testo è irrilevante per
-- una libreria personale. `remove_diacritics 2` rende la ricerca insensibile agli accenti.
CREATE VIRTUAL TABLE IF NOT EXISTS ricette_fts USING fts5(
    titolo, ingredienti, procedimento, categorie,
    tokenize='unicode61 remove_diacritics 2'
);
"""


class ErroreLibreria(RuntimeError):
    pass


def _adesso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def percorso_predefinito() -> Path:
    """`workspace/ricette.db`, accanto al repo e fuori da git — o dove dice `R2R_WORKSPACE`."""
    return paths.database_path()


class Libreria:
    """Accesso alla libreria. Usabile come context manager."""

    def __init__(self, percorso: Path | str | None = None):
        self.percorso = Path(percorso) if percorso else percorso_predefinito()
        self.percorso.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.percorso)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migra_fts_contentless()

    def _migra_fts_contentless(self) -> None:
        """Ricostruisce l'indice full-text se è rimasto nella vecchia forma «contentless».

        Le prime versioni creavano `ricette_fts` con `content=''`, che non ammette DELETE:
        eliminare o correggere una ricetta sollevava `cannot DELETE from contentless fts5
        table`. Lo schema è stato corretto, ma `CREATE VIRTUAL TABLE IF NOT EXISTS` non
        tocca una tabella che esiste già — quindi i database creati prima restavano rotti
        in silenzio, e se ne accorgeva solo chi provava a cancellare qualcosa.

        Si ricostruisce l'indice, non le ricette: i dati veri stanno in `ricette` e non si
        toccano. Costa una reindicizzazione, una volta sola.
        """
        riga = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ricette_fts'"
        ).fetchone()
        if not riga or "content=''" not in (riga["sql"] or ""):
            return

        with self._transazione() as c:
            c.execute("DROP TABLE ricette_fts")
            c.executescript(SCHEMA)
            for r in c.execute("SELECT id, dati FROM ricette").fetchall():
                self._indicizza(c, r["id"], Ricetta.from_dict(json.loads(r["dati"])))

    # ---- ciclo di vita ------------------------------------------------------------

    def __enter__(self) -> "Libreria":
        return self

    def __exit__(self, *_) -> None:
        self.chiudi()

    def chiudi(self) -> None:
        self._conn.close()

    @contextmanager
    def _transazione(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ---- scrittura ----------------------------------------------------------------

    def salva(self, ricetta: Ricetta, sovrascrivi: bool = True) -> int:
        """Salva una ricetta e ritorna il suo id.

        Se esiste già una ricetta con lo stesso URL di origine, viene aggiornata invece
        di crearne una seconda: reimportare lo stesso reel deve correggere la voce
        esistente, non riempire la libreria di doppioni.
        """
        url = ricetta.fonte.url if ricetta.fonte else None
        if url and (esistente := self.id_per_url(url)) is not None:
            if not sovrascrivi:
                return esistente
            self.aggiorna(esistente, ricetta)
            return esistente

        dati = ricetta.to_json(indent=None)
        adesso = _adesso()
        with self._transazione() as c:
            cursore = c.execute(
                """INSERT INTO ricette (titolo, dati, url, autore, piattaforma,
                                        ha_incertezze, creata_il, aggiornata_il)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ricetta.titolo, dati, url,
                    ricetta.fonte.autore if ricetta.fonte else None,
                    ricetta.fonte.piattaforma if ricetta.fonte else None,
                    int(ricetta.ha_incertezze), adesso, adesso,
                ),
            )
            identificativo = int(cursore.lastrowid)
            self._indicizza(c, identificativo, ricetta)
        return identificativo

    def aggiorna(self, identificativo: int, ricetta: Ricetta) -> None:
        """Sostituisce una ricetta esistente — è ciò che accade quando l'utente
        corregge a mano un ingrediente nell'interfaccia."""
        with self._transazione() as c:
            modificate = c.execute(
                """UPDATE ricette
                      SET titolo = ?, dati = ?, autore = ?, ha_incertezze = ?, aggiornata_il = ?
                    WHERE id = ?""",
                (
                    ricetta.titolo, ricetta.to_json(indent=None),
                    ricetta.fonte.autore if ricetta.fonte else None,
                    int(ricetta.ha_incertezze), _adesso(), identificativo,
                ),
            ).rowcount
            if not modificate:
                raise ErroreLibreria(f"Nessuna ricetta con id {identificativo}")
            c.execute("DELETE FROM ricette_fts WHERE rowid = ?", (identificativo,))
            self._indicizza(c, identificativo, ricetta)

    def elimina(self, identificativo: int) -> bool:
        with self._transazione() as c:
            eliminate = c.execute("DELETE FROM ricette WHERE id = ?", (identificativo,)).rowcount
            c.execute("DELETE FROM ricette_fts WHERE rowid = ?", (identificativo,))
        return bool(eliminate)

    @staticmethod
    def _indicizza(c: sqlite3.Connection, identificativo: int, ricetta: Ricetta) -> None:
        c.execute(
            "INSERT INTO ricette_fts (rowid, titolo, ingredienti, procedimento, categorie) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                identificativo,
                ricetta.titolo,
                " ".join(i.nome for i in ricetta.ingredienti),
                " ".join(ricetta.procedimento),
                " ".join(ricetta.categorie),
            ),
        )

    # ---- lettura ------------------------------------------------------------------

    def leggi(self, identificativo: int) -> Ricetta | None:
        riga = self._conn.execute(
            "SELECT dati FROM ricette WHERE id = ?", (identificativo,)
        ).fetchone()
        return Ricetta.from_dict(json.loads(riga["dati"])) if riga else None

    def id_per_url(self, url: str) -> int | None:
        riga = self._conn.execute("SELECT id FROM ricette WHERE url = ?", (url,)).fetchone()
        return int(riga["id"]) if riga else None

    def elenca(self, cerca: str | None = None, limite: int = 200, scarto: int = 0) -> list[dict]:
        """Elenco sintetico per la libreria. Con `cerca` valorizzato usa l'indice full-text.

        Ogni voce contiene il minimo per disegnare una scheda: id, titolo, autore,
        numero di ingredienti e se ci sono incertezze da rivedere.
        """
        if cerca and cerca.strip():
            righe = self._conn.execute(
                """SELECT r.id, r.titolo, r.autore, r.url, r.piattaforma,
                          r.ha_incertezze, r.creata_il, r.dati
                     FROM ricette_fts f
                     JOIN ricette r ON r.id = f.rowid
                    WHERE ricette_fts MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?""",
                (_query_fts(cerca), limite, scarto),
            ).fetchall()
        else:
            righe = self._conn.execute(
                """SELECT id, titolo, autore, url, piattaforma, ha_incertezze, creata_il, dati
                     FROM ricette ORDER BY creata_il DESC LIMIT ? OFFSET ?""",
                (limite, scarto),
            ).fetchall()

        risultato = []
        for riga in righe:
            dati = json.loads(riga["dati"])
            risultato.append({
                "id": riga["id"],
                "titolo": riga["titolo"],
                "autore": riga["autore"],
                "url": riga["url"],
                "piattaforma": riga["piattaforma"],
                "ha_incertezze": bool(riga["ha_incertezze"]),
                "creata_il": riga["creata_il"],
                "porzioni": dati.get("porzioni"),
                "tempo_totale_min": dati.get("tempo_totale_min"),
                "categorie": dati.get("categorie") or [],
                "n_ingredienti": len(dati.get("ingredienti") or []),
                "copertina": (dati.get("immagini") or [None])[0],
            })
        return risultato

    def tutte(self) -> list[Ricetta]:
        righe = self._conn.execute("SELECT dati FROM ricette ORDER BY creata_il DESC").fetchall()
        return [Ricetta.from_dict(json.loads(r["dati"])) for r in righe]

    def conta(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM ricette").fetchone()["n"])


def _query_fts(cerca: str) -> str:
    """Trasforma una ricerca dell'utente in una query FTS5 sicura.

    I termini vengono citati (così i caratteri speciali di FTS5 non diventano sintassi
    per sbaglio) e si aggiunge `*` per la corrispondenza per prefisso: cercando "zucch"
    si trovano sia "zucchine" sia "zucchero".
    """
    termini = [t for t in cerca.replace('"', " ").split() if t]
    return " ".join(f'"{t}"*' for t in termini) if termini else '""'
