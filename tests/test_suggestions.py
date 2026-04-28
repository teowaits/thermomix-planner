"""
Tests for suggestions.py pure functions.

All tests use fixture dicts — no DB, no network, no CookidooClient.
The caller contract for top_suggestions is: all_recipes contains status='ok'
recipes only. Tests honour this contract and verify the filtering assumption.
"""
import pytest

from backend.models import Ingredient, PantryItem, RecipeDetails
from backend.suggestions import (
    FUZZY_THRESHOLD,
    PREPOSITIONS,
    normalise_ingredient_name,
    score_recipe_by_pantry,
    top_suggestions,
)


# ---------------------------------------------------------------------------
# normalise_ingredient_name
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PREPOSITIONS constant
# ---------------------------------------------------------------------------

class TestPrepositionsConstant:
    def test_dell_before_del(self):
        # "dell'" must appear before "del " — otherwise "dell'aglio" strips to
        # "l'aglio" instead of "aglio".
        assert PREPOSITIONS.index("dell'") < PREPOSITIONS.index("del ")

    def test_de_la_before_de(self):
        # "de la " must appear before "de " — otherwise "de la harina" strips
        # to "la harina" instead of "harina".
        assert PREPOSITIONS.index("de la ") < PREPOSITIONS.index("de ")


# ---------------------------------------------------------------------------
# Preposition stripping
# ---------------------------------------------------------------------------

class TestPrepStripping:
    def test_spanish_de(self):
        assert normalise_ingredient_name("de pan") == "pan"

    def test_italian_di(self):
        assert normalise_ingredient_name("di farina") == "farina"

    def test_italian_dell_apostrophe(self):
        assert normalise_ingredient_name("dell'aglio") == "aglio"

    def test_italian_d_apostrophe(self):
        assert normalise_ingredient_name("d'aglio") == "aglio"

    def test_italian_del(self):
        assert normalise_ingredient_name("del pomodoro") == "pomodoro"

    def test_spanish_de_la(self):
        assert normalise_ingredient_name("de la harina") == "harina"

    def test_italian_delle(self):
        # plural strip does not apply to "cipolle" (ends in 'e', not 's')
        assert normalise_ingredient_name("delle cipolle") == "cipolle"

    def test_italian_dei(self):
        # "funghi" ends in 'i', not 's' — no plural strip
        assert normalise_ingredient_name("dei funghi") == "funghi"

    def test_no_strip_del_mid_word(self):
        # "delhi" starts with "del" but next char is 'h', not ' ' or "'"
        assert normalise_ingredient_name("delhi") == "delhi"

    def test_no_strip_de_mid_word(self):
        # "delivery" starts with "de" but next char is 'l', not ' '
        assert normalise_ingredient_name("delivery") == "delivery"

    def test_no_strip_when_result_empty(self):
        # "de" alone — stripping would leave ""; original returned unchanged
        assert normalise_ingredient_name("de") == "de"

    def test_uppercase_input_stripped(self):
        # Input is not pre-lowercased; normalise handles it
        assert normalise_ingredient_name("Di Farina") == "farina"

    def test_prep_strip_then_plural_strip(self):
        # "de pan" → "pan" (no trailing s, no further strip)
        # "di carrots" → strip "di " → "carrots" → plural strip → "carrot"
        assert normalise_ingredient_name("di carrots") == "carrot"


# ---------------------------------------------------------------------------
# normalise_ingredient_name (original cases, unchanged)
# ---------------------------------------------------------------------------

class TestNormaliseIngredientName:
    def test_lowercase(self):
        assert normalise_ingredient_name("Tomatoes") == "tomatoe"

    def test_strips_whitespace(self):
        assert normalise_ingredient_name("  garlic  ") == "garlic"

    def test_strips_trailing_s_when_result_ge_4_chars(self):
        # "carrots" → "carrot" (6 chars after strip)
        assert normalise_ingredient_name("carrots") == "carrot"
        # "eggs" → "egg" (3 chars after strip — meets the ≥3 stripped rule)
        assert normalise_ingredient_name("eggs") == "egg"

    def test_no_strip_when_result_lt_3_chars(self):
        # "gas" → strip would give "ga" (2 chars) — not stripped
        assert normalise_ingredient_name("gas") == "gas"

    def test_no_strip_s_when_original_lt_4_chars(self):
        # "peas" is 4 chars; stripped = "pea" (3 chars) → IS stripped
        assert normalise_ingredient_name("peas") == "pea"
        # "as" is 2 chars → not stripped
        assert normalise_ingredient_name("as") == "as"

    def test_no_trailing_s_unchanged(self):
        assert normalise_ingredient_name("garlic") == "garlic"

    def test_already_normalised(self):
        assert normalise_ingredient_name("onion") == "onion"

    def test_empty_string(self):
        assert normalise_ingredient_name("") == ""


# ---------------------------------------------------------------------------
# Fuzzy matching threshold
# ---------------------------------------------------------------------------

