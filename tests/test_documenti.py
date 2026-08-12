"""Test dell'export in Markdown e PDF.

Questi formati esistono per chi non ha Mela, quindi devono bastare da soli: la ricetta
completa, i gruppi, la fonte, e soprattutto **le incertezze**. Il test che conta più di
tutti è `test_le_lacune_finiscono_nell_export`: un PDF pulito che nasconde le stime sarebbe
più bello e più pericoloso di uno che le dichiara.
"""

from __future__ import annotations

import pytest

from reel2recipe.documenti import (
    ErroreDocumento,
    _testo_pdf,
    _xml_sicuro,
    scrivi_markdown,
    scrivi_pdf,
    verso_markdown,
)
from reel2recipe.recipe import Fonte, Ricetta, da_bozza, percorso_libero

BOZZA = {
    "titolo": "Tiramisù al pistacchio",
    "porzioni": "6 persone",
    "tempo_preparazione_min": 25,
    "ingredienti": [
        {"quantita_raw": "250", "unita_raw": "g", "nome": "ricotta", "gruppo": "Per la crema"},
        {"quantita_raw": "1", "unita_raw": "cup", "nome": "zucchero semolato", "gruppo": "Per la crema"},
        {"quantita_raw": "200", "unita_raw": "g", "nome": "savoiardi", "gruppo": "Per la base"},
        {"quantita_raw": "un pizzico", "unita_raw": None, "nome": "sale", "gruppo": "Per la base"},
    ],
    "procedimento": ["Monta i tuorli con lo zucchero.", "Componi a strati."],
    "note": ["Riposa in frigo almeno 4 ore."],
    "confidenza": {"ingredienti": "alta", "procedimento": "alta"},
    "lacune": ["Il reel non diceva quante uova."],
}


@pytest.fixture
def ricetta() -> Ricetta:
    return da_bozza(BOZZA, fonte=Fonte.adesso(
        url="https://www.instagram.com/reel/ABC123/", autore="cucina_test",
    ))


@pytest.fixture
def semplice() -> Ricetta:
    return da_bozza(
        {"titolo": "Pasta al burro",
         "ingredienti": [{"quantita_raw": "100", "unita_raw": "g", "nome": "burro"}],
         "procedimento": ["Sciogli il burro."], "confidenza": {}, "lacune": []},
    )


# ----------------------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------------------


def test_markdown_ha_la_ricetta_completa(ricetta):
    md = verso_markdown(ricetta)
    assert md.startswith("# Tiramisù al pistacchio")
    assert "## Ingredienti" in md and "## Procedimento" in md
    assert "- 250 g ricotta" in md
    assert "1. Monta i tuorli con lo zucchero." in md
    assert "2. Componi a strati." in md


def test_markdown_annida_i_gruppi_sotto_gli_ingredienti(ricetta):
    """I gruppi sono una parte degli ingredienti, non una sezione pari al procedimento:
    devono stare a un livello di intestazione più basso."""
    md = verso_markdown(ricetta)
    assert "### Per la crema" in md
    assert "### Per la base" in md
    assert "## Per la crema" not in md.replace("### Per la crema", "")


def test_markdown_senza_gruppi_non_inventa_intestazioni(semplice):
    md = verso_markdown(semplice)
    assert "###" not in md
    assert "- 100 g burro" in md


def test_markdown_cita_la_fonte(ricetta):
    """Il procedimento è riformulato con parole nostre: senza il rimando all'originale
    l'attribuzione all'autore si perderebbe (docs/legale.md)."""
    md = verso_markdown(ricetta)
    assert "## Fonte" in md
    assert "cucina_test" in md
    assert "https://www.instagram.com/reel/ABC123/" in md


def test_il_sommario_riporta_porzioni_e_tempi(ricetta):
    assert "6 persone" in verso_markdown(ricetta)
    assert "preparazione 25 min" in verso_markdown(ricetta)


def test_le_lacune_finiscono_nell_export(ricetta):
    """Il test che conta. Chi stampa la ricetta e la porta in cucina deve vedere sia ciò
    che il reel non diceva, sia quali numeri sono stime nostre e non dati."""
    md = verso_markdown(ricetta)
    assert "## Da verificare" in md
    assert "Il reel non diceva quante uova." in md
    # "un pizzico" è diventato 0,5 g: un numero prodotto da noi, e va detto.
    assert "stima" in md and "sale" in md


def test_scrivi_markdown_non_sovrascrive(ricetta, tmp_path):
    primo = scrivi_markdown(ricetta, tmp_path)
    secondo = scrivi_markdown(ricetta, tmp_path)
    assert primo != secondo and primo.exists() and secondo.exists()
    assert primo.read_text(encoding="utf-8").startswith("# Tiramisù")


# ----------------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------------


