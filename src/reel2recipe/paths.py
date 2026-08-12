"""paths.py — where the data lives.

One place decides the root of `workspace/`. That decision used to be repeated identically in
three modules (`store`, `pipeline`, `api`), each with its own `parents[2]`: three copies of
the same fact, which is exactly how two of them end up diverging.

It is also needed because the root is not always "next to the repo". Inside a container — the
Home Assistant add-on — the code sits read-only and the data has to land on the persistent
volume, or the library disappears at the first update. `R2R_WORKSPACE` moves the root without
touching a line of code.

The boundary in `AGENTS.md §7` does not change: whatever the root is, what sits inside it is
third-party material and is neither committed nor redistributed.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def workspace_folder() -> Path:
    """The root of the local data: `R2R_WORKSPACE` if set, `workspace/` otherwise.

    Read on every call and not at import time: a module imported before the environment is
    ready must not freeze the wrong choice.
    """
    if root := os.environ.get("R2R_WORKSPACE", "").strip():
        return Path(root).expanduser()
    return REPO_ROOT / "workspace"


def media_folder() -> Path:
    """Where downloaded video, audio and thumbnails land."""
    return workspace_folder() / "media"


def export_folder() -> Path:
    """Where exported files sit before the browser downloads them."""
    return workspace_folder() / "export"


def database_path() -> Path:
    """The library file."""
    return workspace_folder() / "ricette.db"
