"""Tests for the command line, and in particular for the contract with the add-on.

The Home Assistant add-on lives in another repository (`Stinocon/addons`) and starts this
program with a fixed line, written into its service script. It is a contract between two repos
that neither of them checks: if the shape of the options changes here, nothing over there
notices until the add-on dies on start-up in front of a user.

It has already happened. `--ollama` is a global option, so it goes **before** the subcommand;
the script put it after, argparse exited with code 2, s6 restarted the service for ever, and
Home Assistant — finding nobody listening on the Ingress — answered "502 Bad Gateway". From
the add-on's log:

    r2r: error: unrecognized arguments: --ollama http://127.0.0.1:11434
    WARNING: L'interfaccia si è fermata (codice 2). Fermo l'addon.

These tests hold that line still.
"""

from __future__ import annotations

import pytest

from reel2recipe.cli import _parser

# The exact line from `rootfs/etc/services.d/reel2recipe/run` in the add-on's repo.
# If it changes there, it changes here: they are the two halves of one contract.
ADDON_INVOCATION = [
    "--ollama", "http://127.0.0.1:11434",
    "serve",
    "--host", "0.0.0.0",
    "--porta", "8500",
]


def test_the_addon_invocation_is_valid():
    """The line the add-on starts the interface with has to keep being accepted."""
    args = _parser().parse_args(ADDON_INVOCATION)

    assert args.command == "serve"
    assert args.ollama == "http://127.0.0.1:11434"
    # 0.0.0.0 and not 127.0.0.1: what connects is the Ingress, from outside the container.
    assert args.host == "0.0.0.0"
    assert args.port == 8500


def test_a_global_option_after_the_subcommand_is_refused():
    """The wrong shape stays wrong, and this test says why the contract is fragile.

    It is not an argparse defect to be worked around: it is the reason the order of the
    options in the service script is not a matter of style.
    """
    with pytest.raises(SystemExit) as exit_:
        _parser().parse_args(["serve", "--ollama", "http://127.0.0.1:11434"])

    # Code 2 is what argparse uses for a usage error, and it is what appeared in the
    # add-on's log.
    assert exit_.value.code == 2


def test_serve_has_the_development_fallbacks():
    """With no options, `r2r serve` stays bound to the local machine."""
    args = _parser().parse_args(["serve"])

    assert args.host == "127.0.0.1"
    assert args.port == 8500
    assert args.ollama == "http://localhost:11434"


# --------------------------------------------------------------------------------------
# The spoken language: an axis of the input, not of the output
# --------------------------------------------------------------------------------------


def test_the_speech_is_recognised_by_itself_by_default():
    """The value reaching Whisper has to be `None`, not "it".

    There used to be an "it" hard-wired into `asr.py` that no option could remove: every reel
    was handed to Whisper declared as Italian, even when it was English. The transcription came
    out mangled and the whole rest of the chain worked on that.
    """
    from reel2recipe import asr
    from reel2recipe.cli import spoken_language

    assert asr.DEFAULT_LANGUAGE is None
    args = _parser().parse_args(["cook", "https://esempio.test/reel"])
    assert args.spoken_language == "auto"
    assert spoken_language(args) is None


@pytest.mark.parametrize("choice, expected", [("auto", None), ("it", "it"), ("en", "en")])
def test_the_speech_can_be_forced(choice, expected):
    from reel2recipe.cli import spoken_language

    args = _parser().parse_args(["cook", "https://esempio.test/reel", "--spoken-language", choice])
    assert spoken_language(args) == expected


def test_the_speech_does_not_follow_the_output_language():
    """Asking for the recipe in English does not mean the reel is spoken in English:
    translating is the normal case, and deducing one from the other would tell Whisper
    something false."""
    from reel2recipe.cli import output_axes, spoken_language

    args = _parser().parse_args(["cook", "https://esempio.test/reel", "--language", "en"])
    assert output_axes(args)["language"] == "en"
    assert spoken_language(args) is None


def test_batch_accepts_the_same_option():
    """`cook` and `batch` must not diverge on the processing options."""
    args = _parser().parse_args(["batch", "elenco.txt", "--spoken-language", "en"])
    assert args.spoken_language == "en"


# --------------------------------------------------------------------------------------
# The Italian aliases are a contract, not a courtesy
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("old, new, value", [
    (["cook", "x", "--lingua", "en"], ["cook", "x", "--language", "en"], "language"),
    (["cook", "x", "--sistema", "metrico"], ["cook", "x", "--system", "metrico"], "system"),
    (["cook", "x", "--didascalia", "t"], ["cook", "x", "--caption", "t"], "caption"),
    (["cook", "x", "--modello", "m"], ["cook", "x", "--model", "m"], "model"),
    (["cook", "x", "--lingua-parlato", "it"], ["cook", "x", "--spoken-language", "it"],
     "spoken_language"),
    (["cook", "x", "--no-salva"], ["cook", "x", "--no-save"], "no_save"),
    (["list", "--cerca", "q"], ["list", "--search", "q"], "search"),
    (["export", "--tutte"], ["export", "--all"], "all"),
    (["export", "1", "--formato", "pdf"], ["export", "1", "--format", "pdf"], "format"),
    (["delete", "1", "--si"], ["delete", "1", "--yes"], "yes"),
    (["serve", "--porta", "9000"], ["serve", "--port", "9000"], "port"),
])
def test_the_italian_names_stay_accepted(old, new, value):
    """The option names have moved to English, but the old ones have to keep working:
    `--porta` appears in the line the add-on starts the server with, and that line lives in
    another repository which would notice nothing until the 502."""
    assert getattr(_parser().parse_args(old), value) == \
           getattr(_parser().parse_args(new), value)


def test_elimina_stays_an_alias_of_delete():
    from_old = _parser().parse_args(["elimina", "7"])
    from_new = _parser().parse_args(["delete", "7"])
    assert from_old.func is from_new.func
    assert from_old.id == from_new.id == 7


def test_the_addon_line_survives_the_rename():
    """The same check as `test_the_addon_invocation_is_valid`, but explicit about the point
    the rename could have broken: the value has to arrive in `port`, the new name."""
    args = _parser().parse_args(ADDON_INVOCATION)
    assert args.port == 8500
