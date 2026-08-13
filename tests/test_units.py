"""Golden tests for the normalisation of quantities.

Every expected value in here can be checked by hand, with pencil and paper, starting from the
tables in `data/`. That is the point: if one day somebody "improves" a conversion by having a
model guess it, these tests have to go red.

The negative cases count as much as the positive ones. An ingredient with no known density
must NOT be converted into a weight: the correct behaviour is to keep the volume and declare
the gap, not to produce a plausible number.
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
# Parsing numbers
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
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
        # A fraction followed by its unit: these used to give 1 and 2, i.e. the fraction
        # thrown away in silence. From a real reel: "1¼ cups (300 ml) water" became 1 ml.
        ("1¼ cups", (1.25, 1.25)),
        ("1 1/4 cups", (1.25, 1.25)),
        ("2/3 lb", (2 / 3, 2 / 3)),
        ("1 1/2 cup", (1.5, 1.5)),
        ("2-3 cucchiai", (2.0, 3.0)),
        # The alphabetic tail must not steal the number from text that already has one.
        ("200 circa", (200.0, 200.0)),
    ],
)
def test_parse_quantity(raw, expected):
    assert parse_quantity(raw) == expected


def test_parse_quantity_without_numbers():
    """"q.b." is not a number: it has to give None, not 0. They are different things."""
    assert parse_quantity("q.b.") is None
    assert parse_quantity("") is None
    assert parse_quantity(None) is None


def test_parse_invents_no_ranges():
    """A hyphen between two words is not a range."""
    assert parse_quantity("sale-pepe") is None


# ----------------------------------------------------------------------------------
# Conversions: the plan's golden cases
# ----------------------------------------------------------------------------------


def test_a_cup_of_flour_is_120_grams(t):
    """236.5882365 ml × 0.5072 g/ml = 119.997 g → rounded to 120 g."""
    i = normalise_ingredient("farina 00", "1", "cup", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (120.0, "g")
    assert i.quantity.provenance is Provenance.CONVERTED_DENSITY
    assert i.gap is None
    assert i.mela_line().startswith("120 g farina 00")


def test_a_cup_of_sugar_does_not_weigh_the_same_as_flour(t):
    """The point of the whole project: same volume, weight different by 67%."""
    flour = normalise_ingredient("farina 00", "1", "cup", tables=t)
    sugar = normalise_ingredient("zucchero semolato", "1", "cup", tables=t)
    assert sugar.quantity.value == 200.0
    assert flour.quantity.value == 120.0
    assert sugar.quantity.value > flour.quantity.value


def test_ounces_into_grams(t):
    """8 oz × 28.349523125 = 226.8 g → rounded to steps of 5 = 225 g."""
    i = normalise_ingredient("burro", "8", "oz", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (225.0, "g")
    assert i.quantity.provenance is Provenance.CONVERTED_UNIT


def test_grams_stay_grams(t):
    i = normalise_ingredient("farina 00", "250", "g", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (250.0, "g")
    assert i.quantity.provenance is Provenance.DECLARED


@pytest.mark.parametrize(
    "quantity_raw, name, value, unit",
    [
        ("80g", "maiale", 80.0, "g"),          # joined up, as captions write it
        ("80 g", "maiale", 80.0, "g"),         # split by a space but in the same field
        ("200ml", "latte", 200.0, "ml"),
        ("1cup", "farina 00", 120.0, "g"),     # goes through density as well
        ("1 1/2 cup", "farina 00", 180.0, "g"),  # 1.5 and not 1: the number is re-read whole
    ],
)
def test_a_unit_stuck_to_the_quantity(t, quantity_raw, name, value, unit):
    """The unit left inside `quantita_raw` must not be lost.

    The model does not always separate the two fields. Before this recovery the unit vanished
    and the number was read as a count of pieces: "80g di maiale" became "80 maiale", i.e.
    eighty pigs. It is the case seen on a real reel.
    """
    i = normalise_ingredient(name, quantity_raw, None, tables=t)
    assert (i.quantity.value, i.quantity.unit) == (value, unit)
    assert i.quantity.provenance is not Provenance.COUNT


@pytest.mark.parametrize(
    "name, unit_raw, expected",
    [
        ("Dashi", "polvere", "Dashi (polvere)"),        # "Dashi in polvere" split badly
        ("cipolla", "tritata", "cipolla (tritata)"),
        ("pomodori", "a grappolo", "pomodori (a grappolo)"),
    ],
)
def test_a_quality_without_a_number_does_not_become_a_unit(t, name, unit_raw, expected):
    """Without a number in front of it, an unrecognised word is not a unit.

    The model sometimes splits "Dashi in polvere" into nome="Dashi" and unita_raw="polvere".
    Treating it as a unit put it in front of the name and produced "polvere Dashi", which
    would have arrived that way in Mela and in the PDF. It becomes a note in brackets instead.
    Seen for real, on a real reel.
    """
    i = normalise_ingredient(name, None, unit_raw, tables=t)
    assert i.mela_line() == expected
    assert i.quantity.provenance is Provenance.ABSENT
    assert i.gap, "the quantity stays absent and has to be declared"


def test_with_a_number_the_unknown_unit_is_kept(t):
    """The mirror of the previous one: if the number is there, "3 grappoli" is a real measure
    even though we cannot convert it, and it is kept as it is rather than demoted to a note."""
    i = normalise_ingredient("pomodori", "3", "grappoli", tables=t)
    assert i.mela_line() == "3 grappoli pomodori"


@pytest.mark.parametrize(
    "quantity_raw, name",
    [("2", "uova"), ("2-3", "spicchi"), ("q.b.", "sale"), ("un pizzico", "sale"),
     ("una tazza", "latte")],
)
def test_the_split_off_leaves_counts_and_eyeball_measures_alone(t, quantity_raw, name):
    """The unit recovery has to stay blind to anything that is not a unit of `unita.yaml`:
    "tazza" and "pizzico" live in `vaghe.yaml` and are handled from there, not converted
    here."""
    i = normalise_ingredient(name, quantity_raw, None, tables=t)
    assert i.quantity.provenance in {
        Provenance.COUNT, Provenance.INDETERMINATE, Provenance.ESTIMATED_VAGUE,
    }


def test_kilos_into_grams(t):
    i = normalise_ingredient("patate", "1,5", "kg", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (1500.0, "g")


# ----------------------------------------------------------------------------------
# The negative cases: when NOT to convert
# ----------------------------------------------------------------------------------


def test_an_unknown_density_is_not_invented(t):
    """"1 cup di gorgonzola" cannot be converted into a weight: no density in the table. The
    correct behaviour is to stay in volume and say so."""
    i = normalise_ingredient("gorgonzola", "1", "cup", tables=t)
    assert i.quantity.unit == "ml"
    assert i.quantity.value == pytest.approx(235.0, abs=5)
    assert i.gap is not None and "densità sconosciuta" in i.gap


def test_a_metric_liquid_stays_a_volume(t):
    """"500 ml di latte" → 500 g would be right in physics and wrong in a kitchen."""
    i = normalise_ingredient("latte", "500", "ml", tables=t)
    assert (i.quantity.value, i.quantity.unit) == (500.0, "ml")
    assert i.quantity.provenance is Provenance.DECLARED


def test_an_anglo_saxon_liquid_goes_to_millilitres_not_grams(t):
    """1 cup of milk → 237 ml (not 244 g): the cook measures milk, does not weigh it."""
    i = normalise_ingredient("latte", "1", "cup", tables=t)
    assert i.quantity.unit == "ml"
    assert i.quantity.value == pytest.approx(235.0, abs=5)


def test_an_absent_quantity(t):
    i = normalise_ingredient("prezzemolo", None, None, tables=t)
    assert i.quantity.provenance is Provenance.ABSENT
    assert i.gap is not None
    assert i.mela_line() == "prezzemolo"


def test_an_unrecognised_unit_stays_intact(t):
    i = normalise_ingredient("misteri", "2", "cucchiaioni", tables=t)
    assert i.gap is not None and "non riconosciuta" in i.gap
    assert "cucchiaioni" in i.mela_line()


# ----------------------------------------------------------------------------------
# Spoon measures: kept, not converted
# ----------------------------------------------------------------------------------


def test_a_teaspoon_stays_a_teaspoon(t):
    """"1 cucchiaino di lievito" can be carried out; "4 g" calls for a precision scale."""
    i = normalise_ingredient("lievito per dolci", "1", "cucchiaino", tables=t)
    assert i.quantity.unit == "cucchiaino"
    assert i.quantity.value == 1.0
    assert i.quantity.note is not None and "≈ 4 g" in i.quantity.note
    assert i.mela_line() == "1 cucchiaino lievito per dolci (≈ 4 g)"


def test_tbsp_becomes_cucchiai_in_the_plural(t):
    """2 tbsp = 2 × 14.787 = 29.57 ml → rounded to 30 ml.

    Oil is marked `liquid` in `densita.yaml`, so the equivalent is expressed as a volume and
    not as a weight: nobody weighs oil, they pour it.
    """
    i = normalise_ingredient("olio di oliva", "2", "tbsp", tables=t)
    assert i.quantity.unit == "cucchiai"
    assert i.quantity.note is not None and "30 ml" in i.quantity.note
    assert i.mela_line().startswith("2 cucchiai olio di oliva")


def test_a_spoon_of_something_dry_reports_the_grams(t):
    """1 tablespoon of cocoa = 15 ml × 0.3593 = 5.4 g → rounded to 5.5 g."""
    i = normalise_ingredient("cacao amaro", "1", "cucchiaio", tables=t)
    assert i.quantity.note is not None and "g" in i.quantity.note


# ----------------------------------------------------------------------------------
# Counts and eyeball measures
# ----------------------------------------------------------------------------------


def test_a_count_stays_a_count(t):
    i = normalise_ingredient("uova", "3", None, tables=t)
    assert i.quantity.provenance is Provenance.COUNT
    assert i.mela_line() == "3 uova"


def test_counted_cloves_with_the_weight_as_a_comment(t):
    """The count stays the primary datum; the typical weight is only a help."""
    i = normalise_ingredient("aglio", "2", "spicchi", tables=t)
    assert i.quantity.provenance is Provenance.COUNT
    assert i.quantity.unit == "spicchi"
    assert i.quantity.note is not None and "10 g" in i.quantity.note


def test_qb_does_not_become_a_number(t):
    i = normalise_ingredient("sale", "q.b.", None, tables=t)
    assert i.quantity.provenance is Provenance.INDETERMINATE
    assert i.quantity.value is None
    assert i.mela_line() == "sale q.b."


def test_a_pinch_is_a_declared_estimate(t):
    i = normalise_ingredient("sale", "1", "pizzico", tables=t)
    assert i.quantity.provenance is Provenance.ESTIMATED_VAGUE
    assert i.quantity.value == 0.5
    assert i.gap is not None and "stima" in i.gap


def test_a_drizzle_of_oil(t):
    i = normalise_ingredient("olio di oliva", "un", "filo", tables=t)
    assert i.quantity.provenance is Provenance.ESTIMATED_VAGUE
    assert (i.quantity.value, i.quantity.unit) == (5.0, "ml")


def test_an_open_ended_quantity_is_declared(t):
    i = normalise_ingredient("basilico", "qualche", "foglia", tables=t)
    assert i.quantity.provenance is Provenance.INDETERMINATE
    assert i.gap is not None


def test_the_name_is_not_repeated_with_the_counting_unit(t):
    """Models often produce unita="uova" and nome="uova": "2 uova uova" must not come out."""
    i = normalise_ingredient("uova", "2", "uova", tables=t)
    assert i.mela_line() == "2 uova"


def test_qb_is_recognised_inside_a_string_too(t):
    """A model may put "burro q.b." entirely into unita_raw: it has to be recognised anyway."""
    i = normalise_ingredient("burro", None, "burro q.b.", tables=t)
    assert i.quantity.provenance is Provenance.INDETERMINATE
    assert i.mela_line() == "burro q.b."


def test_density_does_not_dirty_the_line_with_its_source(t):
    """The source of the density datum is documentation, not a comment for the user: it must
    not end up in brackets on the line (it would also break Mela's parser)."""
    i = normalise_ingredient("farina 00", "1", "cup", tables=t)
    assert i.mela_line() == "120 g farina 00"
    assert "cup" not in i.mela_line()


def test_a_range_is_kept(t):
    """"2-3 cucchiai" does not become "2,5 cucchiai": both ends are kept."""
    i = normalise_ingredient("olio di oliva", "2-3", "cucchiai", tables=t)
    assert i.quantity.is_range
    assert "2-3" in i.mela_line()


# ----------------------------------------------------------------------------------
# Temperature
# ----------------------------------------------------------------------------------


def test_fahrenheit_to_celsius():
    """(350 − 32) × 5/9 = 176.67 → rounded to the oven's steps (5 °C) = 175 °C."""
    assert fahrenheit_to_celsius(350) == 175.0
    assert fahrenheit_to_celsius(180) == 80.0
    assert fahrenheit_to_celsius(425) == 220.0


def test_temperature_conversion_in_text(t):
    text, substitutions = convert_temperatures_in_text(
        "Preriscalda il forno a 350°F e cuoci per 25 minuti.", t
    )
    assert "175 °C" in text
    assert "350°F" not in text
    assert len(substitutions) == 1


def test_small_numbers_are_not_temperatures(t):
    """"cuoci 20 f…" must not become a conversion: below 100 °F nothing is touched."""
    text, substitutions = convert_temperatures_in_text("Aggiungi 20 g di farina.", t)
    assert substitutions == []


# ----------------------------------------------------------------------------------
# Rounding and formatting
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, unit, expected",
    [
        (119.997, "g", 120.0),   # above 100 g: steps of 5
        (27.148, "g", 27.0),     # between 10 and 100 g: single grams
        (5.39, "g", 5.5),        # below 10 g: half a gram
        (176.67, "°C", 175.0),   # oven: steps of 5 °C
    ],
)
def test_round_for_kitchen(value, unit, expected):
    assert round_for_kitchen(value, unit) == expected