class TestFuzzyMatching:
    """Document that WRatio ≥ FUZZY_THRESHOLD admits near-miss pantry matches."""

    def _single_ingredient_recipe(self, name: str) -> RecipeDetails:
        return RecipeDetails(
            id="rx", name="Test", status="ok", servings=2,
            ingredients=[Ingredient(name=name, quantity=100, unit="g")],
        )

    async def test_italian_singular_plural_pomodoro(self, no_recent_ids):
        """'pomodoro' ingredient matches 'pomodori' pantry — both resolve to 'tomato'."""
        recipe = self._single_ingredient_recipe("pomodoro")
        pantry = [PantryItem(id="p1", name="pomodori")]
        assert await score_recipe_by_pantry(recipe, pantry, no_recent_ids) > 0.0

    async def test_italian_singular_plural_cipolla(self, no_recent_ids):
        """'cipolla' and 'cipolle' both resolve to 'onion' via dictionary."""
        recipe = self._single_ingredient_recipe("cipolla")
        pantry = [PantryItem(id="p1", name="cipolle")]
        assert await score_recipe_by_pantry(recipe, pantry, no_recent_ids) > 0.0

    async def test_qualifier_suffix_farina(self, no_recent_ids):
        """'farina 00' and 'farina' both resolve to 'all-purpose flour' via dictionary."""
        recipe = self._single_ingredient_recipe("farina 00")
        pantry = [PantryItem(id="p1", name="farina")]
        assert await score_recipe_by_pantry(recipe, pantry, no_recent_ids) > 0.0

    async def test_unrelated_ingredient_no_match(self, no_recent_ids):
        """'sale' vs 'olio' — unrelated, no match."""
        recipe = self._single_ingredient_recipe("sale")
        pantry = [PantryItem(id="p1", name="olio")]
        assert await score_recipe_by_pantry(recipe, pantry, no_recent_ids) == pytest.approx(0.0)

    def test_fuzzy_threshold_constant_value(self):
        assert FUZZY_THRESHOLD == 85


# ---------------------------------------------------------------------------
# score_recipe_by_pantry
# ---------------------------------------------------------------------------

class TestScoreRecipeByPantry:
    async def test_full_pantry_match_no_recency(self, recipe_pasta, no_recent_ids):
        # pantry has all 5 pasta ingredients → coverage = 1.0, no penalty
        pantry = [
            PantryItem(id="p1", name="pasta"),
            PantryItem(id="p2", name="tomatoes"),
            PantryItem(id="p3", name="onion"),
            PantryItem(id="p4", name="garlic"),
            PantryItem(id="p5", name="beef mince"),
        ]
        score = await score_recipe_by_pantry(recipe_pasta, pantry, no_recent_ids)
        assert score == pytest.approx(1.0)

    async def test_partial_match(self, recipe_pasta, no_recent_ids):
        # Only 2 of 5 ingredients in pantry → coverage = 0.4
        pantry = [
            PantryItem(id="p1", name="pasta"),
            PantryItem(id="p2", name="garlic"),
        ]
        score = await score_recipe_by_pantry(recipe_pasta, pantry, no_recent_ids)
        assert score == pytest.approx(0.4)

    async def test_zero_match_no_recency(self, recipe_pasta, no_recent_ids):
        pantry = [PantryItem(id="p1", name="chocolate")]
        score = await score_recipe_by_pantry(recipe_pasta, pantry, no_recent_ids)
        assert score == pytest.approx(0.0)

    async def test_recency_penalty_applied(self, recipe_pasta, pantry_items):
        # r001 in recent_recipe_ids → -0.3 penalty
        # pantry_items has tomatoes, onion, pasta, garlic → 4/5 = 0.8
        # 0.8 - 0.3 = 0.5
        recent = {"r001"}
        score = await score_recipe_by_pantry(recipe_pasta, pantry_items, recent)
        assert score == pytest.approx(0.5)

    async def test_recency_penalty_clamps_to_zero(self, no_recent_ids):
        """Score clamped to 0.0 — never negative."""
        recipe = RecipeDetails(
            id="rx",
            name="Test",
            status="ok",
            servings=2,
            ingredients=[Ingredient(name="truffle", quantity=10, unit="g")],
        )
        score = await score_recipe_by_pantry(recipe, [], {"rx"})
        assert score == pytest.approx(0.0)

    async def test_score_clamped_to_zero_when_recency_exceeds_coverage(self, no_recent_ids):
        """Low coverage + recency penalty → must clamp to 0, not go negative."""
        recipe = RecipeDetails(
            id="rx",
            name="Test",
            status="ok",
            servings=2,
            ingredients=[
                Ingredient(name="truffle", quantity=10, unit="g"),
                Ingredient(name="caviar", quantity=5, unit="g"),
                Ingredient(name="lobster", quantity=200, unit="g"),
                Ingredient(name="foie gras", quantity=100, unit="g"),
            ],
        )
        pantry = [PantryItem(id="p1", name="truffle")]  # 1/4 = 0.25 coverage
        score = await score_recipe_by_pantry(recipe, pantry, {"rx"})  # -0.3 penalty
        # 0.25 - 0.3 = -0.05 → clamped to 0
        assert score == pytest.approx(0.0)

    async def test_no_ingredients_returns_zero(self, no_recent_ids):
        recipe = RecipeDetails(id="rx", name="Empty", status="ok", ingredients=[])
        score = await score_recipe_by_pantry(recipe, [], no_recent_ids)
        assert score == 0.0

    async def test_plural_normalisation_matches(self, no_recent_ids):
        """Pantry 'tomato' matches ingredient 'tomatoes' — both resolve to 'tomato' via dict."""
        recipe = RecipeDetails(
            id="rx",
            name="Test",
            status="ok",
            servings=2,
            ingredients=[Ingredient(name="tomatoes", quantity=200, unit="g")],
        )
        pantry = [PantryItem(id="p1", name="tomato")]
        score = await score_recipe_by_pantry(recipe, pantry, no_recent_ids)
        assert score == pytest.approx(1.0)

    async def test_exact_normalised_match(self, no_recent_ids):
        """Direct normalised string equality match works."""
        recipe = RecipeDetails(
            id="rx",
            name="Test",
            status="ok",
            servings=2,
            ingredients=[Ingredient(name="Garlic", quantity=2, unit="cloves")],
        )
        pantry = [PantryItem(id="p1", name="garlic")]
        score = await score_recipe_by_pantry(recipe, pantry, no_recent_ids)
        assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# top_suggestions
