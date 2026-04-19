"""
Shared test fixtures for shopping and suggestions tests.

Rules:
- No CookidooClient, no aiohttp.ClientSession, no DB handles.
- All fixtures return plain Python data structures / Pydantic models.
- fixture_recipe_cache contains a mix of 'ok' and 'unavailable' recipes.
"""
import pytest

from backend.models import Ingredient, PantryItem, RecipeDetails


# ---------------------------------------------------------------------------
# Recipe fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def recipe_pasta() -> RecipeDetails:
    """A normal ok recipe — uses pantry staples."""
    return RecipeDetails(
        id="r001",
        name="Pasta Bolognese",
        status="ok",
        cooking_time=40,
        servings=4,
        ingredients=[
            Ingredient(name="pasta", quantity=400, unit="g"),
            Ingredient(name="tomatoes", quantity=300, unit="g"),
            Ingredient(name="onion", quantity=1, unit=None),
            Ingredient(name="garlic", quantity=2, unit="cloves"),
            Ingredient(name="beef mince", quantity=500, unit="g"),
        ],
    )


@pytest.fixture()
def recipe_soup() -> RecipeDetails:
    """A quick ok recipe with some pantry overlap."""
    return RecipeDetails(
        id="r002",
        name="Tomato Soup",
        status="ok",
        cooking_time=25,
        servings=2,
        ingredients=[
            Ingredient(name="tomatoes", quantity=500, unit="g"),
            Ingredient(name="onion", quantity=1, unit=None),
            Ingredient(name="vegetable stock", quantity=500, unit="ml"),
        ],
    )


@pytest.fixture()
def recipe_cake() -> RecipeDetails:
    """An ok recipe with none of the pantry items."""
    return RecipeDetails(
        id="r003",
        name="Chocolate Cake",
        status="ok",
        cooking_time=60,
        servings=8,
        ingredients=[
            Ingredient(name="flour", quantity=200, unit="g"),
            Ingredient(name="sugar", quantity=150, unit="g"),
            Ingredient(name="cocoa powder", quantity=50, unit="g"),
            Ingredient(name="eggs", quantity=3, unit=None),
            Ingredient(name="butter", quantity=100, unit="g"),
        ],
    )


@pytest.fixture()
def recipe_unavailable() -> RecipeDetails:
    """A recipe whose Cookidoo fetch failed — no ingredients."""
    return RecipeDetails(
        id="r004",
        name="Mystery Dish",
        status="unavailable",
        cooking_time=None,
        servings=None,
        ingredients=[],
    )


@pytest.fixture()
def recipe_no_time() -> RecipeDetails:
    """An ok recipe with unknown cooking time — passes all max_time filters."""
    return RecipeDetails(
        id="r005",
        name="Simple Salad",
        status="ok",
        cooking_time=None,
        servings=2,
        ingredients=[
            Ingredient(name="tomatoes", quantity=200, unit="g"),
            Ingredient(name="onion", quantity=1, unit=None),
        ],
    )


@pytest.fixture()
def fixture_recipe_cache(
    recipe_pasta, recipe_soup, recipe_cake, recipe_unavailable, recipe_no_time
) -> dict[str, RecipeDetails]:
    """
    Injected recipe cache for shopping tests.
    Mix of ok and unavailable recipes, as route handlers would assemble.
    """
    return {
        r.id: r
        for r in [recipe_pasta, recipe_soup, recipe_cake, recipe_unavailable, recipe_no_time]
    }


# ---------------------------------------------------------------------------
# Pantry fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def pantry_items() -> list[PantryItem]:
    """User has tomatoes, onion, pasta, and garlic in their pantry."""
    return [
        PantryItem(id="p1", name="tomatoes"),
        PantryItem(id="p2", name="onion"),
        PantryItem(id="p3", name="pasta"),
        PantryItem(id="p4", name="garlic"),
    ]


# ---------------------------------------------------------------------------
# Recency fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def recent_recipe_ids() -> set[str]:
    """Simulates route handler querying meal_plan for W-1 and W-2."""
    return {"r001"}  # Pasta Bolognese was used recently


@pytest.fixture()
def no_recent_ids() -> set[str]:
    return set()
