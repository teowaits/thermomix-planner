"""Recipe cache — DB read layer + cache-refresh background task.

Architecture notes
------------------
- All network I/O is delegated to cookidoo_client; this module is network-free
  except inside refresh_cache(), which is the designated entry point for that work.
- _cache_status is process-local (module dict); no DB persistence needed for
  transient refresh state.
- Single-worker only: _cache_status is not safe across multiple processes.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Callable

import aiosqlite

import backend.cookidoo_client as cc
from backend.models import Ingredient, RecipeDetails, RecipeSummary

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process cache status (no DB)
# ---------------------------------------------------------------------------

_cache_status: dict = {
    "state": "idle",          # "idle" | "running" | "done" | "error"
    "progress": {"done": 0, "total": 0},
    "last_refreshed": None,   # ISO timestamp, UTC
    "error": None,
}


def get_cache_status() -> dict:
    """Return a shallow copy of the current cache status."""
    return {
        "state": _cache_status["state"],
        "progress": dict(_cache_status["progress"]),
        "last_refreshed": _cache_status["last_refreshed"],
        "error": _cache_status["error"],
    }


# ---------------------------------------------------------------------------
# Ingredient description parser
# ---------------------------------------------------------------------------

# Matches an optional leading quantity (integer, decimal, or simple fraction)
# followed by an optional unit string.
# Examples: "200 g", "1,5 kg", "1/2 tsp", "2", "nach Geschmack"
_QTY_RE = re.compile(r'^(\d+/\d+|\d+(?:[.,]\d+)?)\s*(.*)?$')


def _parse_description(desc: str | None) -> tuple[float | None, str | None]:
    """Parse a Cookidoo ingredient description into (quantity, unit).

    Returns (None, None) when the description is absent or purely textual
    (e.g. "nach Geschmack", "to taste").
    """
    if not desc:
        return None, None
    desc = desc.strip()
    m = _QTY_RE.match(desc)
    if not m:
        return None, None
    qty_str = m.group(1)
    unit = (m.group(2) or "").strip() or None
    if "/" in qty_str:
        try:
            num, den = qty_str.split("/", 1)
            qty = float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None, None
    else:
        try:
            qty = float(qty_str.replace(",", "."))
        except ValueError:
            return None, None
    return qty, unit


# ---------------------------------------------------------------------------
# DB helpers (private)
# ---------------------------------------------------------------------------

def is_local_custom(recipe_id: str) -> bool:
    """True for recipes created locally (id prefix 'custom-')."""
    return recipe_id.startswith("custom-")


async def _upsert_recipe(
    db: aiosqlite.Connection,
    *,
    recipe_id: str,
    name: str,
    status: str,
    recipe_type: str,
    collection_id: str | None,
    cooking_time: int | None,
    servings: int | None,
    ingredients: list[dict],
    raw_json: str | None,
    source_url: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO recipes
            (id, name, status, recipe_type, collection_id,
             cooking_time, servings, ingredients_json, raw_json, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name             = excluded.name,
            status           = excluded.status,
            recipe_type      = excluded.recipe_type,
            collection_id    = excluded.collection_id,
            cooking_time     = excluded.cooking_time,
            servings         = excluded.servings,
            ingredients_json = excluded.ingredients_json,
            raw_json         = excluded.raw_json,
            source_url       = excluded.source_url
        WHERE recipes.id NOT LIKE 'custom-%'
        """,
        (
            recipe_id,
            name,
            status,
            recipe_type,
            collection_id,
            cooking_time,
            servings,
            json.dumps(ingredients) if ingredients else None,
            raw_json,
            source_url,
        ),
    )


async def _upsert_unavailable(
    db: aiosqlite.Connection,
    recipe_id: str,
    name: str,
    recipe_type: str,
    collection_id: str | None,
) -> None:
    """Store a minimal stub for a recipe whose detail fetch failed."""
    await _upsert_recipe(
        db,
        recipe_id=recipe_id,
        name=name,
        status="unavailable",
        recipe_type=recipe_type,
        collection_id=collection_id,
        cooking_time=None,
        servings=None,
        ingredients=[],
        raw_json=None,
    )


# ---------------------------------------------------------------------------
# Cache refresh (only function with network I/O)
# ---------------------------------------------------------------------------

