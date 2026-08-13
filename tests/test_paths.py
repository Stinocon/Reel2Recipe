"""Tests for the data root.

This is not a convenience detail: if `R2R_WORKSPACE` stopped being honoured, inside the Home
Assistant add-on's container the library would end up on the ephemeral filesystem and vanish
at the first update, with no visible error. It is the kind of silent failure a test covers
well and daily use does not.
"""

from __future__ import annotations

from pathlib import Path

from reel2recipe import paths
from reel2recipe.store import Library, default_path


def test_the_default_sits_next_to_the_repo(monkeypatch):
    monkeypatch.delenv("R2R_WORKSPACE", raising=False)
    assert paths.workspace_folder() == paths.REPO_ROOT / "workspace"


def test_the_variable_moves_the_root(monkeypatch, tmp_path):
    monkeypatch.setenv("R2R_WORKSPACE", str(tmp_path / "dati"))
    assert paths.workspace_folder() == tmp_path / "dati"
    assert paths.media_folder() == tmp_path / "dati" / "media"
    assert paths.export_folder() == tmp_path / "dati" / "export"
    assert paths.database_path() == tmp_path / "dati" / "ricette.db"


def test_an_empty_variable_does_not_count(monkeypatch):
    """A variable set to an empty string is a configuration error, not a choice: it would end
    up pointing at the current directory, wherever that happens to be."""
    monkeypatch.setenv("R2R_WORKSPACE", "   ")
    assert paths.workspace_folder() == paths.REPO_ROOT / "workspace"


def test_the_library_follows_the_variable(monkeypatch, tmp_path):
    """The case that really matters: the database is born where the environment says."""
    monkeypatch.setenv("R2R_WORKSPACE", str(tmp_path / "dati"))
    assert default_path() == tmp_path / "dati" / "ricette.db"
    with Library() as lib:
        assert Path(lib.path).is_file()
        assert Path(lib.path).parent == tmp_path / "dati"
