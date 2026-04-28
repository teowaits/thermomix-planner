"""
Tests for backend/synonyms.py — multilingual ingredient synonym resolution.

All tests that need a DB use an in-memory aiosqlite connection with the full
schema applied. Tests that only exercise the dictionary need no DB at all.

asyncio_mode=auto (pytest.ini) — all async def tests run automatically.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from backend.db import init_schema
from backend.synonyms import _DICT, resolve_ingredient
from backend.models import Ingredient, PantryItem, RecipeDetails
from backend.suggestions import score_recipe_by_pantry
from backend.shopping import build_shopping_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
async def mem_db():
    """In-memory SQLite DB with full schema applied."""
    async with aiosqlite.connect(":memory:") as db:
        await init_schema(db)
        yield db


# ---------------------------------------------------------------------------
# Test 1 — Dictionary lookup (no DB, no API)
# ---------------------------------------------------------------------------

class TestDictionaryLookup:
    async def test_italian_cipolla_resolves_to_onion(self, mem_db):
        assert await resolve_ingredient("cipolla", mem_db) == "onion"

    async def test_spanish_cebolla_resolves_to_onion(self, mem_db):
        assert await resolve_ingredient("cebolla", mem_db) == "onion"

    async def test_english_onion_resolves_to_onion(self, mem_db):
        assert await resolve_ingredient("onion", mem_db) == "onion"

    async def test_italian_plural_cipolle_resolves_to_onion(self, mem_db):
        assert await resolve_ingredient("cipolle", mem_db) == "onion"

    async def test_no_db_still_resolves_from_dict(self):
        """Dictionary lookup works even when db=None."""
        assert await resolve_ingredient("cipolla") == "onion"


# ---------------------------------------------------------------------------
# Test 2 — Preposition stripping then dictionary lookup
# ---------------------------------------------------------------------------

class TestPrepositionThenDict:
    async def test_di_farina_resolves_via_prep_strip(self, mem_db):
        """'di farina' → strip 'di ' → 'farina' → dict → 'all-purpose flour'."""
        assert await resolve_ingredient("di farina", mem_db) == "all-purpose flour"

    async def test_farina_00_direct_dict_lookup(self, mem_db):
        """'farina 00' is in the dictionary directly."""
        assert await resolve_ingredient("farina 00", mem_db) == "all-purpose flour"

    async def test_dell_aglio_strips_and_resolves(self, mem_db):
        """\"dell'aglio\" → strip → 'aglio' → dict → 'garlic'."""
        assert await resolve_ingredient("dell'aglio", mem_db) == "garlic"


# ---------------------------------------------------------------------------
# Test 3 — SQLite cache hit (no API call)
# ---------------------------------------------------------------------------

class TestSQLiteCacheHit:
    async def test_sqlite_cache_hit_returns_cached_canonical(self, mem_db):
        """Pre-inserted row is returned without hitting the Claude API."""
        await mem_db.execute(
            "INSERT INTO ingredient_synonyms (normalised_name, canonical_name, source) "
            "VALUES ('cicoria', 'chicory', 'claude_api')"
        )
        await mem_db.commit()

        with patch("backend.synonyms._resolve_via_claude", new_callable=AsyncMock) as mock_api:
            result = await resolve_ingredient("cicoria", mem_db)

        assert result == "chicory"
        mock_api.assert_not_called()

    async def test_sqlite_cache_stores_on_first_api_call(self, mem_db):
        """After an API resolution, the result is stored in SQLite."""
        with patch("backend.synonyms._resolve_via_claude", new_callable=AsyncMock, return_value="chicory"):
            await resolve_ingredient("cicoria", mem_db)

        mem_db.row_factory = aiosqlite.Row
        async with mem_db.execute(
            "SELECT canonical_name, source FROM ingredient_synonyms WHERE normalised_name = 'cicoria'"
        ) as cur:
            row = await cur.fetchone()

        assert row is not None
        assert row["canonical_name"] == "chicory"
        assert row["source"] == "claude_api"


# ---------------------------------------------------------------------------
# Test 4 — Unknown ingredient with API disabled
# ---------------------------------------------------------------------------