async def retry_unavailable(
    db: aiosqlite.Connection,
    client,
    on_progress: Callable[[dict], None] | None = None,
) -> None:
    """Re-fetch recipe details for every recipe currently marked status='unavailable'.

    This is faster than a full refresh (~90 s for 168 recipes vs ~8 min for 1031)
    and is the recommended recovery path when transient Cookidoo API errors caused
    failures during a previous full refresh.
    """
    global _cache_status

    _cache_status = {
        "state": "running",
        "progress": {"done": 0, "total": 0},
        "last_refreshed": _cache_status.get("last_refreshed"),
        "error": None,
    }
    if on_progress:
        on_progress(get_cache_status())

    try:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, recipe_type, collection_id FROM recipes WHERE status = 'unavailable'"
        ) as cur:
            rows = await cur.fetchall()

        total = len(rows)
        _cache_status["progress"]["total"] = total
        if on_progress:
            on_progress(get_cache_status())

        done = 0
        for row in rows:
            recipe_id = row["id"]
            recipe_name = row["name"]
            recipe_type = row["recipe_type"]
            collection_id = row["collection_id"]

            await asyncio.sleep(0.5)
            try:
                # Always try get_recipe_details first. Custom collections can
                # contain standard Cookidoo recipes (r{id}) alongside truly
                # user-created recipes; only the latter need get_custom_recipe.
                try:
                    details = await cc.get_recipe_details(client, recipe_id)
                    ingredients = [
                        {
                            "name": ing.name,
                            "quantity": _parse_description(ing.description)[0],
                            "unit": _parse_description(ing.description)[1],
                        }
                        for ing in details.ingredients
                    ]
                    raw = json.dumps(dataclasses.asdict(details))
                    await _upsert_recipe(
                        db,
                        recipe_id=recipe_id,
                        name=details.name,
                        status="ok",
                        recipe_type="cookidoo",
                        collection_id=collection_id,
                        cooking_time=details.total_time // 60 if details.total_time else None,
                        servings=details.serving_size or None,
                        ingredients=ingredients,
                        raw_json=raw,
                    )
                except Exception:
                    if recipe_type != "custom":
                        raise
                    # Fall back for truly user-created recipes
                    details = await cc.get_custom_recipe(client, recipe_id)
                    ingredients = [
                        {"name": s, "quantity": None, "unit": None}
                        for s in details.ingredients
                    ]
                    await _upsert_recipe(
                        db,
                        recipe_id=recipe_id,
                        name=details.name,
                        status="ok",
                        recipe_type="custom",
                        collection_id=collection_id,
                        cooking_time=details.total_time // 60 if details.total_time else None,
                        servings=details.serving_size or None,
                        ingredients=ingredients,
                        raw_json=None,
                    )
            except Exception as exc:
                _LOGGER.warning(
                    "Retry failed for recipe %s (%s): %s",
                    recipe_id,
                    recipe_name,
                    exc,
                )
                # Leave status='unavailable' — upsert would be a no-op anyway.

            await db.commit()
            done += 1
            _cache_status["progress"]["done"] = done
            if on_progress:
                on_progress(get_cache_status())

        _cache_status["state"] = "done"
        _cache_status["last_refreshed"] = datetime.now(timezone.utc).isoformat()

    except Exception as exc:
        _LOGGER.error("Retry unavailable failed: %s", exc)
        _cache_status["state"] = "error"
        _cache_status["error"] = str(exc)
        await db.rollback()
        raise

    finally:
        if on_progress:
            on_progress(get_cache_status())


