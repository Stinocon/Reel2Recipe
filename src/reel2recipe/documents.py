"""documents.py — export to Markdown and PDF, for those without Mela.

`.melarecipe` is the best format *if* you have Mela. Anyone who does not would be left with
nothing to keep, and a recipe you cannot keep has not solved the problem it started from:
finding it again. Hence two formats that ask nobody to install anything in order to read them
— Markdown opens everywhere and stays editable, a PDF prints and can be sent.

Both formats share the same structure (`_blocks`), so a recipe exported either way says the
same things in the same order. Only the rendering differs.

**The gaps are exported.** It is the decision that matters in this module: whoever prints the
recipe and takes it into the kitchen has to see that the sauce had no amounts and that this
weight is an estimate of ours. A clean PDF that hides the uncertainties would be prettier and
worse.

The Markdown has no dependencies. The PDF uses reportlab, which sits in the optional `doc`
extra (`uv sync --extra doc`): it is a pure Python library, with no system libraries to
install alongside — a practical constraint, given this has to run inside a container or on a
Raspberry Pi too.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .mela import ingredient_lines
from .recipe import Recipe, free_path
from .units import UNCERTAIN_PROVENANCES, text_from

# The document strings, per language. As in `mela.py`: few and stable, a dictionary is enough
# and reads better than a translation mechanism. Keys in English, values in whatever language
# the reader gets.
TEXTS = {
    "it": {
        "ingredients": "Ingredienti",
        "method": "Procedimento",
        "notes": "Note",
        "to_check": "Da verificare",
        "source": "Fonte",
        "prep": "preparazione {minutes} min",
        "cooking": "cottura {minutes} min",
        "estimate": "«{name}»: {quantity} è una stima, non un dato del reel",
        "recipe_by": "Ricetta di {author} — {url}",
        "recipe_by_without_url": "Ricetta di {author}",
        "footer": ("Estratta da un reel e riorganizzata con Reel2Recipe - le quantita "
                   "mancanti sono dichiarate, mai indovinate."),
        "md_closing": ("*Estratta da un reel e riorganizzata con "
                       "[Reel2Recipe](https://github.com/Stinocon/Reel2Recipe). "
                       "Le quantità convertite vengono da tabelle di densità verificate; "
                       "quelle mancanti sono dichiarate, mai indovinate.*"),
    },
    "en": {
        "ingredients": "Ingredients",
        "method": "Method",
        "notes": "Notes",
        "to_check": "To check",
        "source": "Source",
        "prep": "prep {minutes} min",
        "cooking": "cooking {minutes} min",
        "estimate": "«{name}»: {quantity} is an estimate, not something the reel stated",
        "recipe_by": "Recipe by {author} — {url}",
        "recipe_by_without_url": "Recipe by {author}",
        "footer": ("Extracted from a reel and reorganised with Reel2Recipe - missing "
                   "quantities are declared, never guessed."),
        "md_closing": ("*Extracted from a reel and reorganised with "
                       "[Reel2Recipe](https://github.com/Stinocon/Reel2Recipe). "
                       "Converted quantities come from verified density tables; "
                       "missing ones are declared, never guessed.*"),
    },
}


def text(language: str, key: str, **data) -> str:
    """A document string in the recipe's language, falling back to Italian."""
    return text_from(TEXTS, language, key, **data)

MARKDOWN_EXTENSION = ".md"
PDF_EXTENSION = ".pdf"


# --------------------------------------------------------------------------------------
# The structure the two formats share
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """A piece of recipe. `kind` says how to render it, not what it means: `title`,
    `subtitle` (the sections), `group` (a grouping of ingredients, which sits *inside* a
    section), `paragraph`, `item` (bulleted list), `step` (numbered)."""

    kind: str
    text: str


def _summary(recipe: Recipe) -> str:
    """The line under the title: servings and times, when there are any. Empty if nothing
    is known."""
    parts = []
    if recipe.servings:
        parts.append(str(recipe.servings))
    if recipe.prep_time_min:
        parts.append(text(recipe.language, "prep", minutes=recipe.prep_time_min))
    if recipe.cook_time_min:
        parts.append(text(recipe.language, "cooking", minutes=recipe.cook_time_min))
    return " · ".join(parts)