@pytest.mark.parametrize(
    "value, expected",
    [(120.0, "120"), (1.5, "1,5"), (0.5, "0,5"), (200.0, "200")],
)
def test_format_number(value, expected):
    assert format_number(value) == expected


# ----------------------------------------------------------------------------------
# Integrity of the tables
# ----------------------------------------------------------------------------------


def test_the_tables_load(t):
    assert t.volume["cup"] == pytest.approx(236.5882365)
    assert t.weight["kg"] == 1000.0
    assert "farina 00" in t.density
    assert "acqua" in t.liquids


def test_the_aliases_resolve(t):
    for raw, expected in [("grammi", "g"), ("cucchiai", "cucchiaio"), ("tablespoons", "tbsp")]:
        assert t.canonical_unit(raw) == expected


def test_density_finds_the_aliases(t):
    """"farina" and "all-purpose flour" have to find the same entry as "farina 00"."""
    assert t.density_for("farina")[0] == t.density_for("farina 00")[0]
    assert t.density_for("all-purpose flour") is not None


def test_density_prefers_the_more_specific_entry(t):
    """Between "farina" and "farina integrale", for "farina integrale" the second has to
    win."""
    assert t.density_for("farina integrale")[0] != t.density_for("farina 00")[0]


def test_every_entry_resolves_to_itself(t):
    """No entry may be captured by another.

    `_density_entry` picks the longest entry contained in the name, and at equal length the
    choice is arbitrary: "latte di cocco" would be a coin toss between `cocco` and `latte`,
    both five letters. An entry that does not resolve to itself is an entry whose density will
    never be used — a silent error, the worst kind.

    The remedy is not in the code but in the table: every compound that can be formed has to be
    written out in full (`latte di cocco` next to `cocco`). This test makes the rule
    unavoidable.
    """
    for name in t.density:
        resolved = t._density_entry(name)
        assert resolved is not None and resolved[0] == name, (
            f"«{name}» resolves to «{resolved[0] if resolved else None}»: its density is "
            f"unreachable. An explicit entry for the compound is needed."
        )