async def refresh_cache(
    db: aiosqlite.Connection,
    client,  # cookidoo_api.Cookidoo — avoid circular import from type hint
    on_progress: Callable[[dict], None] | None = None,
) -> None:
    """Enumerate all collections, fetch recipe details, and persist to DB.

    Parameters
    ----------
    db:
        Open aiosqlite connection.
    client:
        The Cookidoo singleton (app.state.cookidoo).
    on_progress:
        Optional callback invoked after each recipe is processed.
        Receives a shallow copy of _cache_status.
    """
    global _cache_status

    # Preserve last_refreshed across the running phase
    _cache_status = {
        "state": "running",
        "progress": {"done": 0, "total": 0},
        "last_refreshed": _cache_status.get("last_refreshed"),
        "error": None,
    }
    if on_progress:
        on_progress(get_cache_status())

    try:
        # ------------------------------------------------------------------
        # 1. Count pages upfront for both collection types
        # ------------------------------------------------------------------
        _, managed_pages = await cc.count_managed_collections(client)
        _, custom_pages = await cc.count_custom_collections(client)

        # ------------------------------------------------------------------
        # 2. Enumerate managed collections → collect (id, name, col_id)
        # ------------------------------------------------------------------
        managed_recipes: list[tuple[str, str, str | None]] = []
        for page in range(managed_pages):
            collections = await cc.get_managed_collections(client, page)
            for col in collections:
                for chapter in col.chapters:
                    for recipe in chapter.recipes:
                        managed_recipes.append((recipe.id, recipe.name, col.id))

        # ------------------------------------------------------------------
        # 3. Enumerate custom collections
        # ------------------------------------------------------------------
        custom_recipes: list[tuple[str, str, str | None]] = []
        for page in range(custom_pages):
            collections = await cc.get_custom_collections(client, page)
            for col in collections:
                for chapter in col.chapters:
                    for recipe in chapter.recipes:
                        custom_recipes.append((recipe.id, recipe.name, col.id))

        # ------------------------------------------------------------------
        # 4. Deduplicate (first occurrence wins; managed takes priority)
        # ------------------------------------------------------------------
        seen: set[str] = set()
        unique_managed: list[tuple[str, str, str | None]] = []
        for item in managed_recipes:
            if item[0] not in seen:
                seen.add(item[0])
                unique_managed.append(item)

        unique_custom: list[tuple[str, str, str | None]] = []
        for item in custom_recipes:
            if item[0] not in seen:
                seen.add(item[0])
                unique_custom.append(item)

        total = len(unique_managed) + len(unique_custom)
        _cache_status["progress"]["total"] = total
        if on_progress:
            on_progress(get_cache_status())

        done = 0

        # ------------------------------------------------------------------
        # 5. Fetch managed recipe details
        # ------------------------------------------------------------------
        for recipe_id, recipe_name, collection_id in unique_managed:
            await asyncio.sleep(0.5)
            try:
                details = await cc.get_recipe_details(client, recipe_id)
                ingredients = [
                    {
                        "name": ing.name,
                        "quantity": _parse_description(ing.description)[0],
                        "unit": _parse_description(ing.description)[1],
                    }
                    for ing in details.ingredients
                ]
                raw = json.dumps(dataclasses.asdict(details))
                await _upsert_recipe(
                    db,
                    recipe_id=recipe_id,
                    name=details.name,
                    status="ok",
                    recipe_type="cookidoo",
                    collection_id=collection_id,
                    cooking_time=details.total_time // 60 if details.total_time else None,
                    servings=details.serving_size or None,
                    ingredients=ingredients,
                    raw_json=raw,
                )
            except Exception as exc:
                _LOGGER.warning(
                    "Failed to fetch details for managed recipe %s (%s): %s",
                    recipe_id,
                    recipe_name,
                    exc,
                )
                await _upsert_unavailable(db, recipe_id, recipe_name, "cookidoo", collection_id)

            # Commit after every recipe so the write lock is released between
            # fetches. This prevents a 6-minute write transaction from blocking
            # pantry/meal-plan writes while a refresh is in progress.
            await db.commit()

            done += 1
            _cache_status["progress"]["done"] = done
            if on_progress:
                on_progress(get_cache_status())

        # ------------------------------------------------------------------
        # 6. Fetch custom collection recipe details
        #
        # Custom collections can contain both standard Cookidoo recipes (saved
        # by the user with a standard r{id}) and truly user-created recipes
        # (different ID format). We try get_recipe_details first; if that fails
        # we fall back to get_custom_recipe, which handles user-created ones.
        # ------------------------------------------------------------------
        for recipe_id, recipe_name, collection_id in unique_custom:
            await asyncio.sleep(0.5)
            try:
                try:
                    details = await cc.get_recipe_details(client, recipe_id)
                    ingredients = [
                        {
                            "name": ing.name,
                            "quantity": _parse_description(ing.description)[0],
                            "unit": _parse_description(ing.description)[1],
                        }
                        for ing in details.ingredients
                    ]
                    raw = json.dumps(dataclasses.asdict(details))
                    await _upsert_recipe(
                        db,
                        recipe_id=recipe_id,
                        name=details.name,
                        status="ok",
                        recipe_type="cookidoo",
                        collection_id=collection_id,
                        cooking_time=details.total_time // 60 if details.total_time else None,
                        servings=details.serving_size or None,
                        ingredients=ingredients,
                        raw_json=raw,
                    )
                except Exception:
                    # Fall back to custom recipe endpoint for user-created recipes
                    details = await cc.get_custom_recipe(client, recipe_id)
                    ingredients = [
                        {"name": s, "quantity": None, "unit": None}
                        for s in details.ingredients
                    ]
                    await _upsert_recipe(
                        db,
                        recipe_id=recipe_id,
                        name=details.name,
                        status="ok",
                        recipe_type="custom",
                        collection_id=collection_id,
                        cooking_time=details.total_time // 60 if details.total_time else None,
                        servings=details.serving_size or None,
                        ingredients=ingredients,
                        raw_json=None,
                    )
            except Exception as exc:
                _LOGGER.warning(
                    "Failed to fetch details for custom recipe %s (%s): %s",
                    recipe_id,
                    recipe_name,
                    exc,
                )
                await _upsert_unavailable(db, recipe_id, recipe_name, "custom", collection_id)

            # Same per-recipe commit as managed recipes above.
            await db.commit()

            done += 1
            _cache_status["progress"]["done"] = done
            if on_progress:
                on_progress(get_cache_status())

        _cache_status["state"] = "done"
        _cache_status["last_refreshed"] = datetime.now(timezone.utc).isoformat()

    except Exception as exc:
        _LOGGER.error("Cache refresh failed: %s", exc)
        _cache_status["state"] = "error"
        _cache_status["error"] = str(exc)
        # Rollback any upsert that executed but was not yet committed
        # (e.g. if db.commit() itself raised).
        await db.rollback()
        raise

    finally:
        if on_progress:
            on_progress(get_cache_status())


