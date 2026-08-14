"""Shared fixtures. What lives here is the one thing every test module needs to be true.

At the moment that is one thing, and it is about the user's data rather than about testing:
**the suite must not write into the real `workspace/`.**
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _workspace_out_of_the_way(tmp_path_factory):
    """Points `R2R_WORKSPACE` at a temporary folder for the whole run.

    Without it the suite wrote into the user's own `workspace/export/`: the API's export tests
    go through `paths.export_folder()`, which resolves to the real thing, and `free_path()`
    adds `-2`, `-3`… rather than overwriting — by design, so an export never silently replaces
    yesterday's. The two behaviours are each right and their product is not: **286 files named
    `pane-N.*`** had piled up next to the user's actual exported recipes, one set per run, for
    as long as the suite had existed.

    Autouse and session-scoped on purpose. Patching the tests that write today would fix
    today; making it a property of the suite covers the ones nobody has written yet, which is
    the only version of this that stays fixed. `paths.py` reads the variable on **every call**
    rather than at import, so setting it here is enough — no module needs reloading.

    It also makes the suite honest about AGENTS.md §7: third-party material and the personal
    library live in `workspace/`, and a test run is not a reason to put anything there.
    """
    root = tmp_path_factory.mktemp("workspace")
    previous = os.environ.get("R2R_WORKSPACE")
    os.environ["R2R_WORKSPACE"] = str(root)
    yield root
    if previous is None:
        os.environ.pop("R2R_WORKSPACE", None)
    else:
        os.environ["R2R_WORKSPACE"] = previous
