"""FastAPI application — routes, CORS, lifespan.

Single-worker only: app.state.cookidoo, app.state.http, and recipe_cache._cache_status
are all process-local. Do not run with --workers > 1.
"""
from __future__ import annotations

import asyncio
import logging
import os
import ssl
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import AsyncGenerator

import aiohttp
import aiosqlite
import certifi
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cookidoo_api import Cookidoo
from cookidoo_api.exceptions import CookidooAuthException
from cookidoo_api.types import CookidooConfig, CookidooLocalizationConfig

import backend.cookidoo_client as cc
import backend.meal_plan as meal_plan
import backend.pantry as pantry
import backend.recipe_cache as recipe_cache
import backend.shopping as shopping
import backend.suggestions as suggestions
from backend.db import DB_PATH, init_schema
from backend.models import (
    CacheProgress,
    CacheStatus,
    PantryItem,
    RecipeDetails,
    RecipeSummary,
    ScoredRecipe,
    ShoppingList,
    WeekSlot,
)

load_dotenv()

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Day / meal string → int mappings (path param validation)
# ---------------------------------------------------------------------------

_DAY_MAP: dict[str, int] = {
    "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6,
}
_MEAL_MAP: dict[str, int] = {"lunch": 0, "dinner": 1}


def _parse_day(s: str) -> int:
    if s not in _DAY_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid day '{s}'. Allowed: {list(_DAY_MAP)}",
        )
    return _DAY_MAP[s]


def _parse_meal(s: str) -> int:
    if s not in _MEAL_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid meal '{s}'. Allowed: {list(_MEAL_MAP)}",
        )
    return _MEAL_MAP[s]


# ---------------------------------------------------------------------------
# Inline request body models (not exported to models.py — used here only)
# ---------------------------------------------------------------------------

class SlotBody(BaseModel):
    recipe_id: str


