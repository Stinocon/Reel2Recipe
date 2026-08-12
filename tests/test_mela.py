"""Test dell'export verso Mela e del passaggio bozza → ricetta.

Il collaudo vero resta aprire un `.melarecipe` in Mela su iOS (v. README). Questi test
proteggono le due cose che si rompono in silenzio: i separatori `\\n` fra le righe di
ingredienti e procedimento, e il formato dei titoli di gruppo `#`.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from reel2recipe.mela import (
    leggi_melarecipe,
    righe_ingredienti,
    scrivi_melarecipe,
    scrivi_melarecipes,
    verso_melarecipe,
)
from reel2recipe.recipe import Fonte, Ricetta, da_bozza


BOZZA = {
    "titolo": "Tiramisù al pistacchio",
    "porzioni": "6 persone",
    "tempo_preparazione_min": 25,
    "tempo_cottura_min": 0,
    "ingredienti": [
        {"quantita_raw": "250", "unita_raw": "g", "nome": "mascarpone", "gruppo": "Per la crema"},
        {"quantita_raw": "3", "unita_raw": None, "nome": "uova", "gruppo": "Per la crema"},
        {"quantita_raw": "1", "unita_raw": "cup", "nome": "zucchero semolato", "gruppo": "Per la crema"},
        {"quantita_raw": "200", "unita_raw": "g", "nome": "savoiardi", "gruppo": "Per la base"},
        {"quantita_raw": "q.b.", "unita_raw": None, "nome": "cacao amaro", "gruppo": "Per la base"},
    ],
    "procedimento": [
        "Monta i tuorli con lo zucchero fino a ottenere un composto chiaro.",
        "Inforna a 350°F per 20 minuti.",
    ],
    "note": ["Riposa in frigo almeno 4 ore."],
    "categorie": ["Dolci", "Senza cottura"],
    "confidenza": {"ingredienti": "alta", "procedimento": "media"},
    "lacune": [],
}


@pytest.fixture
def ricetta() -> Ricetta:
    return da_bozza(
        BOZZA,
        fonte=Fonte.adesso(
            url="https://www.instagram.com/reel/ABC123/",
            autore="cucina_test",
            piattaforma="instagram",
        ),
    )


# ----------------------------------------------------------------------------------
# Bozza → ricetta
# ----------------------------------------------------------------------------------


def test_bozza_normalizza_le_quantita(ricetta):
    """La cup di zucchero deve essere diventata 200 g passando per units.py."""
    zucchero = next(i for i in ricetta.ingredienti if i.nome == "zucchero semolato")
    assert (zucchero.quantita.valore, zucchero.quantita.unita) == (200.0, "g")


def test_bozza_converte_le_temperature(ricetta):
    """350°F nel procedimento deve diventare 175 °C, e la sostituzione va tracciata.

    La traccia si controlla sulla sostituzione ("350°F → 175 °C") e non su una parola
    della frase che la introduce: quella dipende da lingua e sistema, il fatto che la
    modifica al testo dell'autore sia dichiarata no.
    """
    assert any("175 °C" in p for p in ricetta.procedimento)
    assert not any("350" in p and "F" in p for p in ricetta.procedimento)
    assert any("350°F" in n and "175 °C" in n for n in ricetta.note)


def test_bozza_raccoglie_le_lacune(ricetta):
    """Il "q.b." del cacao non è una lacuna, ma la ricetta deve saper dire se ha incertezze."""
    assert ricetta.ha_incertezze


def test_tempo_totale(ricetta):
    assert ricetta.tempo_totale_min() == 25


def test_round_trip_del_modello(ricetta):
    """Ricetta → dict → Ricetta senza perdere quantità né provenienze."""
    ricostruita = Ricetta.from_dict(json.loads(ricetta.to_json()))
    assert ricostruita.titolo == ricetta.titolo
    assert len(ricostruita.ingredienti) == len(ricetta.ingredienti)
    for a, b in zip(ricetta.ingredienti, ricostruita.ingredienti):
        assert a.riga_mela() == b.riga_mela()
        assert a.quantita.provenienza is b.quantita.provenienza


# ----------------------------------------------------------------------------------
# Formato Mela
# ----------------------------------------------------------------------------------


def test_ingredienti_sono_una_stringa_separata_da_newline(ricetta):
    """È l'errore più facile da fare: Mela vuole una stringa, non un array."""
    d = verso_melarecipe(ricetta)
    assert isinstance(d["ingredients"], str)
    assert "\n" in d["ingredients"]
    assert isinstance(d["instructions"], str)


def test_gruppi_come_intestazioni_con_cancelletto(ricetta):
    righe = righe_ingredienti(ricetta)
    assert "# Per la crema" in righe
    assert "# Per la base" in righe
    # L'intestazione deve precedere i suoi ingredienti.
    assert righe.index("# Per la crema") < righe.index("250 g mascarpone")


def test_gruppo_unico_non_produce_intestazione():
    """Se c'è un solo gruppo (o nessuno), l'intestazione è rumore."""
    r = da_bozza({
        "titolo": "Pasta al burro",
        "ingredienti": [{"quantita_raw": "100", "unita_raw": "g", "nome": "burro"}],
        "procedimento": ["Sciogli il burro."],
    })
    assert not any(riga.startswith("#") for riga in righe_ingredienti(r))


