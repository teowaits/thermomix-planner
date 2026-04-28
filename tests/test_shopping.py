"""
Tests for shopping.py pure functions.

All tests use fixture dicts — no DB, no network, no CookidooClient.
"""
import pytest

from backend.models import Ingredient, PantryItem, RecipeDetails, ShoppingList
from backend.shopping import (
    DEFAULT_SERVINGS,
    aggregate_ingredients,
    build_shopping_list,
    scale_ingredients,
)


# ---------------------------------------------------------------------------
# DEFAULT_SERVINGS
# ---------------------------------------------------------------------------

def test_default_servings_keys():
    assert DEFAULT_SERVINGS[0] == 2  # lunch
    assert DEFAULT_SERVINGS[1] == 4  # dinner


# ---------------------------------------------------------------------------
# scale_ingredients
# ---------------------------------------------------------------------------

def test_scale_doubles_quantities():
    ings = [Ingredient(name="flour", quantity=100, unit="g")]
    scaled = scale_ingredients(ings, 2)
    assert scaled[0].quantity == 200


def test_scale_preserves_none_quantity():
    ings = [Ingredient(name="salt", quantity=None, unit=None)]
    scaled = scale_ingredients(ings, 4)
    assert scaled[0].quantity is None


def test_scale_preserves_unit_and_name():
    ings = [Ingredient(name="Olive Oil", quantity=50, unit="ml")]
    scaled = scale_ingredients(ings, 3)
    assert scaled[0].name == "Olive Oil"
    assert scaled[0].unit == "ml"
    assert scaled[0].quantity == 150


def test_scale_zero_multiplier():
    ings = [Ingredient(name="sugar", quantity=100, unit="g")]
    scaled = scale_ingredients(ings, 0)
    assert scaled[0].quantity == 0


def test_scale_returns_new_list():
    ings = [Ingredient(name="salt", quantity=5, unit="g")]
    scaled = scale_ingredients(ings, 2)
    assert scaled is not ings
    assert scaled[0] is not ings[0]


# ---------------------------------------------------------------------------
# aggregate_ingredients
# ---------------------------------------------------------------------------