def test_plausible_densities(t):
    """Catches the factor-of-ten error at writing time.

    No kitchen ingredient sits outside this range: the lightest is cocoa powder (0.36), the
    heaviest honey (1.42). A 5.072 in place of 0.5072 goes unnoticed by the eye and not by this
    test.
    """
    for key, g_per_ml in t.density.items():
        assert 0.2 <= g_per_ml <= 2.0, f"implausible density for {key}: {g_per_ml} g/ml"


# The references admitted as the provenance of a density. The list is deliberately short: a
# few known and findable sources are worth more than many heterogeneous ones.
#   - USDA FDC <id>   FoodData Central; the ID makes the datum findable
#   - King Arthur     the Ingredient Weight Chart, the standard baking reference
#   - definizione     for water: 1 ml = 1 g is not a measurement, it is the gram's definition
_ADMITTED_SOURCES = re.compile(r"^(USDA FDC \d+|King Arthur Baking|definizione:)")


def test_every_density_cites_a_named_source(t):
    """A number without a provenance is a number you cannot trust.

    It is not enough for the `source` field to be filled in: "≈ 96 g per cup" repeats the
    number instead of saying where it comes from, so it does not make it checkable by the
    reader. The source has to name a reference somebody else can go and verify.
    """
    for key, source in t.density_source.items():
        assert source, f"density with no declared source: {key}"
        assert _ADMITTED_SOURCES.match(source), (
            f"unverifiable source for «{key}»: {source!r}. "
            f"A named citation was expected (USDA FDC <id>, King Arthur Baking, definizione:)."
        )


