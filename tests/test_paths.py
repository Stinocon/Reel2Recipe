"""Test della radice dei dati.

Non è un dettaglio di comodo: se `R2R_WORKSPACE` smettesse di essere rispettata, dentro il
container dell'addon Home Assistant la libreria finirebbe nel filesystem effimero e
sparirebbe al primo aggiornamento, senza alcun errore visibile. È il tipo di guasto
silenzioso che un test copre bene e l'uso quotidiano no.
"""

from __future__ import annotations

from pathlib import Path

from reel2recipe import paths
from reel2recipe.store import Libreria, percorso_predefinito


def test_predefinito_e_accanto_al_repo(monkeypatch):
    monkeypatch.delenv("R2R_WORKSPACE", raising=False)
    assert paths.workspace_folder() == paths.REPO_ROOT / "workspace"


def test_variabile_sposta_la_radice(monkeypatch, tmp_path):
    monkeypatch.setenv("R2R_WORKSPACE", str(tmp_path / "dati"))
    assert paths.workspace_folder() == tmp_path / "dati"
    assert paths.media_folder() == tmp_path / "dati" / "media"
    assert paths.export_folder() == tmp_path / "dati" / "export"
    assert paths.database_path() == tmp_path / "dati" / "ricette.db"


def test_variabile_vuota_non_conta(monkeypatch):
    """Una variabile impostata a stringa vuota è un errore di configurazione, non una scelta:
    finirebbe per puntare alla directory corrente, ovunque essa sia."""
    monkeypatch.setenv("R2R_WORKSPACE", "   ")
    assert paths.workspace_folder() == paths.REPO_ROOT / "workspace"


def test_la_libreria_segue_la_variabile(monkeypatch, tmp_path):
    """Il caso che conta davvero: il database nasce dove dice l'ambiente."""
    monkeypatch.setenv("R2R_WORKSPACE", str(tmp_path / "dati"))
    assert percorso_predefinito() == tmp_path / "dati" / "ricette.db"
    with Libreria() as lib:
        assert Path(lib.percorso).is_file()
        assert Path(lib.percorso).parent == tmp_path / "dati"
