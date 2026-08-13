"""Reel2Recipe — from cooking reels to structured recipes, importable into Mela.

Entirely local: transcription with Whisper on the machine, structuring with an LLM through
Ollama. No paid service, no API key, no data leaving the PC.
"""

from importlib.metadata import PackageNotFoundError, version as _version

# The version has one source of truth, `pyproject.toml`, and is read from the installed
# package's metadata. It used to be repeated here as a literal, and the two diverged at the
# 1.0 release: the wheel was built as 1.0.0 while `r2r --version` kept telling the user 0.1.0
# — the same "one fact, two copies" defect docs/architecture.md §10 describes.
try:
    __version__ = _version("reel2recipe")
except PackageNotFoundError:  # pragma: no cover - running from a source tree, uninstalled
    __version__ = "0.0.0+unknown"