def test_aggregate_same_unit_summed():
    lists = [
        ([Ingredient(name="flour", quantity=100, unit="g")], "Recipe A"),
        ([Ingredient(name="flour", quantity=200, unit="g")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 1
    assert result[0].quantity == 300
    assert result[0].unit == "g"


def test_aggregate_different_units_merge_after_normalisation():
    # Phase 2: 200g + 0.2kg → both convert to g → aggregate to 400g
    lists = [
        ([Ingredient(name="flour", quantity=200, unit="g")], "Recipe A"),
        ([Ingredient(name="flour", quantity=0.2, unit="kg")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 1
    assert result[0].quantity == pytest.approx(400.0)
    assert result[0].unit == "g"
    assert result[0].check_units is False


def test_aggregate_none_quantity_not_merged():
    lists = [
        ([Ingredient(name="salt", quantity=None, unit=None)], "Recipe A"),
        ([Ingredient(name="salt", quantity=None, unit=None)], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    # Both kept separately because quantity is None
    assert len(result) == 2


def test_aggregate_recipe_sources_collected():
    lists = [
        ([Ingredient(name="onion", quantity=1, unit=None)], "Soup"),
        ([Ingredient(name="onion", quantity=2, unit=None)], "Stew"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 1
    assert "Soup" in result[0].recipe_sources
    assert "Stew" in result[0].recipe_sources


def test_aggregate_case_insensitive_merge():
    lists = [
        ([Ingredient(name="Tomatoes", quantity=100, unit="g")], "Recipe A"),
        ([Ingredient(name="tomatoes", quantity=150, unit="g")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 1
    assert result[0].quantity == 250


def test_aggregate_empty_input():
    assert aggregate_ingredients([]) == []


def test_aggregate_preserves_order():
    lists = [
        ([Ingredient(name="zucchini", quantity=1, unit=None)], "A"),
        ([Ingredient(name="apple", quantity=1, unit=None)], "B"),
    ]
    result = aggregate_ingredients(lists)
    assert result[0].name == "zucchini"
    assert result[1].name == "apple"


# ---------------------------------------------------------------------------
# build_shopping_list — core behaviour
# ---------------------------------------------------------------------------

async def test_build_shopping_list_basic(fixture_recipe_cache, pantry_items):
    week_plan = {("2026-W16", 0, 1): "r001"}  # dinner → 4 servings
    result = await build_shopping_list(week_plan, pantry_items, fixture_recipe_cache)
    assert isinstance(result, ShoppingList)
    assert result.unavailable_recipes == []
    names = [i.name for i in result.items]
    assert "pasta" in [n.lower() for n in names]


async def test_build_shopping_list_scales_by_meal_slot(fixture_recipe_cache, pantry_items):
    """Dinner slot (meal=1) → 4 servings; recipe default is 4 → ratio 1x."""
    week_plan = {("2026-W16", 0, 1): "r001"}
    result = await build_shopping_list(week_plan, pantry_items, fixture_recipe_cache)
    pasta_item = next(i for i in result.items if i.name.lower() == "pasta")
    # recipe has 400g for 4 servings; dinner = 4 servings → 400g unchanged
    assert pasta_item.quantity == pytest.approx(400.0)


async def test_build_shopping_list_lunch_scales_to_2(fixture_recipe_cache, pantry_items):
    """Lunch slot (meal=0) → 2 servings; recipe default 4 → halved."""
    week_plan = {("2026-W16", 0, 0): "r001"}
    result = await build_shopping_list(week_plan, pantry_items, fixture_recipe_cache)
    pasta_item = next(i for i in result.items if i.name.lower() == "pasta")
    # 400g / 4 * 2 = 200g
    assert pasta_item.quantity == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# build_shopping_list — unavailable recipe handling
# ---------------------------------------------------------------------------

async def test_unavailable_recipe_excluded_from_ingredients(fixture_recipe_cache, pantry_items):
    """Unavailable recipe must not contribute any ingredient lines."""
    week_plan = {("2026-W16", 0, 1): "r004"}  # Mystery Dish — unavailable
    result = await build_shopping_list(week_plan, pantry_items, fixture_recipe_cache)
    assert result.items == []


async def test_unavailable_recipe_name_in_unavailable_list(fixture_recipe_cache, pantry_items):
    """Unavailable recipe name must appear in ShoppingList.unavailable_recipes."""
    week_plan = {("2026-W16", 0, 1): "r004"}
    result = await build_shopping_list(week_plan, pantry_items, fixture_recipe_cache)
    assert "Mystery Dish" in result.unavailable_recipes


async def test_mixed_plan_separates_unavailable(fixture_recipe_cache, pantry_items):
    """Mixed plan: ok recipe contributes items; unavailable recipe goes to warning list."""
    week_plan = {
        ("2026-W16", 0, 1): "r001",  # ok
        ("2026-W16", 1, 1): "r004",  # unavailable
    }
    result = await build_shopping_list(week_plan, pantry_items, fixture_recipe_cache)
    assert len(result.items) > 0
    assert "Mystery Dish" in result.unavailable_recipes
    # Ensure unavailable recipe did NOT produce ingredient lines
    sources = {src for item in result.items for src in item.recipe_sources}
    assert "Mystery Dish" not in sources


async def test_missing_recipe_id_treated_as_unavailable(pantry_items):
    """Recipe ID in plan but absent from cache → treated as unavailable."""
    cache: dict[str, RecipeDetails] = {}
    week_plan = {("2026-W16", 0, 1): "r999"}
    result = await build_shopping_list(week_plan, pantry_items, cache)
    assert result.items == []
    assert "r999" in result.unavailable_recipes


# ---------------------------------------------------------------------------
# build_shopping_list — pantry matching
# ---------------------------------------------------------------------------

async def test_pantry_match_marks_owned(fixture_recipe_cache, pantry_items):
    """Ingredients present in pantry are marked owned=True."""
    week_plan = {("2026-W16", 0, 1): "r001"}
    result = await build_shopping_list(week_plan, pantry_items, fixture_recipe_cache)
    owned_names = {i.name.lower() for i in result.items if i.owned}
    # pasta, tomato(es), onion, garlic are all in pantry
    assert "pasta" in owned_names
    assert "onion" in owned_names
    assert "garlic" in owned_names


async def test_non_pantry_item_not_owned(fixture_recipe_cache, pantry_items):
    week_plan = {("2026-W16", 0, 1): "r001"}
    result = await build_shopping_list(week_plan, pantry_items, fixture_recipe_cache)
    not_owned = {i.name.lower() for i in result.items if not i.owned}
    assert "beef mince" in not_owned


async def test_empty_pantry_nothing_owned(fixture_recipe_cache):
    week_plan = {("2026-W16", 0, 1): "r001"}
    result = await build_shopping_list(week_plan, [], fixture_recipe_cache)
    assert all(not i.owned for i in result.items)


async def test_empty_plan_returns_empty_list(fixture_recipe_cache, pantry_items):
    result = await build_shopping_list({}, pantry_items, fixture_recipe_cache)
    assert result.items == []
    assert result.unavailable_recipes == []


# ---------------------------------------------------------------------------
# aggregate_ingredients — unit normalisation
# ---------------------------------------------------------------------------

def test_unit_normalisation_same_unit():
    """Case 1: same unit — 100g + 200g → 300g, check_units=False."""
    lists = [
        ([Ingredient(name="flour", quantity=100, unit="g")], "Recipe A"),
        ([Ingredient(name="flour", quantity=200, unit="g")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 1
    assert result[0].quantity == pytest.approx(300.0)
    assert result[0].unit == "g"
    assert result[0].check_units is False


def test_unit_normalisation_cross_unit_mass():
    """Case 2: cross-unit mass — 200g + 0.2kg → 400g, check_units=False."""
    lists = [
        ([Ingredient(name="flour", quantity=200, unit="g")], "Recipe A"),
        ([Ingredient(name="flour", quantity=0.2, unit="kg")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 1
    assert result[0].quantity == pytest.approx(400.0)
    assert result[0].unit == "g"
    assert result[0].check_units is False


def test_unit_normalisation_cross_unit_volume():
    """Case 3: cross-unit volume — 500ml + 0.5l → 1000ml, check_units=False."""
    lists = [
        ([Ingredient(name="water", quantity=500, unit="ml")], "Recipe A"),
        ([Ingredient(name="water", quantity=0.5, unit="l")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 1
    assert result[0].quantity == pytest.approx(1000.0)
    assert result[0].unit == "ml"
    assert result[0].check_units is False


def test_unit_normalisation_incompatible_units():
    """Case 4: incompatible units (mass vs volume) → two lines, both check_units=True."""
    lists = [
        ([Ingredient(name="butter", quantity=100, unit="g")], "Recipe A"),
        ([Ingredient(name="butter", quantity=50, unit="ml")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 2
    assert all(item.check_units is True for item in result)


def test_unit_normalisation_unknown_unit_same():
    """Case 5: unknown unit, same on both sides — aggregates, check_units=False."""
    lists = [
        ([Ingredient(name="flour", quantity=1, unit="cup")], "Recipe A"),
        ([Ingredient(name="flour", quantity=2, unit="cup")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 1
    assert result[0].quantity == pytest.approx(3.0)
    assert result[0].unit == "cup"
    assert result[0].check_units is False


def test_unit_normalisation_known_vs_unknown():
    """Case 6: known unit (g) + unknown unit (cup) → two lines, both check_units=True."""
    lists = [
        ([Ingredient(name="flour", quantity=100, unit="g")], "Recipe A"),
        ([Ingredient(name="flour", quantity=1, unit="cup")], "Recipe B"),
    ]
    result = aggregate_ingredients(lists)
    assert len(result) == 2
    assert all(item.check_units is True for item in result)


# ---------------------------------------------------------------------------
# build_shopping_list — fuzzy pantry matching
# ---------------------------------------------------------------------------

async def test_fuzzy_pantry_match_marks_owned():
    """'pomodoro' and 'pomodori' both resolve to 'tomato' via dictionary → owned."""
    recipe = RecipeDetails(
        id="fx1", name="Fuzzy Recipe", status="ok", servings=2,
        ingredients=[Ingredient(name="pomodoro", quantity=200, unit="g")],
    )
    pantry = [PantryItem(id="p1", name="pomodori")]
    result = await build_shopping_list({("2026-W16", 0, 1): "fx1"}, pantry, {"fx1": recipe})
    assert len(result.items) == 1
    assert result.items[0].owned is True


async def test_fuzzy_pantry_no_match_unrelated():
    """'sale fino' ingredient is NOT owned when pantry only has 'olio'."""
    recipe = RecipeDetails(
        id="fx2", name="Fuzzy Recipe 2", status="ok", servings=2,
        ingredients=[Ingredient(name="sale fino", quantity=5, unit="g")],
    )
    pantry = [PantryItem(id="p1", name="olio")]
    result = await build_shopping_list({("2026-W16", 0, 1): "fx2"}, pantry, {"fx2": recipe})
    assert len(result.items) == 1
    assert result.items[0].owned is False