# ---------------------------------------------------------------------------
# DB read functions
# ---------------------------------------------------------------------------

async def get_all_recipes(db: aiosqlite.Connection) -> list[RecipeSummary]:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT id, name, status, recipe_type, collection_id, cooking_time"
        " FROM recipes ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()
    return [
        RecipeSummary(
            id=r["id"],
            name=r["name"],
            status=r["status"],
            collection_id=r["collection_id"],
            cooking_time=r["cooking_time"],
            recipe_type=r["recipe_type"],
        )
        for r in rows
    ]


async def get_recipe_details(
    db: aiosqlite.Connection, recipe_id: str
) -> RecipeDetails | None:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT id, name, status, recipe_type, collection_id,"
        "       cooking_time, servings, ingredients_json, source_url"
        " FROM recipes WHERE id = ?",
        (recipe_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        return None

    ingredients: list[Ingredient] = []
    if row["ingredients_json"]:
        try:
            raw_list = json.loads(row["ingredients_json"])
            ingredients = [
                Ingredient(
                    name=item["name"],
                    quantity=item.get("quantity"),
                    unit=item.get("unit"),
                )
                for item in raw_list
            ]
        except (json.JSONDecodeError, KeyError):
            _LOGGER.warning("Malformed ingredients_json for recipe %s", recipe_id)

    return RecipeDetails(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        collection_id=row["collection_id"],
        cooking_time=row["cooking_time"],
        servings=row["servings"],
        ingredients=ingredients,
        recipe_type=row["recipe_type"],
        source_url=row["source_url"],
    )


async def get_all_recipe_details(
    db: aiosqlite.Connection,
) -> list[RecipeDetails]:
    """Return full RecipeDetails for every status='ok' recipe.

    Used by the suggestions route, which needs ingredient lists for scoring.
    """
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT id, name, status, recipe_type, collection_id,"
        "       cooking_time, servings, ingredients_json, source_url"
        " FROM recipes WHERE status = 'ok' ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()

    result: list[RecipeDetails] = []
    for row in rows:
        ingredients: list[Ingredient] = []
        if row["ingredients_json"]:
            try:
                raw_list = json.loads(row["ingredients_json"])
                ingredients = [
                    Ingredient(
                        name=item["name"],
                        quantity=item.get("quantity"),
                        unit=item.get("unit"),
                    )
                    for item in raw_list
                ]
            except (json.JSONDecodeError, KeyError):
                _LOGGER.warning("Malformed ingredients_json for recipe %s", row["id"])
        result.append(
            RecipeDetails(
                id=row["id"],
                name=row["name"],
                status=row["status"],
                collection_id=row["collection_id"],
                cooking_time=row["cooking_time"],
                servings=row["servings"],
                ingredients=ingredients,
                recipe_type=row["recipe_type"],
                source_url=row["source_url"],
            )
        )
    return result


async def search_recipes(
    db: aiosqlite.Connection,
    q: str,
    max_time: int | None,
) -> list[RecipeSummary]:
    db.row_factory = aiosqlite.Row
    like = f"%{q}%" if q else "%"

    if max_time is not None:
        async with db.execute(
            "SELECT id, name, status, recipe_type, collection_id, cooking_time"
            " FROM recipes"
            " WHERE name LIKE ?"
            "   AND cooking_time IS NOT NULL AND cooking_time <= ?"
            " ORDER BY name",
            (like, max_time),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with db.execute(
            "SELECT id, name, status, recipe_type, collection_id, cooking_time"
            " FROM recipes WHERE name LIKE ? ORDER BY name",
            (like,),
        ) as cur:
            rows = await cur.fetchall()

    return [
        RecipeSummary(
            id=r["id"],
            name=r["name"],
            status=r["status"],
            collection_id=r["collection_id"],
            cooking_time=r["cooking_time"],
            recipe_type=r["recipe_type"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Local custom recipe CRUD
# ---------------------------------------------------------------------------

async def create_custom_recipe(
    db: aiosqlite.Connection,
    *,
    name: str,
    servings: int | None,
    cooking_time: int | None,
    ingredients: list[dict],
    source_url: str | None,
) -> RecipeDetails:
    recipe_id = f"custom-{uuid.uuid4().hex}"
    ingredients_json = json.dumps(ingredients) if ingredients else None
    await db.execute(
        """
        INSERT INTO recipes
            (id, name, status, recipe_type, collection_id,
             cooking_time, servings, ingredients_json, raw_json, source_url)
        VALUES (?, ?, 'ok', 'local_custom', NULL, ?, ?, ?, NULL, ?)
        """,
        (recipe_id, name, cooking_time, servings, ingredients_json, source_url),
    )
    await db.commit()
    return RecipeDetails(
        id=recipe_id,
        name=name,
        status="ok",
        recipe_type="local_custom",
        collection_id=None,
        cooking_time=cooking_time,
        servings=servings,
        ingredients=[
            Ingredient(name=i["name"], quantity=i.get("quantity"), unit=i.get("unit"))
            for i in ingredients
        ],
        source_url=source_url,
    )


async def update_custom_recipe(
    db: aiosqlite.Connection,
    recipe_id: str,
    *,
    name: str,
    servings: int | None,
    cooking_time: int | None,
    ingredients: list[dict],
    source_url: str | None,
) -> RecipeDetails | None:
    if not is_local_custom(recipe_id):
        return None
    ingredients_json = json.dumps(ingredients) if ingredients else None
    async with db.execute(
        """
        UPDATE recipes
           SET name = ?, cooking_time = ?, servings = ?,
               ingredients_json = ?, source_url = ?
         WHERE id = ? AND recipe_type = 'local_custom'
        """,
        (name, cooking_time, servings, ingredients_json, source_url, recipe_id),
    ) as cur:
        if cur.rowcount == 0:
            return None
    await db.commit()
    return RecipeDetails(
        id=recipe_id,
        name=name,
        status="ok",
        recipe_type="local_custom",
        collection_id=None,
        cooking_time=cooking_time,
        servings=servings,
        ingredients=[
            Ingredient(name=i["name"], quantity=i.get("quantity"), unit=i.get("unit"))
            for i in ingredients
        ],
        source_url=source_url,
    )


async def delete_custom_recipe(
    db: aiosqlite.Connection, recipe_id: str
) -> bool:
    if not is_local_custom(recipe_id):
        return False
    async with db.execute(
        "DELETE FROM recipes WHERE id = ? AND recipe_type = 'local_custom'",
        (recipe_id,),
    ) as cur:
        deleted = cur.rowcount > 0
    if deleted:
        await db.commit()
    return deleted
