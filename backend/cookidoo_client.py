"""Cookidoo network layer — ALL Cookidoo API calls live here.

The Cookidoo singleton is created once in main.py lifespan and passed in;
this module never creates a ClientSession or a Cookidoo instance itself.

Re-login policy: on CookidooAuthException, attempt login() once and retry.
The second failure propagates to the caller (route handler raises 503).

Integration test notes (Step 8 — 2026-04-16):
- Calendar sync (add_recipes_to_calendar): confirmed working with TM5.
  Recipes appear in the Cookidoo calendar correctly via the web/app.
- Shopping sync (add_ingredient_items_for_recipes + edit_ingredient_items_ownership):
  confirmed working; owned/pantry-matched items are flagged in Cookidoo.
- _iso_week_day_to_date() verified correct: date.fromisocalendar(year, week, day+1)
  returns the right date. Today=2026-04-16 (Thu) is mid-W16; Mon of W16 = 2026-04-13
  (already passed). Syncing a W16 Monday slot correctly targets April 13, not April 20.
  April 20 is Mon of W17 (next week). Not a bug — expected ISO week arithmetic.
- Ingredient name quality: Cookidoo returns ingredient names that retain
  language-specific prepositions ("de pan", "di farina") from descriptions
  like "40 g de pan". This is a cookidoo-api library parsing artefact.
  Phase 1 known limitation: pantry matching requires the user to add the
  prefixed form (e.g. "de pan", not "pan") for exact-match to hit.
  Phase 2: consider stripping common "de/di/d'/del/della" prefixes in
  normalise_ingredient_name(), or switch to fuzzy matching.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from cookidoo_api import Cookidoo
from cookidoo_api.exceptions import CookidooAuthException
from cookidoo_api.types import (
    CookidooCalendarDay,
    CookidooCollection,
    CookidooCustomRecipe,
    CookidooIngredientItem,
    CookidooShoppingRecipeDetails,
)

from backend.models import PantryItem, WeekSlot
from backend.suggestions import normalise_ingredient_name


def _is_local_custom(recipe_id: str) -> bool:
    return recipe_id.startswith("custom-")

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _call(client: Cookidoo, fn, *args, **kwargs):
    """Invoke a bound Cookidoo method; re-login once on auth failure."""
    try:
        return await fn(*args, **kwargs)
    except CookidooAuthException:
        _LOGGER.warning("CookidooAuthException — re-logging in once")
        await client.login()
        return await fn(*args, **kwargs)  # second failure propagates to caller


def _iso_week_day_to_date(iso_week: str, day: int) -> date:
    """Convert an ISO week string + 0-based weekday to a date.

    Parameters
    ----------
    iso_week:
        e.g. '2026-W16'
    day:
        0 = Monday … 6 = Sunday
    """
    year_str, week_str = iso_week.split("-W")
    # date.fromisocalendar uses 1-based weekday (1=Mon)
    return date.fromisocalendar(int(year_str), int(week_str), day + 1)


# ---------------------------------------------------------------------------
# Thin wrappers — re-export Cookidoo methods with the re-login guard
# ---------------------------------------------------------------------------

async def get_managed_collections(
    client: Cookidoo, page: int = 0
) -> list[CookidooCollection]:
    return await _call(client, client.get_managed_collections, page)


async def get_recipe_details(
    client: Cookidoo, recipe_id: str
) -> CookidooShoppingRecipeDetails:
    return await _call(client, client.get_recipe_details, recipe_id)


async def add_recipes_to_calendar(
    client: Cookidoo, day: date, recipe_ids: list[str]
) -> CookidooCalendarDay:
    return await _call(client, client.add_recipes_to_calendar, day, recipe_ids)


async def add_custom_recipes_to_calendar(
    client: Cookidoo, day: date, recipe_ids: list[str]
) -> CookidooCalendarDay:
    return await _call(client, client.add_custom_recipes_to_calendar, day, recipe_ids)


async def add_ingredient_items_for_recipes(
    client: Cookidoo, recipe_ids: list[str]
) -> list[CookidooIngredientItem]:
    return await _call(client, client.add_ingredient_items_for_recipes, recipe_ids)


async def edit_ingredient_items_ownership(
    client: Cookidoo, ingredient_items: list[CookidooIngredientItem]
) -> list[CookidooIngredientItem]:
    return await _call(client, client.edit_ingredient_items_ownership, ingredient_items)


async def clear_shopping_list(client: Cookidoo) -> None:
    await _call(client, client.clear_shopping_list)


async def count_managed_collections(client: Cookidoo) -> tuple[int, int]:
    """Return (total_collections, total_pages)."""
    return await _call(client, client.count_managed_collections)


async def count_custom_collections(client: Cookidoo) -> tuple[int, int]:
    """Return (total_collections, total_pages)."""
    return await _call(client, client.count_custom_collections)


async def get_custom_collections(
    client: Cookidoo, page: int = 0
) -> list[CookidooCollection]:
    return await _call(client, client.get_custom_collections, page)


async def get_custom_recipe(
    client: Cookidoo, recipe_id: str
) -> CookidooCustomRecipe:
    return await _call(client, client.get_custom_recipe, recipe_id)


# ---------------------------------------------------------------------------
# High-level sync operations (called by route handlers)
# ---------------------------------------------------------------------------

async def push_week_to_calendar(
    client: Cookidoo, slots: list[WeekSlot]
) -> None:
    """Push a week's non-empty meal-plan slots to the Cookidoo calendar.

    Slots are grouped by day so each calendar day receives a single API call.
    Slots with no recipe_id are silently skipped.
    Local custom recipes (id prefix 'custom-') are silently skipped —
    they don't exist in Cookidoo so there's nothing to push.
    Cookidoo-hosted custom recipes (recipe_type='custom') use the separate
    add_custom_recipes_to_calendar endpoint.
    """
    # Separate by API routing: standard Cookidoo vs hosted custom
    day_standard: dict[int, list[str]] = defaultdict(list)
    day_cookidoo_custom: dict[int, list[str]] = defaultdict(list)
    iso_week: str | None = None

    for slot in slots:
        if not slot.recipe_id:
            continue
        if _is_local_custom(slot.recipe_id):
            # Local custom recipes have no Cookidoo ID — skip silently
            _LOGGER.debug("push_week_to_calendar: skipping local custom recipe %s", slot.recipe_id)
            continue
        iso_week = slot.iso_week
        if slot.recipe_type == "custom":
            day_cookidoo_custom[slot.day].append(slot.recipe_id)
        else:
            day_standard[slot.day].append(slot.recipe_id)

    if not iso_week or (not day_standard and not day_cookidoo_custom):
        _LOGGER.info("push_week_to_calendar: nothing to push")
        return

    all_days = set(day_standard) | set(day_cookidoo_custom)
    for day in sorted(all_days):
        target_date = _iso_week_day_to_date(iso_week, day)
        if day_standard.get(day):
            _LOGGER.info(
                "push_week_to_calendar: adding %d standard recipe(s) to %s",
                len(day_standard[day]), target_date,
            )
            await add_recipes_to_calendar(client, target_date, day_standard[day])
        if day_cookidoo_custom.get(day):
            _LOGGER.info(
                "push_week_to_calendar: adding %d cookidoo-custom recipe(s) to %s",
                len(day_cookidoo_custom[day]), target_date,
            )
            await add_custom_recipes_to_calendar(client, target_date, day_cookidoo_custom[day])


async def sync_shopping_list(
    client: Cookidoo,
    recipe_ids: list[str],
    pantry_items: list[PantryItem],
) -> None:
    """Replace the Cookidoo shopping list with ingredients for the given recipes.

    Steps:
    1. Clear the existing shopping list.
    2. Add ingredient items for all recipe_ids (no-op if list is empty).
    3. Mark items as owned when their normalised name matches a pantry item.

    Parameters
    ----------
    client:
        The shared Cookidoo singleton.
    recipe_ids:
        IDs of recipes whose ingredients should appear in the shopping list.
        Only status='ok' recipes should be passed; unavailable ones are excluded
        upstream by the route handler.
    pantry_items:
        Current pantry; matched items are flagged as owned in Cookidoo.
    """
    await clear_shopping_list(client)

    if not recipe_ids:
        _LOGGER.info("sync_shopping_list: no recipes — list cleared and left empty")
        return

    ingredient_items = await add_ingredient_items_for_recipes(client, recipe_ids)

    # Match by normalised ingredient name against pantry
    pantry_names = {normalise_ingredient_name(p.name) for p in pantry_items}
    to_own = [
        item
        for item in ingredient_items
        if not item.is_owned and normalise_ingredient_name(item.name) in pantry_names
    ]

    if to_own:
        for item in to_own:
            item.is_owned = True
        await edit_ingredient_items_ownership(client, to_own)
        _LOGGER.info("sync_shopping_list: marked %d item(s) as owned", len(to_own))