# ----------------------------------------------------------------------------------
# Bidirectionality: two axes, language and system
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, quantity_raw, unit_raw, expected",
    [
        # Someone cooking in imperial does not want grams, nor a double rounding: "1 cup" was
        # already executable and stays as it was.
        ("farina 00", "1", "cup", "1 cup farina 00"),
        # A weight stays a weight, expressed in ounces. It does not become 1.67 cup.
        ("farina 00", "200", "g", "7 oz farina 00"),
        # A metric volume becomes an imperial volume, written as a fraction.
        ("latte", "500", "ml", "2 1/8 cup latte"),
        # Below the pound ounces are used; above it, pounds.
        ("burro", "8", "oz", "8 oz burro"),
    ],
)
def test_the_imperial_system(t, name, quantity_raw, unit_raw, expected):
    i = normalise_ingredient(name, quantity_raw, unit_raw, tables=t,
                             system=System.IMPERIAL)
    assert i.mela_line() == expected


def test_the_system_does_not_cross_density_towards_imperial(t):
    """Towards metric a dry volume becomes a weight: that is why `densita.yaml` exists.
    Towards imperial it does NOT, and that is not an oversight: "200 g di farina" rendered in
    cups would give 1.67 cup, a number no measuring cup can make."""
    metric = normalise_ingredient("farina 00", "1", "cup", tables=t)
    assert metric.quantity.provenance is Provenance.CONVERTED_DENSITY
    assert metric.quantity.unit == "g"

    imperial = normalise_ingredient("farina 00", "1", "cup", tables=t,
                                    system=System.IMPERIAL)
    assert imperial.quantity.unit == "cup"


