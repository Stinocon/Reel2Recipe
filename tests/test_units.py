"""Golden test della normalizzazione delle quantità.

Ogni valore atteso qui dentro è verificabile a mano con carta e penna a partire dalle
tabelle in `data/`. È il punto: se un giorno qualcuno "migliora" una conversione facendola
indovinare a un modello, questi test devono diventare rossi.

I casi negativi contano quanto quelli positivi. Un ingrediente senza densità nota NON deve
essere convertito in peso: il comportamento corretto è conservare il volume e dichiarare
la lacuna, non produrre un numero plausibile.
"""

from __future__ import annotations

import re

import pytest

from reel2recipe.units import (
    Language,
    Provenance,
    System,
    round_for_kitchen,
    load_tables,
    convert_temperatures_in_text,
    fahrenheit_to_celsius,
    format_number,
    normalise_ingredient,
    parse_quantity,
)


@pytest.fixture(scope="module")
def t():
    return load_tables()


# ----------------------------------------------------------------------------------
# Parsing dei numeri
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "grezza, atteso",
    [
        ("200", (200.0, 200.0)),
        ("1,5", (1.5, 1.5)),
        ("1.5", (1.5, 1.5)),
        ("1/2", (0.5, 0.5)),
        ("3/4", (0.75, 0.75)),
        ("1 1/2", (1.5, 1.5)),
        ("½", (0.5, 0.5)),
        ("1½", (1.5, 1.5)),
        ("2-3", (2.0, 3.0)),
        ("2 o 3", (2.0, 3.0)),
        ("due", (2.0, 2.0)),
        ("mezzo", (0.5, 0.5)),
        ("circa 200", (200.0, 200.0)),
        # Frazione seguita dalla sua unità: prima davano 1 e 2, cioè la frazione buttata
        # via in silenzio. Da un reel vero: «1¼ cups (300 ml) water» diventava 1 ml d'acqua.
        ("1¼ cups", (1.25, 1.25)),
        ("1 1/4 cups", (1.25, 1.25)),
        ("2/3 lb", (2 / 3, 2 / 3)),
        ("1 1/2 cup", (1.5, 1.5)),
        ("2-3 cucchiai", (2.0, 3.0)),
        # La coda alfabetica non deve rubare il numero a chi ce l'ha già in mezzo al testo.
        ("200 circa", (200.0, 200.0)),
    ],
)
def test_parse_quantita(grezza, atteso):
    assert parse_quantity(grezza) == atteso


def test_parse_quantita_senza_numeri():
    """"q.b." non è un numero: deve dare None, non 0. Sono cose diverse."""
    assert parse_quantity("q.b.") is None
    assert parse_quantity("") is None
    assert parse_quantity(None) is None


def test_parse_non_inventa_intervalli():
    """Un trattino fra due parole non è un intervallo."""
    assert parse_quantity("sale-pepe") is None


# ----------------------------------------------------------------------------------
# Conversioni: i casi golden del piano
# ----------------------------------------------------------------------------------