def _blocks(recipe: Recipe) -> list[Block]:
    """The recipe as a sequence of blocks, in the order it is meant to be read.

    The order is not arbitrary: first what you need (ingredients), then what to do (method),
    then what to be wary of (to check), and finally whose recipe it is (source). The author's
    own notes come before the gaps because they are theirs, not ours.
    """
    blocks = [Block("title", recipe.title)]

    if summary := _summary(recipe):
        blocks.append(Block("summary", summary))
    if recipe.description:
        blocks.append(Block("paragraph", recipe.description))

    language = recipe.language
    blocks.append(Block("subtitle", text(language, "ingredients")))
    for line in ingredient_lines(recipe):
        # `ingredient_lines` marks group headings with "#", which is Mela's convention. Here
        # they become headings of a lower rank: "Salsa" is a part of the ingredients, not a
        # section on a par with "Procedimento".
        if line.startswith("# "):
            blocks.append(Block("group", line[2:]))
        else:
            blocks.append(Block("item", line))

    if recipe.method:
        blocks.append(Block("subtitle", text(language, "method")))
        blocks.extend(Block("step", step) for step in recipe.method)

    if recipe.notes:
        blocks.append(Block("subtitle", text(language, "notes")))
        blocks.extend(Block("item", note) for note in recipe.notes)

    if warnings := _warnings(recipe):
        blocks.append(Block("subtitle", text(language, "to_check")))
        blocks.extend(Block("item", w) for w in warnings)

    if line := _source_line(recipe):
        blocks.append(Block("subtitle", text(language, "source")))
        blocks.append(Block("paragraph", line))

    return blocks


def _warnings(recipe: Recipe) -> list[str]:
    """The declared gaps, plus the quantities that are estimates rather than data.

    The two are different and both have to be said: "it was not stated" is a hole,
    "un pizzico ≈ 0,5 g" is a number of ours. Whoever is cooking must be able to tell them
    apart.
    """
    lines = list(recipe.gaps)
    estimated = [
        text(recipe.language, "estimate", name=i.name, quantity=i.quantity.text())
        for i in recipe.ingredients
        if i.quantity.provenance in UNCERTAIN_PROVENANCES and i.quantity.value is not None
    ]
    # `recipe.py`'s gaps already name the ingredients with no quantity: only the estimates
    # that have not been declared already are kept, so as not to say the same thing twice.
    return lines + [e for e in estimated if not any(e.split("»")[0] in line for line in lines)]


def _source_line(recipe: Recipe) -> str:
    """The attribution. Not a courtesy detail: the recipe belongs to whoever made it, and the
    reworded method only makes sense while the pointer back to the original stays
    (docs/legal.md)."""
    if not recipe.source:
        return ""
    author, url = recipe.source.author, recipe.source.url
    if author and url:
        return text(recipe.language, "recipe_by", author=author, url=url)
    if author:
        return text(recipe.language, "recipe_by_without_url", author=author)
    return url or ""


# --------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------


def to_markdown(recipe: Recipe) -> str:
    """The recipe in Markdown. No dependencies: it is text."""
    lines: list[str] = []
    step_number = 0

    for block in _blocks(recipe):
        if block.kind == "title":
            lines += [f"# {block.text}"]
        elif block.kind == "summary":
            lines += ["", f"*{block.text}*"]
        elif block.kind in ("subtitle", "group"):
            step_number = 0
            hashes = "##" if block.kind == "subtitle" else "###"
            lines += ["", f"{hashes} {block.text}", ""]
        elif block.kind == "paragraph":
            lines += [block.text, ""]
        elif block.kind == "item":
            lines.append(f"- {block.text}")
        elif block.kind == "step":
            step_number += 1
            lines.append(f"{step_number}. {block.text}")

    body = "\n".join(lines).strip()
    return f"{body}\n\n---\n\n" + text(recipe.language, "md_closing") + "\n"