@pytest.mark.parametrize(
    "language, expected",
    [(Language.IT, "sale q.b."), (Language.EN, "sale to taste")],
)
def test_the_language_changes_the_labels_not_the_names(t, language, expected):
    """The language touches what we write — units, "q.b.", messages — not the ingredient's
    name, which comes from the reel's author and is not translated downstream."""
    i = normalise_ingredient("sale", None, "q.b.", tables=t, language=language)
    assert i.mela_line() == expected


def test_the_unit_labels_are_symmetric(t):
    """"tbsp" is said cucchiaio in Italian and "cucchiaio" is said tbsp in English: the table
    works both ways, which is the point of the bidirectionality."""
    assert t.label("tbsp", 2, Language.IT) == "cucchiai"
    assert t.label("cucchiaio", 2, Language.EN) == "tbsp"
    assert t.label("tbsp", 1, Language.IT) == "cucchiaio"


@pytest.mark.parametrize(
    "value, expected",
    [(0.125, "1/8"), (0.25, "1/4"), (1 / 3, "1/3"), (0.75, "3/4"),
     (1.5, "1 1/2"), (2 + 2 / 3, "2 2/3"), (2.0, "2")],
)
def test_imperial_is_written_in_fractions(value, expected):
    """A measuring cup has a quarter and a third of a cup, not 0.23. The fractions are not a
    typographic affectation: they are the measures that physically exist in a kitchen."""
    assert format_number(value, System.IMPERIAL) == expected


def test_metric_stays_in_decimals_with_a_comma():
    assert format_number(1.5) == "1,5"
    assert format_number(1.5, System.METRIC) == "1,5"


def test_the_note_of_an_estimate_does_not_contradict_the_number(t):
    """The note is composed from the value, not written into the table. Written by hand it
    depended on the language while the number depends on the system, and out came "0,5 g (a
    pinch is about 1/8 tsp)": a note that contradicts the quantity it accompanies."""
    for system in (System.METRIC, System.IMPERIAL):
        for language in (Language.IT, Language.EN):
            i = normalise_ingredient("sale", "un pizzico", None, tables=t,
                                     system=system, language=language)
            assert i.quantity.note is not None
            # The number quoted in the note is exactly the quantity's.
            assert format_number(i.quantity.value, system) in i.quantity.note
            assert i.quantity.unit in i.quantity.note