class PantryItemBody(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None


class IngredientBody(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None


class CustomRecipeBody(BaseModel):
    name: str
    servings: int | None = None
    cooking_time: int | None = None
    ingredients: list[IngredientBody] = []
    source_url: str | None = None


# ---------------------------------------------------------------------------
# ISO week helpers
# ---------------------------------------------------------------------------

def _iso_week_str(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _current_week() -> str:
    return _iso_week_str(date.today())


def _next_week() -> str:
    return _iso_week_str(date.today() + timedelta(weeks=1))


# ---------------------------------------------------------------------------
# Per-request DB dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(DB_PATH) as db:
        yield db


# ---------------------------------------------------------------------------
# Background task wrapper — owns its own DB connection (request's closes first)
# ---------------------------------------------------------------------------

async def _run_refresh(cookidoo: Cookidoo) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await recipe_cache.refresh_cache(db, cookidoo)
        except Exception:
            _LOGGER.exception("Cache refresh task failed")
            raise


async def _run_retry(cookidoo: Cookidoo) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await recipe_cache.retry_unavailable(db, cookidoo)
        except Exception:
            _LOGGER.exception("Retry unavailable task failed")
            raise


# ---------------------------------------------------------------------------
# Lifespan: aiohttp session (outer) → Cookidoo login → yield → shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(connector=connector) as session:
        app.state.http = session
        country = os.getenv("COOKIDOO_COUNTRY", "it")
        language = os.getenv("COOKIDOO_LANGUAGE", "it-IT")
        cfg = CookidooConfig(
            email=os.environ["COOKIDOO_EMAIL"],
            password=os.environ["COOKIDOO_PASSWORD"],
            localization=CookidooLocalizationConfig(
                country_code=country,
                language=language,
                url=f"https://cookidoo.{country}/foundation/{language}",
            ),
        )
        app.state.cookidoo = Cookidoo(session, cfg)
        await app.state.cookidoo.login()  # intentional crash on bad credentials
        # Init DB schema once at startup; per-request get_db() connections see it immediately.
        async with aiosqlite.connect(DB_PATH) as _db:
            await init_schema(_db)
        app.state.refresh_task = None
        yield
        # Shutdown: cancel any in-flight cache refresh
        task: asyncio.Task | None = app.state.refresh_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Thermomix Planner", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/weeks/current")
async def get_current_weeks() -> dict[str, str]:
    return {"current": _current_week(), "next": _next_week()}


@app.get("/api/recipes")
async def list_recipes(
    db: aiosqlite.Connection = Depends(get_db),
) -> list[RecipeSummary]:
    return await recipe_cache.get_all_recipes(db)


# Must be declared before /api/recipes/{id} to avoid path param conflicts
@app.post("/api/recipes/custom", status_code=201)
async def create_custom_recipe(
    body: CustomRecipeBody,
    db: aiosqlite.Connection = Depends(get_db),
) -> RecipeDetails:
    ingredients = [i.model_dump() for i in body.ingredients]
    return await recipe_cache.create_custom_recipe(
        db,
        name=body.name,
        servings=body.servings,
        cooking_time=body.cooking_time,
        ingredients=ingredients,
        source_url=body.source_url,
    )


@app.put("/api/recipes/custom/{id}")
async def update_custom_recipe(
    id: str,
    body: CustomRecipeBody,
    db: aiosqlite.Connection = Depends(get_db),
) -> RecipeDetails:
    ingredients = [i.model_dump() for i in body.ingredients]
    result = await recipe_cache.update_custom_recipe(
        db,
        id,
        name=body.name,
        servings=body.servings,
        cooking_time=body.cooking_time,
        ingredients=ingredients,
        source_url=body.source_url,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Custom recipe not found")
    return result


@app.delete("/api/recipes/custom/{id}", status_code=204)
async def delete_custom_recipe(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> Response:
    deleted = await recipe_cache.delete_custom_recipe(db, id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Custom recipe not found")
    return Response(status_code=204)


@app.get("/api/recipes/search")
async def search_recipes(
    q: str = "",
    max_time: int | None = None,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[RecipeSummary]:
    return await recipe_cache.search_recipes(db, q, max_time)


@app.get("/api/recipes/{id}")
async def get_recipe(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> RecipeDetails:
    recipe = await recipe_cache.get_recipe_details(db, id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@app.post("/api/cache/refresh", status_code=202)
async def start_cache_refresh(request: Request) -> Response:
    task: asyncio.Task | None = request.app.state.refresh_task
    if task and not task.done():
        raise HTTPException(
            status_code=409,
            detail=recipe_cache.get_cache_status(),
        )
    request.app.state.refresh_task = asyncio.create_task(
        _run_refresh(request.app.state.cookidoo)
    )
    return Response(status_code=202)


@app.post("/api/cache/retry", status_code=202)
async def retry_unavailable(request: Request) -> Response:
    """Re-fetch only recipes currently marked status='unavailable' (~90 s vs ~8 min full refresh)."""
    task: asyncio.Task | None = request.app.state.refresh_task
    if task and not task.done():
        raise HTTPException(
            status_code=409,
            detail=recipe_cache.get_cache_status(),
        )
    request.app.state.refresh_task = asyncio.create_task(
        _run_retry(request.app.state.cookidoo)
    )
    return Response(status_code=202)


@app.get("/api/cache/status")
async def cache_status(
    db: aiosqlite.Connection = Depends(get_db),
) -> CacheStatus:
    s = recipe_cache.get_cache_status()
    async with db.execute(
        "SELECT status, COUNT(*) FROM recipes GROUP BY status"
    ) as cur:
        rows = await cur.fetchall()
    counts = {row[0]: row[1] for row in rows}
    return CacheStatus(
        state=s["state"],
        progress=CacheProgress(**s["progress"]),
        last_refreshed=s["last_refreshed"],
        error=s["error"],
        recipe_count=counts.get("ok", 0),
        unavailable_count=counts.get("unavailable", 0),
    )


@app.get("/api/plan")
async def get_plan(
    week: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[WeekSlot]:
    iso_week = week if week is not None else _current_week()
    return await meal_plan.get_week(db, iso_week)


@app.put("/api/plan/{iso_week}/{day}/{meal}")
async def set_plan_slot(
    iso_week: str,
    day: str,
    meal: str,
    body: SlotBody,
    db: aiosqlite.Connection = Depends(get_db),
) -> WeekSlot:
    day_int = _parse_day(day)
    meal_int = _parse_meal(meal)
    try:
        return await meal_plan.set_slot(db, iso_week, day_int, meal_int, body.recipe_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/plan/{iso_week}/{day}/{meal}", status_code=204)
async def clear_plan_slot(
    iso_week: str,
    day: str,
    meal: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> Response:
    day_int = _parse_day(day)
    meal_int = _parse_meal(meal)
    deleted = await meal_plan.clear_slot(db, iso_week, day_int, meal_int)
    if not deleted:
        raise HTTPException(status_code=404, detail="Slot not found")
    return Response(status_code=204)


@app.get("/api/pantry")
async def list_pantry(
    db: aiosqlite.Connection = Depends(get_db),
) -> list[PantryItem]:
    return await pantry.list_items(db)


@app.post("/api/pantry", status_code=201)
async def add_pantry_item(
    body: PantryItemBody,
    db: aiosqlite.Connection = Depends(get_db),
) -> PantryItem:
    return await pantry.add_item(db, body.name, body.quantity, body.unit)


@app.put("/api/pantry/{id}")
async def update_pantry_item(
    id: str,
    body: PantryItemBody,
    db: aiosqlite.Connection = Depends(get_db),
) -> PantryItem:
    result = await pantry.update_item(db, id, body.name, body.quantity, body.unit)
    if result is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    return result


@app.delete("/api/pantry/{id}", status_code=204)
async def delete_pantry_item(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> Response:
    deleted = await pantry.delete_item(db, id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    return Response(status_code=204)


@app.get("/api/shopping-list")
async def get_shopping_list(
    week: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
) -> ShoppingList:
    iso_week = week if week is not None else _current_week()
    slots = await meal_plan.get_week(db, iso_week)
    pantry_items = await pantry.list_items(db)

    week_plan: dict[tuple[str, int, int], str] = {
        (s.iso_week, s.day, s.meal): s.recipe_id
        for s in slots
        if s.recipe_id
    }

    # Fetch details for each unique recipe_id in the plan.
    # recipe_id not found in cache → absent from recipe_details dict;
    # build_shopping_list will put the recipe_id in unavailable_recipes.
    recipe_details: dict[str, RecipeDetails] = {}
    for recipe_id in set(week_plan.values()):
        details = await recipe_cache.get_recipe_details(db, recipe_id)
        if details is not None:
            recipe_details[recipe_id] = details

    return shopping.build_shopping_list(week_plan, pantry_items, recipe_details)


@app.get("/api/suggestions")
async def get_suggestions(
    max_time: int | None = None,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[ScoredRecipe]:
    all_recipes = await recipe_cache.get_all_recipe_details(db)
    pantry_items = await pantry.list_items(db)
    recent_ids = await meal_plan.get_recent_ids(db)
    return suggestions.top_suggestions(pantry_items, all_recipes, recent_ids, max_time=max_time)


@app.post("/api/sync/calendar")
async def sync_calendar(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> Response:
    slots = await meal_plan.get_week(db, _current_week())
    try:
        await cc.push_week_to_calendar(request.app.state.cookidoo, slots)
    except CookidooAuthException as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return Response(status_code=200)


@app.post("/api/sync/shopping")
async def sync_shopping(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> Response:
    slots = await meal_plan.get_week(db, _current_week())
    # Only pass recipe_ids for cached, available recipes
    recipe_ids: list[str] = []
    for slot in slots:
        if slot.recipe_id:
            details = await recipe_cache.get_recipe_details(db, slot.recipe_id)
            if details and details.status == "ok" and details.recipe_type != "local_custom":
                recipe_ids.append(slot.recipe_id)
    pantry_items = await pantry.list_items(db)
    try:
        await cc.sync_shopping_list(request.app.state.cookidoo, recipe_ids, pantry_items)
    except CookidooAuthException as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return Response(status_code=200)