class TestApiDisabled:
    async def test_unknown_ingredient_no_api_key_passthrough(self, mem_db, monkeypatch):
        """With no API key, unknown ingredient passes through as normalised name."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = await resolve_ingredient("cicoria", mem_db)
        # 'cicoria' is not in the dictionary; no API → returns normalised form
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_no_exception_raised_without_api_key(self, mem_db, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Must not raise regardless of input
        result = await resolve_ingredient("xyzunknowningredient123", mem_db)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Test 5 — _DICT coverage
# ---------------------------------------------------------------------------

class TestDictCoverage:
    def test_dict_has_minimum_entries(self):
        assert len(_DICT) > 400

    def test_cipolla_in_dict(self):
        assert _DICT.get("cipolla") == "onion"

    def test_huevo_in_dict(self):
        assert _DICT.get("huevo") == "egg"

    def test_farina_00_in_dict(self):
        assert _DICT.get("farina 00") == "all-purpose flour"

    def test_english_tomato_in_dict(self):
        assert _DICT.get("tomato") == "tomato"

    def test_english_tomatoes_in_dict(self):
        # Raw form "tomatoes" must be present even though normalise strips to "tomatoe"
        assert _DICT.get("tomatoes") == "tomato"

    def test_canonical_maps_to_itself(self):
        # Canonical English names map to themselves
        assert _DICT.get("onion") == "onion"
        assert _DICT.get("garlic") == "garlic"


# ---------------------------------------------------------------------------
# Test 6 — Cross-language match in score_recipe_by_pantry
# ---------------------------------------------------------------------------

class TestCrossLanguageSuggestions:
    async def test_cipolla_ingredient_matches_onion_pantry(self, mem_db):
        """Italian 'cipolla' in recipe, English 'onion' in pantry → score > 0."""
        recipe = RecipeDetails(
            id="rx", name="Test", status="ok", servings=2,
            ingredients=[Ingredient(name="cipolla", quantity=1, unit=None)],
        )
        pantry = [PantryItem(id="p1", name="onion")]
        score = await score_recipe_by_pantry(recipe, pantry, set(), db=mem_db)
        assert score > 0.0

    async def test_onion_ingredient_matches_cipolla_pantry(self, mem_db):
        """English 'onion' in recipe, Italian 'cipolla' in pantry → score > 0."""
        recipe = RecipeDetails(
            id="rx", name="Test", status="ok", servings=2,
            ingredients=[Ingredient(name="onion", quantity=1, unit=None)],
        )
        pantry = [PantryItem(id="p1", name="cipolla")]
        score = await score_recipe_by_pantry(recipe, pantry, set(), db=mem_db)
        assert score > 0.0

    async def test_unrelated_ingredients_still_no_match(self, mem_db):
        """Cross-language resolution must not create false positives."""
        recipe = RecipeDetails(
            id="rx", name="Test", status="ok", servings=2,
            ingredients=[Ingredient(name="sale", quantity=5, unit="g")],
        )
        pantry = [PantryItem(id="p1", name="onion")]
        score = await score_recipe_by_pantry(recipe, pantry, set(), db=mem_db)
        assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 7 — Cross-language match in shopping list owned flag
# ---------------------------------------------------------------------------

class TestCrossLanguageShopping:
    async def test_cipolla_ingredient_owned_when_pantry_has_onion(self, mem_db):
        """'cipolla' ingredient is marked owned when pantry contains 'onion'."""
        recipe = RecipeDetails(
            id="sl1", name="Test", status="ok", servings=2,
            ingredients=[Ingredient(name="cipolla", quantity=1, unit=None)],
        )
        pantry = [PantryItem(id="p1", name="onion")]
        result = await build_shopping_list(
            {("2026-W16", 0, 1): "sl1"}, pantry, {"sl1": recipe}, db=mem_db
        )
        assert len(result.items) == 1
        assert result.items[0].owned is True

    async def test_onion_ingredient_owned_when_pantry_has_cipolla(self, mem_db):
        recipe = RecipeDetails(
            id="sl2", name="Test", status="ok", servings=2,
            ingredients=[Ingredient(name="onion", quantity=1, unit=None)],
        )
        pantry = [PantryItem(id="p1", name="cipolla")]
        result = await build_shopping_list(
            {("2026-W16", 0, 1): "sl2"}, pantry, {"sl2": recipe}, db=mem_db
        )
        assert result.items[0].owned is True

    async def test_unrelated_cross_language_not_owned(self, mem_db):
        recipe = RecipeDetails(
            id="sl3", name="Test", status="ok", servings=2,
            ingredients=[Ingredient(name="cipolla", quantity=1, unit=None)],
        )
        pantry = [PantryItem(id="p1", name="sale")]
        result = await build_shopping_list(
            {("2026-W16", 0, 1): "sl3"}, pantry, {"sl3": recipe}, db=mem_db
        )
        assert result.items[0].owned is False