def test_pdf_e_un_pdf_valido(ricetta, tmp_path):
    pytest.importorskip("reportlab", reason="l'export PDF richiede l'extra «doc»")
    percorso = scrivi_pdf(ricetta, tmp_path)
    assert percorso.suffix == ".pdf"
    assert percorso.read_bytes().startswith(b"%PDF")


def test_pdf_e_markdown_hanno_lo_stesso_nome_di_base(ricetta, tmp_path):
    """Tre vestiti della stessa ricetta devono chiamarsi allo stesso modo, o ritrovarli
    nella cartella di export diventa un indovinello."""
    pytest.importorskip("reportlab", reason="l'export PDF richiede l'extra «doc»")
    assert scrivi_pdf(ricetta, tmp_path).stem == scrivi_markdown(ricetta, tmp_path).stem


def test_senza_reportlab_l_errore_dice_cosa_fare(ricetta, tmp_path, monkeypatch):
    """Se manca l'extra, il messaggio deve indicare il comando e l'alternativa, non
    limitarsi a un ImportError."""
    import builtins

    vero_import = builtins.__import__

    def import_che_nega_reportlab(nome, *args, **kwargs):
        if nome.startswith("reportlab"):
            raise ImportError("simulazione: reportlab non installato")
        return vero_import(nome, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_che_nega_reportlab)
    with pytest.raises(ErroreDocumento) as e:
        scrivi_pdf(ricetta, tmp_path)
    assert "uv sync --extra doc" in str(e.value)
    assert "markdown" in str(e.value).lower()


@pytest.mark.parametrize(
    "prima, dopo",
    [
        ("≈ 4 g", "~ 4 g"),          # il simbolo che produciamo di più
        ("perché", "perché"),         # gli accenti stanno in Latin-1 e restano
        ("buono 🇯🇵📍 davvero", "buono davvero"),   # le emoji spariscono senza lasciare spazi doppi
        ("2–3 cucchiai", "2-3 cucchiai"),
    ],
)
def test_testo_pdf_riduce_solo_cio_che_non_si_puo_disegnare(prima, dopo):
    assert _testo_pdf(prima) == dopo


def test_xml_sicuro_protegge_i_paragrafi():
    """reportlab legge i paragrafi come mini-XML: un ingrediente con "&" farebbe esplodere
    l'export invece di stampare una e commerciale."""
    assert _xml_sicuro("sale & pepe <tutto>") == "sale &amp; pepe &lt;tutto&gt;"


# ----------------------------------------------------------------------------------
# Helper condivisi
# ----------------------------------------------------------------------------------


def test_percorso_libero_non_calpesta_un_export_precedente(tmp_path):
    primo = percorso_libero(tmp_path, "ricetta", ".md")
    primo.write_text("primo", encoding="utf-8")
    secondo = percorso_libero(tmp_path, "ricetta", ".md")
    assert secondo.name == "ricetta-2.md"
    assert primo.read_text(encoding="utf-8") == "primo"


def test_nome_file_e_leggibile_e_sicuro():
    assert da_bozza({"titolo": "Tiramisù al pistacchio!", "ingredienti": [],
                     "procedimento": [], "confidenza": {}, "lacune": []}).nome_file() \
        == "tiramisu-al-pistacchio"


def test_export_in_inglese_traduce_l_involucro(tmp_path):
    """L'involucro — sezioni, attribuzione, piede — segue la lingua della ricetta.

    I nomi degli ingredienti no: quelli vengono dall'estrazione, non si ritraducono a valle
    (per quello serve una nuova estrazione). Qui si verifica ciò che il CODICE controlla:
    le intestazioni.
    """
    from reel2recipe.units import Lingua, Sistema
    r = da_bozza(
        {"titolo": "Pancakes",
         "ingredienti": [{"quantita_raw": "1", "unita_raw": "cup", "nome": "flour"}],
         "procedimento": ["Mix everything."], "confidenza": {},
         "lacune": ["the reel did not say how many eggs"]},
        fonte=Fonte.adesso(url="https://x/y", autore="baker"),
        lingua=Lingua.EN, sistema=Sistema.IMPERIALE,
    )
    md = verso_markdown(r)
    assert "## Ingredients" in md and "## Method" in md
    assert "## To check" in md and "## Source" in md
    assert "Recipe by baker" in md
    # E il sistema imperiale: 1 cup di farina resta 1 cup, non 120 g.
    assert "1 cup flour" in md
    # Nessuna intestazione italiana sopravvissuta.
    assert "Ingredienti" not in md and "Procedimento" not in md


def test_export_in_italiano_resta_italiano(ricetta):
    """Il default non deve essere toccato dal multilingua: senza chiedere nulla, tutto in
    italiano."""
    md = verso_markdown(ricetta)
    assert "## Ingredienti" in md and "## Procedimento" in md
    assert "Ingredients" not in md
