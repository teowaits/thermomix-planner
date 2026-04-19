"""
shopping.py — pure functions, no DB, no network, no async.

Route handlers are responsible for fetching all required data from the DB and
passing plain data structures into these functions.

Phase 2 notes:
- Pantry matching uses rapidfuzz WRatio ≥ FUZZY_THRESHOLD (from suggestions.py).
- Unit normalisation converts mass (g/kg/mg) and volume (ml/l/cl/dl) to
  canonical units before aggregation. Ingredients with incompatible units
  (e.g. g vs ml) are kept as separate lines and flagged check_units=True.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from backend.suggestions import FUZZY_THRESHOLD, normalise_ingredient_name
from backend.models import (
    AggregatedIngredient,
    Ingredient,
    PantryItem,
    RecipeDetails,
    ShoppingItem,
    ShoppingList,
)

# Default servings per meal slot: 0=lunch → 2 portions, 1=dinner → 4 portions.
DEFAULT_SERVINGS: dict[int, int] = {0: 2, 1: 4}

# Unit → (canonical_unit, conversion_factor).
# Mass canonical: g.  Volume canonical: ml.  Count canonical: pcs.
# Unit strings are matched after lowercasing and stripping.
_UNIT_CANON: dict[str, tuple[str, float]] = {
    # mass → g
    "g": ("g", 1.0), "gr": ("g", 1.0), "gram": ("g", 1.0), "grams": ("g", 1.0),
    "kg": ("g", 1000.0), "mg": ("g", 0.001),
    # volume → ml
    "ml": ("ml", 1.0), "l": ("ml", 1000.0),
    "cl": ("ml", 10.0), "dl": ("ml", 100.0),
    # count → pcs (unit=None and unit="" both map here)
    "": ("pcs", 1.0), "pcs": ("pcs", 1.0),
    "piece": ("pcs", 1.0), "pieces": ("pcs", 1.0),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_pantry_name(name: str) -> str:
    """Lowercase and strip leading/trailing whitespace for pantry matching."""
    return name.strip().lower()


def _to_canonical(
    quantity: float | None,
    unit: str | None,
) -> tuple[float | None, str | None, bool]:
    """Convert quantity+unit to canonical form.

    Returns (canonical_qty, canonical_unit, is_known).
    is_known=False means the unit is not in _UNIT_CANON — treat as opaque.
    """
    key = (unit or "").lower().strip()
    if key not in _UNIT_CANON:
        return quantity, unit, False
    canon_unit, factor = _UNIT_CANON[key]
    canon_qty = quantity * factor if quantity is not None else None
    return canon_qty, canon_unit, True


# ---------------------------------------------------------------------------
# Public pure functions
# ---------------------------------------------------------------------------

def scale_ingredients(
    ingredients: List[Ingredient],
    servings: int,
) -> List[Ingredient]:
    """
    Return a new list of Ingredients with quantities scaled to `servings`.

    Scaling is relative to the recipe's default serving count stored on each
    Ingredient — but since the Cookidoo API returns absolute quantities for the
    recipe's default serving, we scale by the ratio:
        scaled_qty = original_qty * (target_servings / recipe_default_servings)

    Because recipe_default_servings is not stored per-ingredient (it lives on
    RecipeDetails), the caller must pre-divide if needed.  For Phase 1 the
    simpler contract is used: this function receives ingredients already
    expressed per-1-serving and multiplies by `servings`.  The caller in
    build_shopping_list() handles the division step.

    If quantity is None (ingredient listed without amount), it is left as None.
    """
    scaled = []
    for ing in ingredients:
        if ing.quantity is None:
            scaled.append(ing.model_copy())
        else:
            scaled.append(
                Ingredient(
                    name=ing.name,
                    quantity=ing.quantity * servings,
                    unit=ing.unit,
                )
            )
    return scaled


def aggregate_ingredients(
    ingredient_lists: List[Tuple[List[Ingredient], str]],
) -> List[AggregatedIngredient]:
    """
    Merge ingredient lists from multiple recipes into a single list.

    Each entry in `ingredient_lists` is (ingredients, recipe_name).

    Ingredients with the same normalised name AND the same canonical unit are
    summed. Known units are converted to canonical form before keying (g/kg→g,
    ml/l/cl/dl→ml, count/None→pcs). Unknown units are treated as opaque and
    only aggregate with identical unit strings.

    Ingredients without a quantity are kept as separate lines per recipe source
    (we cannot sum None + None meaningfully).

    check_units=True is set on all rows for a given ingredient name when that
    name appears under more than one canonical unit (e.g. g and ml) — this
    signals a unit conflict the user should review.
    """
    seen: Dict[Tuple[str, str], AggregatedIngredient] = {}
    order: List[Tuple[str, str]] = []

    for ingredients, recipe_name in ingredient_lists:
        for ing in ingredients:
            norm_name = _normalise_pantry_name(ing.name)

            if ing.quantity is None:
                # Never merge quantity-less lines — use a per-recipe sentinel.
                key = (norm_name, f"__none__{recipe_name}")
                canon_qty: float | None = None
                canon_unit: str | None = ing.unit
            else:
                canon_qty, canon_unit, _ = _to_canonical(ing.quantity, ing.unit)
                unit_key = (canon_unit or "").lower().strip()
                key = (norm_name, unit_key)

            if key in seen:
                agg = seen[key]
                if canon_qty is not None and agg.quantity is not None:
                    seen[key] = AggregatedIngredient(
                        name=agg.name,
                        quantity=agg.quantity + canon_qty,
                        unit=agg.unit,
                        recipe_sources=agg.recipe_sources + [recipe_name]
                        if recipe_name not in agg.recipe_sources
                        else agg.recipe_sources,
                    )
                else:
                    if recipe_name not in seen[key].recipe_sources:
                        sources = seen[key].recipe_sources + [recipe_name]
                        seen[key] = seen[key].model_copy(update={"recipe_sources": sources})
            else:
                seen[key] = AggregatedIngredient(
                    name=ing.name,   # preserve original capitalisation
                    quantity=canon_qty,
                    unit=canon_unit,
                    recipe_sources=[recipe_name],
                )
                order.append(key)

    # Detect incompatible-unit conflicts: if the same normalised ingredient
    # name appears under more than one canonical unit key, flag all such rows.
    name_to_keys: dict[str, list] = defaultdict(list)
    for k in order:
        norm_name, unit_key = k
        if not unit_key.startswith("__none__"):
            name_to_keys[norm_name].append(k)
    multi_unit_names = {n for n, ks in name_to_keys.items() if len(ks) > 1}

    result: List[AggregatedIngredient] = []
    for k in order:
        norm_name, unit_key = k
        agg = seen[k]
        conflict = norm_name in multi_unit_names and not unit_key.startswith("__none__")
        result.append(agg.model_copy(update={"check_units": conflict}))
    return result


def build_shopping_list(
    week_plan: Dict[Tuple[str, int, int], str],
    pantry_items: List[PantryItem],
    recipe_cache: Dict[str, RecipeDetails],
) -> ShoppingList:
    """
    Build a shopping list for the given week plan.

    Parameters
    ----------
    week_plan:
        Mapping of (iso_week, day, meal) → recipe_id for every filled slot.
    pantry_items:
        Items the user already owns. Matched ingredients are flagged owned=True.
    recipe_cache:
        Injected — no DB handle. Must contain RecipeDetails for all recipe_ids
        referenced in week_plan. Missing IDs are treated as unavailable.

    Returns
    -------
    ShoppingList
        items: aggregated, scaled, pantry-matched ingredient lines.
        unavailable_recipes: names of recipes that could not supply ingredients
            (status='unavailable' or missing from cache).
    """
    unavailable_names: List[str] = []
    ingredient_lists: List[Tuple[List[Ingredient], str]] = []

    for (iso_week, day, meal), recipe_id in week_plan.items():
        details = recipe_cache.get(recipe_id)

        if details is None or details.status == "unavailable":
            name = details.name if details is not None else recipe_id
            unavailable_names.append(name)
            continue

        target_servings = DEFAULT_SERVINGS[meal]
        recipe_default = details.servings or target_servings  # fall back if missing

        # Scale each ingredient from recipe default → target servings.
        per_one = [
            Ingredient(
                name=ing.name,
                quantity=(ing.quantity / recipe_default) if ing.quantity is not None else None,
                unit=ing.unit,
            )
            for ing in details.ingredients
        ]
        scaled = scale_ingredients(per_one, target_servings)
        ingredient_lists.append((scaled, details.name))

    aggregated = aggregate_ingredients(ingredient_lists)

    pantry_norm_names: List[str] = [
        normalise_ingredient_name(p.name) for p in pantry_items
    ]

    items: list[ShoppingItem] = []
    for agg in aggregated:
        norm = normalise_ingredient_name(agg.name)
        owned = any(
            fuzz.WRatio(norm, p) >= FUZZY_THRESHOLD
            for p in pantry_norm_names
        )

        items.append(
            ShoppingItem(
                name=agg.name,
                quantity=agg.quantity,
                unit=agg.unit,
                owned=owned,
                recipe_sources=agg.recipe_sources,
                check_units=agg.check_units,
            )
        )

    return ShoppingList(items=items, unavailable_recipes=unavailable_names)
