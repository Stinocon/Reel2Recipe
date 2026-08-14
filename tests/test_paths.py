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


def test_the_suite_never_writes_into_the_real_workspace():
    """The guard on the fixture in `conftest.py`, and the reason it exists.

    `workspace/` holds two things that are not ours to touch: third-party material and the
    user's own recipe library (AGENTS.md §7). The suite was writing into it anyway — the API's
    export tests resolve `paths.export_folder()` for real, and `free_path()` adds `-2`, `-3`…
    rather than overwrite, so **286 files named `pane-N.*`** had accumulated next to the user's
    actual exports, one set per run.

    A fixture that stops firing is worse than no fixture, and this one is autouse and silent,
    which is the shape that stops firing without anybody noticing. So it is checked here: the
    paths this run resolves must not be under the repository's own `workspace/`.
    """
    from reel2recipe import paths

    real = paths.REPO_ROOT / "workspace"
    for name, resolved in (("workspace", paths.workspace_folder()),
                           ("export", paths.export_folder()),
                           ("media", paths.media_folder()),
                           ("database", paths.database_path())):
        assert real not in resolved.parents and resolved != real, (
            f"the suite is resolving the real {name} folder ({resolved}): the conftest fixture "
            "that redirects R2R_WORKSPACE is not doing its job, and a test run is writing into "
            "the user's own data"
        )