def test_cup_di_farina_fa_120_grammi(t):
    """236,5882365 ml × 0,5072 g/ml = 119,997 g → arrotondato a 120 g."""
    i = normalise_ingredient("farina 00", "1", "cup", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (120.0, "g")
    assert i.quantity.provenance is Provenance.CONVERTED_DENSITY
    assert i.gap is None
    assert i.mela_line().startswith("120 g farina 00")


def test_cup_di_zucchero_non_pesa_come_la_farina(t):
    """Il punto di tutto il progetto: stesso volume, peso diverso del 67%."""
    farina = normalise_ingredient("farina 00", "1", "cup", tables=t)
    zucchero = normalise_ingredient("zucchero semolato", "1", "cup", tables=t)
    assert zucchero.quantity.value == 200.0
    assert farina.quantity.value == 120.0
    assert zucchero.quantity.value > farina.quantity.value


def test_once_in_grammi(t):
    """8 oz × 28,349523125 = 226,8 g → arrotondato a scatti di 5 = 225 g."""
    i = normalise_ingredient("burro", "8", "oz", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (225.0, "g")
    assert i.quantity.provenance is Provenance.CONVERTED_UNIT


def test_grammi_restano_grammi(t):
    i = normalise_ingredient("farina 00", "250", "g", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (250.0, "g")
    assert i.quantity.provenance is Provenance.DECLARED


@pytest.mark.parametrize(
    "quantita_raw, nome, valore, unita",
    [
        ("80g", "maiale", 80.0, "g"),          # attaccata, come la scrivono le didascalie
        ("80 g", "maiale", 80.0, "g"),         # separata da uno spazio ma nello stesso campo
        ("200ml", "latte", 200.0, "ml"),
        ("1cup", "farina 00", 120.0, "g"),     # passa anche per la densità
        ("1 1/2 cup", "farina 00", 180.0, "g"),  # 1,5 e non 1: il numero va riletto intero
    ],
)
def test_unita_attaccata_alla_quantita(t, quantita_raw, nome, valore, unita):
    """L'unità rimasta dentro `quantita_raw` non deve andare persa.

    Il modello non sempre separa i due campi. Prima di questo recupero l'unità spariva e il
    numero veniva letto come un conteggio di pezzi: "80g di maiale" diventava "80 maiale",
    cioè ottanta maiali. È il caso visto su un reel vero.
    """
    i = normalise_ingredient(nome, quantita_raw, None, tables=t)
    assert (i.quantity.value, i.quantity.unit) == (valore, unita)
    assert i.quantity.provenance is not Provenance.COUNT


@pytest.mark.parametrize(
    "nome, unita_raw, atteso",
    [
        ("Dashi", "polvere", "Dashi (polvere)"),        # "Dashi in polvere" spezzato male
        ("cipolla", "tritata", "cipolla (tritata)"),
        ("pomodori", "a grappolo", "pomodori (a grappolo)"),
    ],
)
def test_una_qualita_senza_numero_non_diventa_un_unita(t, nome, unita_raw, atteso):
    """Senza un numero davanti, una parola non riconosciuta non è un'unità.

    Il modello a volte spezza "Dashi in polvere" in nome="Dashi" e unita_raw="polvere".
    Trattandola da unità finiva davanti al nome e produceva «polvere Dashi», che sarebbe
    arrivato così in Mela e nel PDF. Diventa invece una nota fra parentesi. Caso visto
    davvero, su un reel vero.
    """
    i = normalise_ingredient(nome, None, unita_raw, tables=t)
    assert i.mela_line() == atteso
    assert i.quantity.provenance is Provenance.ABSENT
    assert i.gap, "la quantità resta assente e va dichiarata"


def test_con_un_numero_l_unita_sconosciuta_si_conserva(t):
    """Speculare al precedente: se il numero c'è, «3 grappoli» è una misura vera anche se
    non sappiamo convertirla, e va conservata com'è invece di essere degradata a nota."""
    i = normalise_ingredient("pomodori", "3", "grappoli", tables=t)
    assert i.mela_line() == "3 grappoli pomodori"


@pytest.mark.parametrize(
    "quantita_raw, nome",
    [("2", "uova"), ("2-3", "spicchi"), ("q.b.", "sale"), ("un pizzico", "sale"),
     ("una tazza", "latte")],
)
def test_lo_scorporo_non_tocca_conteggi_e_misure_a_occhio(t, quantita_raw, nome):
    """Il recupero dell'unità deve restare cieco a ciò che non è un'unità di `unita.yaml`:
    "tazza" e "pizzico" stanno in `vaghe.yaml` e vanno gestiti da lì, non convertiti qui."""
    i = normalise_ingredient(nome, quantita_raw, None, tables=t)
    assert i.quantity.provenance in {
        Provenance.COUNT, Provenance.INDETERMINATE, Provenance.ESTIMATED_VAGUE,
    }


def test_chili_in_grammi(t):
    i = normalise_ingredient("patate", "1,5", "kg", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (1500.0, "g")


# ----------------------------------------------------------------------------------
# I casi negativi: quando NON si deve convertire
# ----------------------------------------------------------------------------------


def test_densita_sconosciuta_non_si_inventa(t):
    """"1 cup di gorgonzola" non è convertibile in peso: nessuna densità in tabella.
    Il comportamento corretto è restare in volume e dichiararlo."""
    i = normalise_ingredient("gorgonzola", "1", "cup", tables=t)
    assert i.quantity.unit == "ml"
    assert i.quantity.value == pytest.approx(235.0, abs=5)
    assert i.gap is not None and "densità sconosciuta" in i.gap


def test_liquido_metrico_resta_in_volume(t):
    """"500 ml di latte" → 500 g sarebbe corretto in fisica e sbagliato in cucina."""
    i = normalise_ingredient("latte", "500", "ml", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (500.0, "ml")
    assert i.quantity.provenance is Provenance.DECLARED


def test_liquido_anglosassone_va_in_millilitri_non_in_grammi(t):
    """1 cup di latte → 237 ml (non 244 g): il cuoco misura il latte, non lo pesa."""
    i = normalise_ingredient("latte", "1", "cup", tables=t)
    assert i.quantity.unit == "ml"
    assert i.quantity.value == pytest.approx(235.0, abs=5)


def test_quantita_assente(t):
    i = normalise_ingredient("prezzemolo", None, None, tables=t)
    assert i.quantity.provenance is Provenance.ABSENT
    assert i.gap is not None
    assert i.mela_line() == "prezzemolo"


def test_unita_non_riconosciuta_resta_intatta(t):
    i = normalise_ingredient("misteri", "2", "cucchiaioni", tables=t)
    assert i.gap is not None and "non riconosciuta" in i.gap
    assert "cucchiaioni" in i.mela_line()


# ----------------------------------------------------------------------------------
# Misure a cucchiaio: si conservano, non si convertono
# ----------------------------------------------------------------------------------


def test_cucchiaino_resta_cucchiaino(t):
    """"1 cucchiaino di lievito" è eseguibile; "4 g" richiede una bilancia di precisione."""
    i = normalise_ingredient("lievito per dolci", "1", "cucchiaino", tables=t)
    assert i.quantity.unit == "cucchiaino"
    assert i.quantity.value == 1.0
    assert i.quantity.note is not None and "≈ 4 g" in i.quantity.note
    assert i.mela_line() == "1 cucchiaino lievito per dolci (≈ 4 g)"


def test_tbsp_diventa_cucchiai_al_plurale(t):
    """2 tbsp = 2 × 14,787 = 29,57 ml → arrotondato a 30 ml.

    L'olio è marcato `liquido` in `densita.yaml`, quindi l'equivalente si esprime in
    volume e non in peso: nessuno pesa l'olio, lo si versa.
    """
    i = normalise_ingredient("olio di oliva", "2", "tbsp", tables=t)
    assert i.quantity.unit == "cucchiai"
    assert i.quantity.note is not None and "30 ml" in i.quantity.note
    assert i.mela_line().startswith("2 cucchiai olio di oliva")


def test_cucchiaio_di_secco_riporta_i_grammi(t):
    """1 cucchiaio di cacao = 15 ml × 0,3593 = 5,4 g → arrotondato a 5,5 g."""
    i = normalise_ingredient("cacao amaro", "1", "cucchiaio", tables=t)
    assert i.quantity.note is not None and "g" in i.quantity.note


# ----------------------------------------------------------------------------------
# Conteggi e misure a occhio
# ----------------------------------------------------------------------------------


def test_conteggio_resta_conteggio(t):
    i = normalise_ingredient("uova", "3", None, tables=t)
    assert i.quantity.provenance is Provenance.COUNT
    assert i.mela_line() == "3 uova"


def test_spicchi_contati_con_peso_come_commento(t):
    """Il conteggio resta il dato primario; il peso tipico è solo un aiuto."""
    i = normalise_ingredient("aglio", "2", "spicchi", tables=t)
    assert i.quantity.provenance is Provenance.COUNT
    assert i.quantity.unit == "spicchi"
    assert i.quantity.note is not None and "10 g" in i.quantity.note


def test_qb_non_diventa_un_numero(t):
    i = normalise_ingredient("sale", "q.b.", None, tables=t)
    assert i.quantity.provenance is Provenance.INDETERMINATE
    assert i.quantity.value is None
    assert i.mela_line() == "sale q.b."


def test_pizzico_e_una_stima_dichiarata(t):
    i = normalise_ingredient("sale", "1", "pizzico", tables=t)
    assert i.quantity.provenance is Provenance.ESTIMATED_VAGUE
    assert i.quantity.value == 0.5
    assert i.gap is not None and "stima" in i.gap


def test_filo_di_olio(t):
    i = normalise_ingredient("olio di oliva", "un", "filo", tables=t)
    assert i.quantity.provenance is Provenance.ESTIMATED_VAGUE
    assert (i.quantity.value, i.quantity.unit) == (5.0, "ml")


def test_quantita_indeterminata_dichiarata(t):
    i = normalise_ingredient("basilico", "qualche", "foglia", tables=t)
    assert i.quantity.provenance is Provenance.INDETERMINATE
    assert i.gap is not None


def test_nome_non_si_ripete_con_lunita_di_conteggio(t):
    """I modelli producono spesso unita="uova" e nome="uova": non deve uscire "2 uova uova"."""
    i = normalise_ingredient("uova", "2", "uova", tables=t)
    assert i.mela_line() == "2 uova"


def test_qb_riconosciuto_anche_dentro_una_stringa(t):
    """Un modello può mettere "burro q.b." tutto in unita_raw: va comunque riconosciuto."""
    i = normalise_ingredient("burro", None, "burro q.b.", tables=t)
    assert i.quantity.provenance is Provenance.INDETERMINATE
    assert i.mela_line() == "burro q.b."


def test_densita_non_sporca_la_riga_con_la_fonte(t):
    """La fonte del dato di densità è documentazione, non un commento per l'utente:
    non deve finire fra parentesi nella riga (romperebbe anche il parser di Mela)."""
    i = normalise_ingredient("farina 00", "1", "cup", tables=t)
    assert i.mela_line() == "120 g farina 00"
    assert "cup" not in i.mela_line()


def test_intervallo_conservato(t):
    """"2-3 cucchiai" non diventa "2,5 cucchiai": si tengono entrambi gli estremi."""
    i = normalise_ingredient("olio di oliva", "2-3", "cucchiai", tables=t)
    assert i.quantity.is_range
    assert "2-3" in i.mela_line()


# ----------------------------------------------------------------------------------
# Temperature
# ----------------------------------------------------------------------------------


def test_fahrenheit_in_celsius():
    """(350 − 32) × 5/9 = 176,67 → arrotondato agli scatti del forno (5 °C) = 175 °C."""
    assert fahrenheit_to_celsius(350) == 175.0
    assert fahrenheit_to_celsius(180) == 80.0
    assert fahrenheit_to_celsius(425) == 220.0


def test_conversione_temperature_nel_testo(t):
    testo, sostituzioni = convert_temperatures_in_text(
        "Preriscalda il forno a 350°F e cuoci per 25 minuti.", t
    )
    assert "175 °C" in testo
    assert "350°F" not in testo
    assert len(sostituzioni) == 1


def test_numeri_piccoli_non_sono_temperature(t):
    """"cuoci 20 f..." non deve diventare una conversione: sotto i 100 °F non si tocca."""
    testo, sostituzioni = convert_temperatures_in_text("Aggiungi 20 g di farina.", t)
    assert sostituzioni == []


# ----------------------------------------------------------------------------------
# Arrotondamento e formattazione
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valore, unita, atteso",
    [
        (119.997, "g", 120.0),   # sopra i 100 g: scatti di 5
        (27.148, "g", 27.0),     # fra 10 e 100 g: grammo singolo
        (5.39, "g", 5.5),        # sotto i 10 g: mezzo grammo
        (176.67, "°C", 175.0),   # forno: scatti di 5 °C
    ],
)
def test_arrotonda_cucina(valore, unita, atteso):
    assert round_for_kitchen(valore, unita) == atteso


@pytest.mark.parametrize(
    "valore, atteso",
    [(120.0, "120"), (1.5, "1,5"), (0.5, "0,5"), (200.0, "200")],
)
def test_formatta_numero(valore, atteso):
    assert format_number(valore) == atteso


# ----------------------------------------------------------------------------------
# Integrità delle tabelle
# ----------------------------------------------------------------------------------


def test_tabelle_caricate(t):
    assert t.volume["cup"] == pytest.approx(236.5882365)
    assert t.weight["kg"] == 1000.0
    assert "farina 00" in t.density
    assert "acqua" in t.liquids


def test_alias_risolvono(t):
    for grezza, atteso in [("grammi", "g"), ("cucchiai", "cucchiaio"), ("tablespoons", "tbsp")]:
        assert t.canonical_unit(grezza) == atteso


def test_densita_trova_gli_alias(t):
    """"farina" e "all-purpose flour" devono trovare la stessa voce di "farina 00"."""
    assert t.density_for("farina")[0] == t.density_for("farina 00")[0]
    assert t.density_for("all-purpose flour") is not None


def test_densita_preferisce_la_voce_piu_specifica(t):
    """Fra "farina" e "farina integrale", per "farina integrale" deve vincere la seconda."""
    assert t.density_for("farina integrale")[0] != t.density_for("farina 00")[0]


def test_ogni_voce_risolve_a_se_stessa(t):
    """Nessuna voce deve essere catturata da un'altra.

    `_voce_densita` sceglie la voce più lunga contenuta nel nome, e a parità di lunghezza
    la scelta è arbitraria: "latte di cocco" sarebbe una monetina fra `cocco` e `latte`,
    entrambi di cinque lettere. Una voce che non risolve a se stessa è una voce la cui
    densità non verrà mai usata — un errore silenzioso, il peggior tipo.

    Il rimedio non è nel codice ma nella tabella: ogni composto formabile va scritto per
    esteso (`latte di cocco` accanto a `cocco`). Questo test rende la regola non aggirabile.
    """
    for nome in t.density:
        risolta = t._density_entry(nome)
        assert risolta is not None and risolta[0] == nome, (
            f"«{nome}» risolve a «{risolta[0] if risolta else None}»: "
            f"la sua densità è irraggiungibile. Serve una voce esplicita per il composto."
        )


def test_densita_plausibili(t):
    """Intercetta l'errore di fattore 10 in fase di scrittura.

    Nessun ingrediente da cucina sta fuori da questa forbice: il più leggero è il cacao
    in polvere (0,36), il più pesante il miele (1,42). Un 5,072 al posto di 0,5072 passa
    inosservato all'occhio e non a questo test.
    """
    for chiave, g_per_ml in t.density.items():
        assert 0.2 <= g_per_ml <= 2.0, f"densità implausibile per {chiave}: {g_per_ml} g/ml"


# Riferimenti ammessi come provenienza di una densità. L'elenco è deliberatamente corto:
# poche fonti note e ritrovabili valgono più di molte fonti eterogenee.
#   - USDA FDC <id>   FoodData Central, l'ID rende il dato ritrovabile
#   - King Arthur     la Ingredient Weight Chart, riferimento standard per la panificazione
#   - definizione     per l'acqua: 1 ml = 1 g non è una misura, è la definizione del grammo
_FONTI_AMMESSE = re.compile(r"^(USDA FDC \d+|King Arthur Baking|definizione:)")


def test_ogni_densita_cita_una_fonte_nominata(t):
    """Un numero senza provenienza è un numero di cui non ci si può fidare.

    Non basta che il campo `fonte` sia pieno: "≈ 96 g per cup" ripete il numero invece di
    dire da dove viene, quindi non lo rende verificabile da chi legge. La fonte deve
    nominare un riferimento che qualcun altro possa andare a controllare.
    """
    for chiave, fonte in t.density_source.items():
        assert fonte, f"densità senza fonte dichiarata: {chiave}"
        assert _FONTI_AMMESSE.match(fonte), (
            f"fonte non verificabile per «{chiave}»: {fonte!r}. "
            f"Attesa una citazione nominata (USDA FDC <id>, King Arthur Baking, definizione:)."
        )


# ----------------------------------------------------------------------------------
# Bidirezionalità: due assi, lingua e sistema
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nome, quantita_raw, unita_raw, atteso",
    [
        # Chi cucina in imperiale non vuole i grammi, e nemmeno un doppio arrotondamento:
        # "1 cup" era già eseguibile e resta com'era.
        ("farina 00", "1", "cup", "1 cup farina 00"),
        # Un peso resta un peso, espresso in once. Non diventa 1,67 cup.
        ("farina 00", "200", "g", "7 oz farina 00"),
        # Un volume metrico diventa un volume imperiale, scritto a frazione.
        ("latte", "500", "ml", "2 1/8 cup latte"),
        # Sotto la libbra si usano le once; sopra, le libbre.
        ("burro", "8", "oz", "8 oz burro"),
    ],
)
def test_sistema_imperiale(t, nome, quantita_raw, unita_raw, atteso):
    i = normalise_ingredient(nome, quantita_raw, unita_raw, tables=t,
                               system=System.IMPERIAL)
    assert i.mela_line() == atteso


def test_il_sistema_non_attraversa_la_densita_verso_l_imperiale(t):
    """Verso il metrico un volume secco diventa peso: è il motivo per cui esiste
    `densita.yaml`. Verso l'imperiale NO, e non è una dimenticanza: "200 g di farina" reso
    in cup darebbe 1,67 cup, un numero che nessun misurino sa fare."""
    metrico = normalise_ingredient("farina 00", "1", "cup", tables=t)
    assert metrico.quantity.provenance is Provenance.CONVERTED_DENSITY
    assert metrico.quantity.unit == "g"

    imperiale = normalise_ingredient("farina 00", "1", "cup", tables=t,
                                       system=System.IMPERIAL)
    assert imperiale.quantity.unit == "cup"


@pytest.mark.parametrize(
    "lingua, atteso",
    [(Language.IT, "sale q.b."), (Language.EN, "sale to taste")],
)
def test_la_lingua_cambia_le_etichette_non_i_nomi(t, lingua, atteso):
    """La lingua tocca ciò che scriviamo noi — unità, "q.b.", messaggi — non il nome
    dell'ingrediente, che viene dall'autore del reel e non si traduce a valle."""
    i = normalise_ingredient("sale", None, "q.b.", tables=t, language=lingua)
    assert i.mela_line() == atteso


def test_le_etichette_delle_unita_sono_simmetriche(t):
    """"tbsp" si dice cucchiaio in italiano e "cucchiaio" si dice tbsp in inglese: la
    tabella funziona nei due sensi, che è il punto della bidirezionalità."""
    assert t.label("tbsp", 2, Language.IT) == "cucchiai"
    assert t.label("cucchiaio", 2, Language.EN) == "tbsp"
    assert t.label("tbsp", 1, Language.IT) == "cucchiaio"


@pytest.mark.parametrize(
    "valore, atteso",
    [(0.125, "1/8"), (0.25, "1/4"), (1 / 3, "1/3"), (0.75, "3/4"),
     (1.5, "1 1/2"), (2 + 2 / 3, "2 2/3"), (2.0, "2")],
)
def test_l_imperiale_si_scrive_a_frazioni(valore, atteso):
    """Un misurino ha il quarto e il terzo di cup, non lo 0,23. Le frazioni non sono
    un vezzo tipografico: sono le misure che esistono fisicamente in cucina."""
    assert format_number(valore, System.IMPERIAL) == atteso


def test_il_metrico_resta_a_decimali_con_la_virgola():
    assert format_number(1.5) == "1,5"
    assert format_number(1.5, System.METRIC) == "1,5"


def test_la_nota_di_una_stima_non_contraddice_il_numero(t):
    """La nota si compone dal valore, non si scrive in tabella. Scritta a mano dipendeva
    dalla lingua mentre il numero dipende dal sistema, e usciva "0,5 g (a pinch is about
    1/8 tsp)": una nota che smentisce la quantità che accompagna."""
    for sistema in (System.METRIC, System.IMPERIAL):
        for lingua in (Language.IT, Language.EN):
            i = normalise_ingredient("sale", "un pizzico", None, tables=t,
                                       system=sistema, language=lingua)
            assert i.quantity.note is not None
            # Il numero citato nella nota è esattamente quello della quantità.
            assert format_number(i.quantity.value, sistema) in i.quantity.note
            assert i.quantity.unit in i.quantity.note


def test_nessun_equivalente_ridondante(t):
    """"2 tbsp (≈ 2 tbsp)" è rumore: l'equivalente si mostra solo se cambia unità."""
    assert normalise_ingredient("olio di oliva", "2", "tbsp", tables=t,
                                  system=System.IMPERIAL).quantity.note is None
    assert normalise_ingredient("olio di oliva", "2", "tbsp", tables=t).quantity.note is not None


def test_temperature_verso_l_imperiale(t):
    """Speculare alla conversione verso i Celsius: un forno americano non ha la scala
    Celsius, quindi verso l'imperiale i gradi vanno in Fahrenheit, arrotondati a 25 come
    le manopole (325, 350, 375)."""
    testo, sostituzioni = convert_temperatures_in_text(
        "Inforna a 180 °C per 20 minuti.", t, System.IMPERIAL)
    assert "350 °F" in testo
    assert "180 °C" not in testo
    assert sostituzioni == ["180 °C → 350 °F"]


def test_le_temperature_gia_nel_sistema_non_si_toccano(t):
    """Verso il metrico una temperatura già in Celsius resta com'è: nessuna conversione
    inutile, nessuna sostituzione fantasma nella traccia."""
    testo, sostituzioni = convert_temperatures_in_text("Inforna a 180 °C.", t, System.METRIC)
    assert testo == "Inforna a 180 °C."
    assert sostituzioni == []


# ----------------------------------------------------------------------------------
# Quantità e unità che si contraddicono
# ----------------------------------------------------------------------------------
#
# Il caso viene da un reel vero (sukiyaki nel rice cooker). La fonte scriveva la stessa
# dose due volte, «1¼ cups (300 ml) water», e il modello ne ha mescolato i pezzi: il
# numero della prima rappresentazione con l'unità della seconda. Ne usciva "1 ml" d'acqua
# al posto di 300, con provenienza `dichiarato` — un numero sbagliato presentato come
# certo, cioè esattamente il guasto che questo progetto esiste per evitare.


def test_unita_dentro_la_quantita_vince_su_quella_isolata(t):
    """Fra le due, la coppia internamente coerente è «1¼ cups»: numero e unità stanno nello
    stesso pezzo di testo. Il «ml» veniva da un'altra parte della frase."""
    ingr = normalise_ingredient("acqua", "1¼ cups", "ml", tables=t)
    assert ingr.quantity.unit == "ml"          # l'acqua è liquida: resta un volume
    assert 290 <= ingr.quantity.value <= 300   # 1,25 cup ≈ 296 ml, non 1
    assert ingr.gap is not None


def test_la_contraddizione_viene_dichiarata(t):
    """Indovinare non basta: se la fonte era ambigua, chi cucina deve saperlo."""
    ingr = normalise_ingredient("acqua", "1¼ cups", "ml", tables=t)
    assert "cups" in ingr.gap and "ml" in ingr.gap


def test_contraddizione_anche_in_inglese(t):
    ingr = normalise_ingredient("water", "1¼ cups", "ml", tables=t, language="en")
    assert "check against the source" in ingr.gap


def test_nessun_avviso_se_le_due_unita_concordano(t):
    """«2 cups» + «cup» dicono la stessa cosa: non c'è nulla da segnalare, e riempire le
    lacune di rumore le rende inutili quando contano davvero."""
    assert normalise_ingredient("zucchero", "2 cups", "cup", tables=t).gap is None


def test_la_politica_normale_non_cambia(t):
    """Quando la quantità è solo un numero, l'unità isolata dal modello resta quella buona."""
    ingr = normalise_ingredient("mirin", "4", "cucchiai", tables=t)
    assert ingr.quantity.unit == "cucchiai" and ingr.quantity.value == 4
    assert ingr.gap is None


def test_unita_attaccata_senza_unita_isolata_resta_com_era(t):
    """Il percorso preesistente — «80g» con unita_raw vuoto — non deve essere toccato."""
    ingr = normalise_ingredient("maiale", "80g", "", tables=t)
    assert ingr.quantity.value == 80 and ingr.quantity.unit == "g"
    assert ingr.gap is None


def test_le_lacune_non_si_mangiano_a_vicenda(t):
    """Una densità sconosciuta e una contraddizione sono due cose da sapere, non una."""
    ingr = normalise_ingredient("polvere di stelle", "2 cups", "ml", tables=t)
    assert "cups" in ingr.gap
    assert "densità" in ingr.gap


# ----------------------------------------------------------------------------------
# Ingressi malformati: il modello mette la cosa giusta nel campo sbagliato
# ----------------------------------------------------------------------------------
#
# Tutti e due i casi vengono da reel veri. Non si correggono nel prompt perché il prompt
# chiede e il modello concede quando gli pare: qui la difesa è deterministica.


def test_una_parola_fra_parentesi_non_e_un_unita(t):
    """«1 melanzana bianca (facoltativa)» diventava «1 (facoltativa) melanzana bianca».

    La regola che degrada una non-unità a nota non scattava perché richiede che manchi il
    numero, e qui il numero c'è. Le parentesi bastano da sole: nessuna unità di misura si
    scrive fra parentesi.
    """
    ingr = normalise_ingredient("melanzana bianca", "1", "(facoltativa)", tables=t)
    assert ingr.mela_line() == "1 melanzana bianca (facoltativa)"
    assert ingr.quantity.provenance is Provenance.COUNT
    assert ingr.gap is None


@pytest.mark.parametrize("nome", ["semi di sesamo q.b.", "olio q.b.", "burro a piacere"])
def test_qb_attaccato_al_nome_resta_una_quantita_indeterminata(t, nome):
    """Il modello attacca «q.b.» al nome invece di lasciarlo nella quantità.

    Il codice non vedeva alcuna indicazione e dichiarava «quantità non indicata nel reel»:
    una lacuna falsa, perché il reel aveva indicato eccome. Una lacuna che mente vale meno
    di nessuna lacuna, perché insegna a non fidarsi delle altre.
    """
    ingr = normalise_ingredient(nome, "", "", tables=t)
    assert ingr.quantity.provenance is Provenance.INDETERMINATE
    assert ingr.mela_line().endswith("q.b.")
    assert not ingr.mela_line().endswith("q.b. q.b."), "il marcatore non va ripetuto"


def test_una_parola_vaga_nel_mezzo_del_nome_non_conta(t):
    """Il confronto è ancorato in coda ed esatto: «pomodori poco maturi» è un ingrediente
    senza quantità, non una quantità indeterminata. Un match per contenimento qui
    trasformerebbe mezzo ricettario in «q.b.»."""
    ingr = normalise_ingredient("pomodori poco maturi", "", "", tables=t)
    assert ingr.quantity.provenance is Provenance.ABSENT
    assert "poco maturi" in ingr.mela_line()


def test_un_nome_fatto_solo_dell_espressione_resta_intatto(t):
    """Staccare «q.b.» da un nome che è solo «q.b.» lascerebbe un ingrediente senza nome."""
    assert normalise_ingredient("q.b.", "", "", tables=t).mela_line() == "q.b."


def test_qb_isolato_nell_unita_continua_a_funzionare(t):
    """Il percorso preesistente non si tocca."""
    ingr = normalise_ingredient("sale", "", "q.b.", tables=t)
    assert ingr.quantity.provenance is Provenance.INDETERMINATE
    assert ingr.mela_line() == "sale q.b."


def test_il_messaggio_italiano_ha_le_parentesi_bilanciate(t):
    """Finisce nelle note dei file esportati: una parentesi spaiata si vede."""
    ingr = normalise_ingredient("Dashi", None, "polvere", tables=t)
    assert ingr.gap.count("(") == ingr.gap.count(")")


@pytest.mark.parametrize(
    "nome, valore, unita",
    [("sale (un pizzico)", 0.5, "g"), ("olio (un filo)", 5.0, "ml")],
)
def test_misura_a_occhio_fra_parentesi_nel_nome(t, nome, valore, unita):
    """«1 bel pizzico di sale» arriva dal modello come nome="sale (un pizzico)" e quantità
    vuota. Dichiarare "quantità non indicata" sarebbe falso: la misura c'è, è a occhio, e
    `vaghe.yaml` sa quanto pesa. Terza variante dello stesso pattern, da un reel vero."""
    ingr = normalise_ingredient(nome, "", "", tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (valore, unita)
    assert ingr.quantity.provenance is Provenance.ESTIMATED_VAGUE
    assert ingr.gap, "una stima va sempre dichiarata come tale"


def test_un_parentetico_che_non_e_una_misura_resta_una_nota(t):
    """Il criterio non sono le parentesi ma il fatto che dentro ci sia una misura nota.
    «crema di cocco (lattina di cocco parte sopra più grassa)» descrive l'ingrediente."""
    nome = "crema di cocco (lattina di cocco parte sopra più grassa)"
    ingr = normalise_ingredient(nome, "70", "g", tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (70.0, "g")
    assert "lattina" in ingr.mela_line()


def test_una_misura_gia_isolata_vince_sul_parentetico(t):
    """Se il modello ha già messo una quantità nel suo campo, il parentetico è una nota."""
    ingr = normalise_ingredient("sale (un pizzico)", "5", "g", tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (5.0, "g")


def test_un_nome_fatto_solo_del_parentetico_resta_intatto(t):
    assert normalise_ingredient("(un pizzico)", "", "", tables=t).mela_line() == "(un pizzico)"


@pytest.mark.parametrize("apostrofo", ["'", "’", "‘"])
def test_l_apostrofo_tipografico_non_nasconde_una_misura_vaga(t, apostrofo):
    """Le tastiere iOS e le didascalie di Instagram scrivono l'apostrofo curvo, e le voci di
    `vaghe.yaml` sono scritte con quello ASCII. Senza normalizzarli, «bicchiere d'acqua»
    usciva come «1 bicchiere d'acqua acqua» con provenienza `dichiarato`: una riga senza
    senso presentata come dato certo, che è il guasto che questo progetto esiste per evitare."""
    ingr = normalise_ingredient("acqua", "1", f"bicchiere d{apostrofo}acqua", tables=t)
    assert ingr.quantity.provenance is Provenance.ESTIMATED_VAGUE
    assert (ingr.quantity.value, ingr.quantity.unit) == (200.0, "ml")


@pytest.mark.parametrize("nota", ["q.b.", "(q.b.)", "un pizzico"])
def test_una_misura_finita_nelle_note_resta_una_misura(t, nota):
    """Quarta variante dello stesso pattern, e l'unica trovata da un test invece che da un
    reel: quando il modello non sa dove mettere «q.b.» lo infila in `note`. Il codice non
    vedeva alcuna indicazione e dichiarava «quantità non indicata nel reel»."""
    ingr = normalise_ingredient("sale", "", "", notes=nota, tables=t)
    assert ingr.quantity.provenance in {Provenance.INDETERMINATE, Provenance.ESTIMATED_VAGUE}


@pytest.mark.parametrize("nota", ["a temperatura ambiente", "tritata", "a grappolo"])
def test_una_nota_vera_resta_una_nota(t, nota):
    """Il criterio è che la nota sia una misura NOTA, non che ci sia una nota."""
    ingr = normalise_ingredient("burro", "", "", notes=nota, tables=t)
    assert ingr.quantity.provenance is Provenance.ABSENT
    assert nota in ingr.mela_line()


def test_una_quantita_gia_presente_lascia_la_nota_dov_e(t):
    ingr = normalise_ingredient("farina", "250", "g", notes="q.b.", tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (250.0, "g")
    assert "q.b." in ingr.mela_line()


@pytest.mark.parametrize(
    "grezza, valore",
    [
        ("una presa", 1.0),       # forma canonica
        ("1 presa", 1.0),         # come la scrivono le didascalie
        ("1 bel pizzico", 0.5),   # con un aggettivo in mezzo
        ("2 pizzico", 1.0),       # il numerale moltiplica il valore tipico
    ],
)
def test_un_numerale_non_annulla_la_misura_a_occhio(t, grezza, valore):
    """«1 presa di sale» e «1 bel pizzico» compaiono tali e quali nelle didascalie. La ricerca
    faceva match esatto, non trovava «1 presa» dove la tabella ha «presa», e l'ingrediente
    finiva come conteggio: «1 sale», cioè un sale."""
    ingr = normalise_ingredient("sale", grezza, "", tables=t)
    assert ingr.quantity.provenance is Provenance.ESTIMATED_VAGUE, ingr.mela_line()
    assert ingr.quantity.value == valore


def test_un_numerale_con_un_unita_vera_resta_una_conversione(t):
    """Il ripiego sulla coda non deve rubare i casi che hanno un'unità vera."""
    ingr = normalise_ingredient("farina 00", "2", "cucchiai", tables=t)
    assert ingr.quantity.provenance is not Provenance.ESTIMATED_VAGUE
    assert ingr.quantity.unit == "cucchiai"


@pytest.mark.parametrize("unita_raw, valore, unita", [("(g)", 200.0, "g"), ("(ml)", 200.0, "ml")])
def test_un_unita_vera_fra_parentesi_non_diventa_una_nota(t, unita_raw, valore, unita):
    """«Nessuna unità si scrive fra parentesi» è un criterio quasi giusto, e il quasi costava
    caro: il modello scrive anche `unita_raw="(g)"`, e degradarlo a nota faceva di «200 g di
    farina» un conteggio di duecento farine, senza nemmeno una lacuna."""
    ingr = normalise_ingredient("farina 00", "200", unita_raw, tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (valore, unita)
    assert ingr.quantity.provenance is not Provenance.COUNT


@pytest.mark.parametrize("nome", ["frutta secca (noce)", "cioccolato (tazza)", "vino (bicchiere)"])
def test_un_parentetico_di_una_parola_qualifica_l_ingrediente(t, nome):
    """Molte voci di `vaghe.yaml` hanno alias di una parola — noce, tazza, bicchiere — che
    fra parentesi dopo un nome ne indicano la varietà o il recipiente, non la dose."""
    ingr = normalise_ingredient(nome, "", "", tables=t)
    assert ingr.quantity.provenance is Provenance.ABSENT, ingr.mela_line()
