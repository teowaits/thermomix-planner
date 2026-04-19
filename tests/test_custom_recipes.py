"""
Tests for local custom recipe CRUD in recipe_cache.py.

Uses an in-memory aiosqlite DB — no network, no Cookidoo client.
"""
import pytest
import aiosqlite

from backend.db import init_schema
from backend.models import RecipeDetails
from backend.recipe_cache import (
    create_custom_recipe,
    delete_custom_recipe,
    get_recipe_details,
    is_local_custom,
    update_custom_recipe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
async def db():
    async with aiosqlite.connect(":memory:") as conn:
        await init_schema(conn)
        yield conn


# ---------------------------------------------------------------------------
# is_local_custom
# ---------------------------------------------------------------------------

def test_is_local_custom_true():
    assert is_local_custom("custom-abc123") is True


def test_is_local_custom_false_cookidoo():
    assert is_local_custom("r12345") is False


def test_is_local_custom_false_empty():
    assert is_local_custom("") is False


# ---------------------------------------------------------------------------
# create_custom_recipe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_returns_recipe_details(db):
    recipe = await create_custom_recipe(
        db,
        name="My Risotto",
        servings=4,
        cooking_time=35,
        ingredients=[{"name": "arborio rice", "quantity": 300, "unit": "g"}],
        source_url="https://example.com/risotto",
    )
    assert isinstance(recipe, RecipeDetails)
    assert recipe.name == "My Risotto"
    assert recipe.recipe_type == "local_custom"
    assert recipe.status == "ok"
    assert is_local_custom(recipe.id)
    assert recipe.source_url == "https://example.com/risotto"
    assert len(recipe.ingredients) == 1
    assert recipe.ingredients[0].name == "arborio rice"


@pytest.mark.asyncio
async def test_create_persists_to_db(db):
    recipe = await create_custom_recipe(
        db, name="My Risotto", servings=4,
        cooking_time=35, ingredients=[], source_url=None,
    )
    fetched = await get_recipe_details(db, recipe.id)
    assert fetched is not None
    assert fetched.name == "My Risotto"
    assert fetched.recipe_type == "local_custom"


@pytest.mark.asyncio
async def test_create_generates_unique_ids(db):
    r1 = await create_custom_recipe(
        db, name="A", servings=None, cooking_time=None, ingredients=[], source_url=None,
    )
    r2 = await create_custom_recipe(
        db, name="B", servings=None, cooking_time=None, ingredients=[], source_url=None,
    )
    assert r1.id != r2.id


# ---------------------------------------------------------------------------
# update_custom_recipe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_changes_fields(db):
    recipe = await create_custom_recipe(
        db, name="Old Name", servings=2, cooking_time=20, ingredients=[], source_url=None,
    )
    updated = await update_custom_recipe(
        db, recipe.id,
        name="New Name", servings=4, cooking_time=30,
        ingredients=[{"name": "salt", "quantity": None, "unit": None}],
        source_url="https://example.com",
    )
    assert updated is not None
    assert updated.name == "New Name"
    assert updated.servings == 4
    assert updated.cooking_time == 30
    assert len(updated.ingredients) == 1
    assert updated.source_url == "https://example.com"


@pytest.mark.asyncio
async def test_update_nonexistent_returns_none(db):
    result = await update_custom_recipe(
        db, "custom-doesnotexist",
        name="X", servings=None, cooking_time=None, ingredients=[], source_url=None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_update_non_custom_id_returns_none(db):
    result = await update_custom_recipe(
        db, "r99999",
        name="X", servings=None, cooking_time=None, ingredients=[], source_url=None,
    )
    assert result is None


# ---------------------------------------------------------------------------
# delete_custom_recipe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_removes_recipe(db):
    recipe = await create_custom_recipe(
        db, name="Temp", servings=None, cooking_time=None, ingredients=[], source_url=None,
    )
    deleted = await delete_custom_recipe(db, recipe.id)
    assert deleted is True
    assert await get_recipe_details(db, recipe.id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(db):
    result = await delete_custom_recipe(db, "custom-doesnotexist")
    assert result is False


@pytest.mark.asyncio
async def test_delete_non_custom_id_returns_false(db):
    result = await delete_custom_recipe(db, "r99999")
    assert result is False