# ---------------------------------------------------------------------------

class TestTopSuggestions:
    async def test_returns_scored_recipes(self, recipe_pasta, recipe_soup, pantry_items, no_recent_ids):
        results = await top_suggestions(
            pantry=pantry_items,
            all_recipes=[recipe_pasta, recipe_soup],
            recent_recipe_ids=no_recent_ids,
        )
        assert len(results) > 0
        assert all(r.score > 0.0 for r in results)

    async def test_sorted_by_score_descending(self, recipe_pasta, recipe_soup, pantry_items, no_recent_ids):
        results = await top_suggestions(pantry_items, [recipe_pasta, recipe_soup], no_recent_ids)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_zero_score_excluded(self, recipe_cake, pantry_items, no_recent_ids):
        """Recipe with no pantry match scores 0 and must not appear in results."""
        results = await top_suggestions(pantry_items, [recipe_cake], no_recent_ids)
        assert results == []

    async def test_unavailable_recipe_never_in_output(self, recipe_unavailable, pantry_items, no_recent_ids):
        """Caller should pass only ok recipes, but even if an unavailable one
        slips through it has no ingredients → scores 0 → excluded."""
        results = await top_suggestions(pantry_items, [recipe_unavailable], no_recent_ids)
        assert results == []
        ids = [r.recipe.id for r in results]
        assert "r004" not in ids

    async def test_max_time_filter_excludes_slow_recipes(
        self, recipe_pasta, recipe_soup, pantry_items, no_recent_ids
    ):
        # pasta = 40 min, soup = 25 min; max_time=30 → only soup passes
        results = await top_suggestions(pantry_items, [recipe_pasta, recipe_soup], no_recent_ids, max_time=30)
        ids = [r.recipe.id for r in results]
        assert "r002" in ids
        assert "r001" not in ids

    async def test_max_time_none_means_no_filter(
        self, recipe_pasta, recipe_soup, pantry_items, no_recent_ids
    ):
        results = await top_suggestions(pantry_items, [recipe_pasta, recipe_soup], no_recent_ids, max_time=None)
        ids = [r.recipe.id for r in results]
        assert "r001" in ids
        assert "r002" in ids

    async def test_none_cooking_time_passes_filter(self, recipe_no_time, pantry_items, no_recent_ids):
        """Recipe with cooking_time=None is not excluded by max_time filter."""
        results = await top_suggestions(pantry_items, [recipe_no_time], no_recent_ids, max_time=10)
        ids = [r.recipe.id for r in results]
        assert "r005" in ids

    async def test_top_n_respected(self, recipe_pasta, recipe_soup, recipe_no_time, pantry_items, no_recent_ids):
        results = await top_suggestions(
            pantry_items,
            [recipe_pasta, recipe_soup, recipe_no_time],
            no_recent_ids,
            n=1,
        )
        assert len(results) == 1

    async def test_recency_penalty_reduces_score(self, recipe_pasta, pantry_items):
        recent = {"r001"}
        no_recent: set[str] = set()

        score_with_penalty = (await top_suggestions(pantry_items, [recipe_pasta], recent))[0].score
        score_without_penalty = (await top_suggestions(pantry_items, [recipe_pasta], no_recent))[0].score
        assert score_without_penalty > score_with_penalty

    async def test_empty_recipes_list(self, pantry_items, no_recent_ids):
        results = await top_suggestions(pantry_items, [], no_recent_ids)
        assert results == []

    async def test_empty_pantry_no_results(self, recipe_pasta, no_recent_ids):
        results = await top_suggestions([], [recipe_pasta], no_recent_ids)
        assert results == []