def test_no_redundant_equivalent(t):
    """"2 tbsp (≈ 2 tbsp)" is noise: the equivalent is shown only when the unit changes."""
    assert normalise_ingredient("olio di oliva", "2", "tbsp", tables=t,
                                system=System.IMPERIAL).quantity.note is None
    assert normalise_ingredient("olio di oliva", "2", "tbsp", tables=t).quantity.note is not None


def test_temperatures_towards_imperial(t):
    """The mirror of the conversion towards Celsius: an American oven has no Celsius scale, so
    towards imperial the degrees go to Fahrenheit, rounded to 25 like the dials (325, 350,
    375)."""
    text, substitutions = convert_temperatures_in_text(
        "Inforna a 180 °C per 20 minuti.", t, System.IMPERIAL)
    assert "350 °F" in text
    assert "180 °C" not in text
    assert substitutions == ["180 °C → 350 °F"]


def test_temperatures_already_in_the_system_are_left_alone(t):
    """Towards metric a temperature already in Celsius stays as it is: no pointless
    conversion, no phantom substitution in the trace."""
    text, substitutions = convert_temperatures_in_text("Inforna a 180 °C.", t, System.METRIC)
    assert text == "Inforna a 180 °C."
    assert substitutions == []


# ----------------------------------------------------------------------------------
# Quantity and unit contradicting each other
# ----------------------------------------------------------------------------------
#
# The case comes from a real reel (sukiyaki in a rice cooker). The source wrote the same
# amount twice, "1¼ cups (300 ml) water", and the model mixed the pieces: the number of the
# first representation with the unit of the second. Out came "1 ml" of water instead of 300,
# with provenance `dichiarato` — a wrong number presented as certain, which is exactly the
# failure this project exists to prevent.


def test_the_unit_inside_the_quantity_beats_the_isolated_one(t):
    """Of the two, the internally coherent pair is "1¼ cups": number and unit sit in the same
    piece of text. The "ml" came from another part of the sentence."""
    ingr = normalise_ingredient("acqua", "1¼ cups", "ml", tables=t)
    assert ingr.quantity.unit == "ml"          # water is a liquid: it stays a volume
    assert 290 <= ingr.quantity.value <= 300   # 1.25 cup ≈ 296 ml, not 1
    assert ingr.gap is not None


def test_the_contradiction_is_declared(t):
    """Guessing is not enough: if the source was ambiguous, the cook has to know."""
    ingr = normalise_ingredient("acqua", "1¼ cups", "ml", tables=t)
    assert "cups" in ingr.gap and "ml" in ingr.gap


def test_the_contradiction_in_english_too(t):
    ingr = normalise_ingredient("water", "1¼ cups", "ml", tables=t, language="en")
    assert "check against the source" in ingr.gap


def test_no_warning_when_the_two_units_agree(t):
    """"2 cups" + "cup" say the same thing: there is nothing to flag, and filling the gaps
    with noise makes them useless when they really matter."""
    assert normalise_ingredient("zucchero", "2 cups", "cup", tables=t).gap is None


def test_the_normal_policy_does_not_change(t):
    """When the quantity is only a number, the unit the model isolated stays the good one."""
    ingr = normalise_ingredient("mirin", "4", "cucchiai", tables=t)
    assert ingr.quantity.unit == "cucchiai" and ingr.quantity.value == 4
    assert ingr.gap is None


def test_a_stuck_on_unit_with_no_isolated_unit_stays_as_it_was(t):
    """The pre-existing path — "80g" with an empty unita_raw — must not be touched."""
    ingr = normalise_ingredient("maiale", "80g", "", tables=t)
    assert ingr.quantity.value == 80 and ingr.quantity.unit == "g"
    assert ingr.gap is None


def test_the_gaps_do_not_eat_one_another(t):
    """An unknown density and a contradiction are two things to know, not one."""
    ingr = normalise_ingredient("polvere di stelle", "2 cups", "ml", tables=t)
    assert "cups" in ingr.gap
    assert "densità" in ingr.gap


# ----------------------------------------------------------------------------------
# Malformed inputs: the model puts the right thing in the wrong field
# ----------------------------------------------------------------------------------
#
# Both cases come from real reels. They are not fixed in the prompt because the prompt asks
# and the model concedes when it feels like it: here the defence is deterministic.