def write_markdown(recipe: Recipe, folder: Path | str) -> Path:
    """Writes the recipe as a `.md` file. Returns the path created."""
    path = free_path(folder, recipe.file_name(), MARKDOWN_EXTENSION)
    path.write_text(to_markdown(recipe), encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------------------

# The PDF's standard fonts cover Latin-1: Italian accents are there, typographic symbols and
# emoji are not. Rather than letting those turn into black rectangles, the few characters we
# actually produce are translated and the rest is dropped.
_PDF_SUBSTITUTIONS = {
    "≈": "~", "–": "-", "—": "-", "→": "->", "×": "x", "°": "°",
    "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "·": "-", " ": " ",
}


def _pdf_text(value: str) -> str:
    """Reduces the text to what the standard fonts can draw.

    The PDF is the only one of the three formats that cannot render any character: Markdown is
    UTF-8 and so is Mela. Here an emoji left in a note would become a rectangle, which is worse
    than its absence. Accents — the only thing that really matters in Italian — are in Latin-1
    and stay.
    """
    for before, after in _PDF_SUBSTITUTIONS.items():
        value = value.replace(before, after)
    cleaned = value.encode("latin-1", "ignore").decode("latin-1")
    # Vanishing emoji leave double spaces behind: they are closed up, or the text looks wrong.
    return " ".join(cleaned.split())


def _xml_safe(value: str) -> str:
    """reportlab reads paragraphs as mini-XML: `<` and `&` have to be escaped or the export
    blows up on an ingredient containing "<" or a note containing "&"."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class DocumentError(RuntimeError):
    """The export was not produced. The message has to say what to do about it."""


def write_pdf(recipe: Recipe, folder: Path | str) -> Path:
    """Writes the recipe as a laid-out PDF. Returns the path created."""
    try:
        from reportlab.lib.enums import TA_JUSTIFY
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate
    except ImportError as e:
        raise DocumentError(
            "The PDF export needs the «doc» dependencies. Install them with:\n"
            "  uv sync --extra doc\n"
            "Markdown, on the other hand, needs nothing: use --format markdown."
        ) from e

    styles = {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20,
                                leading=25, spaceAfter=2 * mm),
        "summary": ParagraphStyle("summary", fontName="Helvetica-Oblique", fontSize=10,
                                  leading=14, textColor="#666666", spaceAfter=5 * mm),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica-Bold", fontSize=13,
                                   leading=17, spaceBefore=6 * mm, spaceAfter=2 * mm),
        "group": ParagraphStyle("group", fontName="Helvetica-Bold", fontSize=10.5,
                                leading=14, spaceBefore=3 * mm, spaceAfter=1 * mm),
        "paragraph": ParagraphStyle("paragraph", fontName="Helvetica", fontSize=10.5,
                                    leading=15, alignment=TA_JUSTIFY, spaceAfter=2 * mm),
        "item": ParagraphStyle("item", fontName="Helvetica", fontSize=10.5, leading=15),
        "step": ParagraphStyle("step", fontName="Helvetica", fontSize=10.5, leading=15),
    }

    def paragraph(block: Block):
        return Paragraph(_xml_safe(_pdf_text(block.text)), styles[block.kind])

    content: list = []
    # Items and steps are accumulated so they can be rendered as a single list: reportlab
    # numbers the steps itself, so the numbering restarts at every section without counting
    # by hand.
    run: list = []
    run_kind = ""

    def close_run():
        nonlocal run, run_kind
        if not run:
            return
        numbered = run_kind == "step"
        content.append(ListFlowable(
            [ListItem(p, leftIndent=6 * mm) for p in run],
            bulletType="1" if numbered else "bullet",
            bulletFontName="Helvetica",
            # Step numbers should read like the text they introduce; a bullet point, on the
            # other hand, is meant to be discreet.
            bulletFontSize=10.5 if numbered else 8,
            leftIndent=6 * mm, spaceAfter=2 * mm,
        ))
        run, run_kind = [], ""

    for block in _blocks(recipe):
        if block.kind in ("item", "step"):
            if run_kind and block.kind != run_kind:
                close_run()
            run_kind = block.kind
            run.append(paragraph(block))
        else:
            close_run()
            content.append(paragraph(block))
    close_run()

    def footer(canvas, document):
        """The provenance goes in the footer, not at the end of the text.

        Put in the flow, it ended up alone on a nearly empty second page every time the recipe
        filled the first. In the footer it appears on every page, moves nothing, and cannot be
        left orphaned. The page number is there only when there is more than one page.
        """
        canvas.saveState()
        canvas.setFont("Helvetica-Oblique", 7.5)
        canvas.setFillGray(0.55)
        canvas.drawString(20 * mm, 11 * mm, _pdf_text(text(recipe.language, "footer")))
        if canvas.getPageNumber() > 1 or document.page > 1:
            canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()

    path = free_path(folder, recipe.file_name(), PDF_EXTENSION)
    SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
        title=_pdf_text(recipe.title), author="Reel2Recipe",
    ).build(content, onFirstPage=footer, onLaterPages=footer)
    return path