def test_qb_reso_alla_italiana(ricetta):
    d = verso_melarecipe(ricetta)
    assert "cacao amaro q.b." in d["ingredients"]


def test_procedimento_non_numerato(ricetta):
    """La numerazione la mette Mela: aggiungerla qui produceva "1 1. Monta i tuorli…".

    Visto sulla prima ricetta aperta davvero nell'app, non deducibile dal formato.
    """
    d = verso_melarecipe(ricetta)
    assert d["instructions"].startswith("Monta i tuorli")
    assert "1. " not in d["instructions"]


def test_numerazione_gia_presente_viene_tolta(ricetta):
    """Stesso doppione per l'altra strada: un passo che arriva già numerato dal modello."""
    ricetta.procedimento = ["1. Monta i tuorli.", "2) Inforna.", "3 - Sforna."]
    righe = verso_melarecipe(ricetta)["instructions"].split("\n")
    assert righe == ["Monta i tuorli.", "Inforna.", "Sforna."]


def test_passo_che_inizia_per_cifra_resta_intero(ricetta):
    """Una cifra iniziale non è sempre un'etichetta di elenco: qui è la quantità.

    Il terzo caso è quello che costringe il criterio a essere stretto: "5 - 6 minuti" ha la
    forma di una numerazione, ma togliere "5 - " cambierebbe un tempo di cottura in silenzio.
    """
    ricetta.procedimento = [
        "200 g di farina in una ciotola.",
        "180 °C per 20 minuti.",
        "5 - 6 minuti di cottura, finché non è dorato.",
    ]
    righe = verso_melarecipe(ricetta)["instructions"].split("\n")
    assert righe == [
        "200 g di farina in una ciotola.",
        "180 °C per 20 minuti.",
        "5 - 6 minuti di cottura, finché non è dorato.",
    ]


def test_campi_obbligatori_e_tipi(ricetta):
    d = verso_melarecipe(ricetta)
    for chiave in ("id", "title", "text", "images", "categories", "yield", "prepTime",
                   "cookTime", "totalTime", "ingredients", "instructions", "notes",
                   "nutrition", "link", "favorite", "wantToCook", "date"):
        assert chiave in d, f"campo mancante nel .melarecipe: {chiave}"
    assert isinstance(d["images"], list)
    assert isinstance(d["categories"], list)
    assert isinstance(d["favorite"], bool)
    assert isinstance(d["date"], float)


def test_identificativo_dallurl(ricetta):
    """Con un URL, l'id è l'URL senza schema: dà a Mela una chiave stabile per gli aggiornamenti."""
    assert verso_melarecipe(ricetta)["id"] == "www.instagram.com/reel/ABC123"


def test_link_valorizzato_per_attribuzione(ricetta):
    """L'attribuzione all'autore originale non è opzionale."""
    d = verso_melarecipe(ricetta)
    assert d["link"] == "https://www.instagram.com/reel/ABC123/"
    assert "cucina_test" in d["notes"]


def test_durate_leggibili():
    r = da_bozza({"titolo": "X", "tempo_preparazione_min": 90, "tempo_cottura_min": 45})
    d = verso_melarecipe(r)
    assert d["prepTime"] == "1 h 30 min"
    assert d["cookTime"] == "45 min"
    assert d["totalTime"] == "2 h 15 min"


def test_categorie_senza_virgole():
    """Mela non ammette virgole nei nomi di categoria: verrebbero spezzate all'import."""
    r = da_bozza({"titolo": "X", "categorie": ["Dolci, freddi"]})
    assert "," not in verso_melarecipe(r)["categories"][0]


def test_lacune_finiscono_nelle_note():
    """Una stima non deve mai passare per un dato certo: va scritta nella ricetta."""
    r = da_bozza({
        "titolo": "Test",
        "ingredienti": [{"quantita_raw": "1", "unita_raw": "cup", "nome": "gorgonzola"}],
    })
    note = verso_melarecipe(r)["notes"]
    assert "Da verificare" in note
    assert "densità sconosciuta" in note


# ----------------------------------------------------------------------------------
# Scrittura su disco
# ----------------------------------------------------------------------------------


def test_scrittura_e_rilettura(ricetta, tmp_path):
    percorso = scrivi_melarecipe(ricetta, tmp_path)
    assert percorso.suffix == ".melarecipe"
    riletta = leggi_melarecipe(percorso)
    assert riletta["title"] == "Tiramisù al pistacchio"
    assert "250 g mascarpone" in riletta["ingredients"]


def test_non_sovrascrive_export_precedenti(ricetta, tmp_path):
    primo = scrivi_melarecipe(ricetta, tmp_path)
    secondo = scrivi_melarecipe(ricetta, tmp_path)
    assert primo != secondo
    assert primo.exists() and secondo.exists()


def test_export_multiplo_e_uno_zip(ricetta, tmp_path):
    percorso = scrivi_melarecipes([ricetta, ricetta], tmp_path / "arretrato")
    assert percorso.suffix == ".melarecipes"
    with zipfile.ZipFile(percorso) as z:
        nomi = z.namelist()
        assert len(nomi) == 2, "i nomi duplicati devono essere disambiguati, non sovrascritti"
        assert all(n.endswith(".melarecipe") for n in nomi)
        assert json.loads(z.read(nomi[0]))["title"] == "Tiramisù al pistacchio"