def test_a_word_in_brackets_is_not_a_unit(t):
    """"1 melanzana bianca (facoltativa)" became "1 (facoltativa) melanzana bianca".

    The rule that demotes a non-unit to a note did not fire because it requires the number to
    be missing, and here the number is there. The brackets are enough on their own: no unit of
    measurement is written in brackets.
    """
    ingr = normalise_ingredient("melanzana bianca", "1", "(facoltativa)", tables=t)
    assert ingr.mela_line() == "1 melanzana bianca (facoltativa)"
    assert ingr.quantity.provenance is Provenance.COUNT
    assert ingr.gap is None


@pytest.mark.parametrize("name", ["semi di sesamo q.b.", "olio q.b.", "burro a piacere"])
def test_qb_stuck_to_the_name_stays_an_open_ended_quantity(t, name):
    """The model sticks "q.b." onto the name instead of leaving it in the quantity.

    The code saw no indication at all and declared "quantity not given in the reel": a false
    gap, because the reel had indicated it perfectly well. A gap that lies is worth less than
    no gap, because it teaches you not to trust the others.
    """
    ingr = normalise_ingredient(name, "", "", tables=t)
    assert ingr.quantity.provenance is Provenance.INDETERMINATE
    assert ingr.mela_line().endswith("q.b.")
    assert not ingr.mela_line().endswith("q.b. q.b."), "the marker must not be repeated"


def test_a_vague_word_in_the_middle_of_the_name_does_not_count(t):
    """The comparison is anchored at the end and exact: "pomodori poco maturi" is an ingredient
    with no quantity, not an open-ended quantity. A containment match here would turn half a
    recipe book into "q.b."."""
    ingr = normalise_ingredient("pomodori poco maturi", "", "", tables=t)
    assert ingr.quantity.provenance is Provenance.ABSENT
    assert "poco maturi" in ingr.mela_line()


def test_a_name_made_only_of_the_expression_stays_intact(t):
    """Peeling "q.b." off a name that is only "q.b." would leave an ingredient with no name."""
    assert normalise_ingredient("q.b.", "", "", tables=t).mela_line() == "q.b."


def test_qb_isolated_in_the_unit_keeps_working(t):
    """The pre-existing path is not touched."""
    ingr = normalise_ingredient("sale", "", "q.b.", tables=t)
    assert ingr.quantity.provenance is Provenance.INDETERMINATE
    assert ingr.mela_line() == "sale q.b."


def test_the_italian_message_has_balanced_brackets(t):
    """It ends up in the notes of the exported files: an unmatched bracket shows."""
    ingr = normalise_ingredient("Dashi", None, "polvere", tables=t)
    assert ingr.gap.count("(") == ingr.gap.count(")")


@pytest.mark.parametrize(
    "name, value, unit",
    [("sale (un pizzico)", 0.5, "g"), ("olio (un filo)", 5.0, "ml")],
)
def test_an_eyeball_measure_in_brackets_within_the_name(t, name, value, unit):
    """"1 bel pizzico di sale" arrives from the model as nome="sale (un pizzico)" with an empty
    quantity. Declaring "quantity not given" would be false: the measure is there, it is by
    eye, and `vaghe.yaml` knows what it weighs. The third variant of the same pattern, from a
    real reel."""
    ingr = normalise_ingredient(name, "", "", tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (value, unit)
    assert ingr.quantity.provenance is Provenance.ESTIMATED_VAGUE
    assert ingr.gap, "an estimate is always declared as such"


def test_a_parenthetical_that_is_not_a_measure_stays_a_note(t):
    """The criterion is not the brackets but whether a known measure is inside them. "crema di
    cocco (lattina di cocco parte sopra più grassa)" describes the ingredient."""
    name = "crema di cocco (lattina di cocco parte sopra più grassa)"
    ingr = normalise_ingredient(name, "70", "g", tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (70.0, "g")
    assert "lattina" in ingr.mela_line()


def test_a_measure_already_isolated_beats_the_parenthetical(t):
    """If the model has already put a quantity in its own field, the parenthetical is a
    note."""
    ingr = normalise_ingredient("sale (un pizzico)", "5", "g", tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (5.0, "g")


def test_a_name_made_only_of_the_parenthetical_stays_intact(t):
    assert normalise_ingredient("(un pizzico)", "", "", tables=t).mela_line() == "(un pizzico)"


@pytest.mark.parametrize("apostrophe", ["'", "’", "‘"])
def test_the_typographic_apostrophe_does_not_hide_a_vague_measure(t, apostrophe):
    """iOS keyboards and Instagram captions write the curly apostrophe, and `vaghe.yaml`'s
    entries are written with the ASCII one. Without normalising them, "bicchiere d'acqua" came
    out as "1 bicchiere d'acqua acqua" with provenance `dichiarato`: a meaningless line
    presented as certain data, which is the failure this project exists to prevent."""
    ingr = normalise_ingredient("acqua", "1", f"bicchiere d{apostrophe}acqua", tables=t)
    assert ingr.quantity.provenance is Provenance.ESTIMATED_VAGUE
    assert (ingr.quantity.value, ingr.quantity.unit) == (200.0, "ml")


@pytest.mark.parametrize("note", ["q.b.", "(q.b.)", "un pizzico"])
def test_a_measure_that_ended_up_in_the_notes_stays_a_measure(t, note):
    """The fourth variant of the same pattern, and the only one found by a test rather than by
    a reel: when the model does not know where to put "q.b." it slips it into `note`. The code
    saw no indication and declared "quantity not given in the reel"."""
    ingr = normalise_ingredient("sale", "", "", notes=note, tables=t)
    assert ingr.quantity.provenance in {Provenance.INDETERMINATE, Provenance.ESTIMATED_VAGUE}


@pytest.mark.parametrize("note", ["a temperatura ambiente", "tritata", "a grappolo"])
def test_a_real_note_stays_a_note(t, note):
    """The criterion is that the note be a KNOWN measure, not that there be a note."""
    ingr = normalise_ingredient("burro", "", "", notes=note, tables=t)
    assert ingr.quantity.provenance is Provenance.ABSENT
    assert note in ingr.mela_line()


def test_an_already_present_quantity_leaves_the_note_where_it_is(t):
    ingr = normalise_ingredient("farina", "250", "g", notes="q.b.", tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (250.0, "g")
    assert "q.b." in ingr.mela_line()


@pytest.mark.parametrize(
    "raw, value",
    [
        ("una presa", 1.0),       # the canonical form
        ("1 presa", 1.0),         # as the captions write it
        ("1 bel pizzico", 0.5),   # with an adjective in the middle
        ("2 pizzico", 1.0),       # the numeral multiplies the typical value
    ],
)
def test_a_numeral_does_not_cancel_the_eyeball_measure(t, raw, value):
    """"1 presa di sale" and "1 bel pizzico" appear just like that in captions. The lookup did
    an exact match, did not find "1 presa" where the table has "presa", and the ingredient
    ended up as a count: "1 sale", i.e. one salt."""
    ingr = normalise_ingredient("sale", raw, "", tables=t)
    assert ingr.quantity.provenance is Provenance.ESTIMATED_VAGUE, ingr.mela_line()
    assert ingr.quantity.value == value


def test_a_numeral_with_a_real_unit_stays_a_conversion(t):
    """The fallback on the tail must not steal the cases that have a real unit."""
    ingr = normalise_ingredient("farina 00", "2", "cucchiai", tables=t)
    assert ingr.quantity.provenance is not Provenance.ESTIMATED_VAGUE
    assert ingr.quantity.unit == "cucchiai"


@pytest.mark.parametrize("unit_raw, value, unit", [("(g)", 200.0, "g"), ("(ml)", 200.0, "ml")])
def test_a_real_unit_in_brackets_does_not_become_a_note(t, unit_raw, value, unit):
    """"No unit is written in brackets" is an almost-right criterion, and the almost cost
    dearly: the model also writes `unita_raw="(g)"`, and demoting that to a note turned "200 g
    di farina" into a count of two hundred flours, without even a gap."""
    ingr = normalise_ingredient("farina 00", "200", unit_raw, tables=t)
    assert (ingr.quantity.value, ingr.quantity.unit) == (value, unit)
    assert ingr.quantity.provenance is not Provenance.COUNT


@pytest.mark.parametrize("name", ["frutta secca (noce)", "cioccolato (tazza)", "vino (bicchiere)"])
def test_a_one_word_parenthetical_qualifies_the_ingredient(t, name):
    """Many `vaghe.yaml` entries have single-word aliases — noce, tazza, bicchiere — which in
    brackets after a name indicate its variety or its container, not its dose."""
    ingr = normalise_ingredient(name, "", "", tables=t)
    assert ingr.quantity.provenance is Provenance.ABSENT, ingr.mela_line()
