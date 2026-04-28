"""
suggestions.py — scoring and suggestion functions.

Route handlers are responsible for:
  1. Fetching all ok-status RecipeDetails from the DB.
  2. Querying the meal_plan table for recent_recipe_ids (W-1 and W-2 relative
     to the current ISO week) and passing the result as a set[str].
  3. Passing pantry items as a list[PantryItem].
  4. Passing a db connection so ingredients can be resolved to canonical names.

Scoring formula (locked — do not modify):
    coverage        = matched_pantry_ingredients / total_ingredients
    recency_penalty = 0.3 if recipe.id in recent_recipe_ids else 0.0
    final_score     = max(0.0, coverage - recency_penalty)

Phase 2 notes:
  - Ingredient matching uses rapidfuzz WRatio ≥ FUZZY_THRESHOLD (85).
  - Unit normalisation is not applied to ingredient names (Phase 2 Item 1c).

Phase 3 notes:
  - score_recipe_by_pantry and top_suggestions are now async.
  - When db is provided, ingredients are resolved to canonical English names
    via synonyms.resolve_ingredient() before fuzzy comparison. This enables
    cross-language pantry matching (e.g. "cipolla" pantry matches "onion" recipe).
  - When db is None (test mode): dictionary-only resolution, no SQLite/API access.
  - synonyms is imported lazily inside the functions to avoid a circular import
    (synonyms.py imports normalise_ingredient_name from this module).
"""
from __future__ import annotations

from typing import List, Optional, Set

import aiosqlite
from rapidfuzz import fuzz

from backend.models import PantryItem, RecipeDetails, ScoredRecipe

# WRatio score threshold (0–100) for pantry ingredient matching.
# Admits near-misses such as singular/plural and minor spelling variants
# while rejecting unrelated ingredients. Shared with shopping.py.
FUZZY_THRESHOLD = 85


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

# Longest-first so compound forms (dell', de la) match before their prefixes
# (del, de). Order is load-bearing — do not sort alphabetically.
PREPOSITIONS = [
    "dell'", "d'",
    "de la ", "de las ", "de los ",
    "delle ", "della ", "dello ", "degli ", "dei ",
    "del ", "di ", "de ",
]


def normalise_ingredient_name(name: str) -> str:
    """
    Return a normalised ingredient name for matching purposes.

    Rules (Phase 2):
    - Strip leading/trailing whitespace.
    - Lowercase.
    - Strip a leading Italian/Spanish preposition (di, d', de, del, della,
      dello, dell', dei, degli, delle, de la, de las, de los) when it appears
      at the very start of the string. Stripping is skipped if it would leave
      an empty or whitespace-only result.
    - Strip a trailing 's' only when the resulting string is ≥ 4 characters.
      This catches common plurals (eggs→egg, carrots→carrot) while avoiding
      mangling short words (peas stays peas — stripped 'pea' is 3 chars, ok;
      but 'gas' would become 'ga' which is 2 chars, so it is left alone).

    Known approximation: this is not a proper stemmer. 'tomatoes' → 'tomatoe'
    (wrong) but the match will still fail anyway, so it does not create false
    positives. Phase 2 can replace this with a real stemmer.
    """
    normalised = name.strip().lower()

    for prep in PREPOSITIONS:
        if normalised.startswith(prep):
            candidate = normalised[len(prep):]
            if candidate.strip():
                normalised = candidate
            break

    if normalised.endswith("s") and len(normalised) >= 4:
        candidate = normalised[:-1]
        if len(candidate) >= 3:
            return candidate
    return normalised


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

async def score_recipe_by_pantry(
    recipe: RecipeDetails,
    pantry: List[PantryItem],
    recent_recipe_ids: Set[str],
    db: Optional[aiosqlite.Connection] = None,
) -> float:
    """
    Return a pantry-match score in [0.0, 1.0] for the recipe.

    The caller must guarantee recipe.status == 'ok'.  Unavailable recipes
    must be filtered out before calling this function.

    Scoring formula (locked):
        coverage        = matched / total_ingredients
        recency_penalty = 0.3 if recipe.id in recent_recipe_ids else 0.0
        final_score     = max(0.0, coverage - recency_penalty)

    When db is provided, ingredient names are resolved to canonical English via
    synonyms.resolve_ingredient() enabling cross-language matching.
    When db is None, falls back to normalise_ingredient_name() only.

    If the recipe has no ingredients, returns 0.0.
    """
    # Lazy import avoids circular dependency (synonyms imports normalise from here)
    from backend.synonyms import resolve_ingredient  # noqa: PLC0415

    if not recipe.ingredients:
        return 0.0

    pantry_canonical: List[str] = [
        await resolve_ingredient(p.name, db) for p in pantry
    ]

    matched = 0
    for ing in recipe.ingredients:
        ing_canon = await resolve_ingredient(ing.name, db)
        if any(fuzz.WRatio(ing_canon, p) >= FUZZY_THRESHOLD for p in pantry_canonical):
            matched += 1

    coverage = matched / len(recipe.ingredients)
    recency_penalty = 0.3 if recipe.id in recent_recipe_ids else 0.0
    return max(0.0, coverage - recency_penalty)


# ---------------------------------------------------------------------------
# Top suggestions
# ---------------------------------------------------------------------------

async def top_suggestions(
    pantry: List[PantryItem],
    all_recipes: List[RecipeDetails],
    recent_recipe_ids: Set[str],
    max_time: Optional[int] = None,
    n: int = 10,
    db: Optional[aiosqlite.Connection] = None,
) -> List[ScoredRecipe]:
    """
    Return the top-n recipes sorted by pantry-match score descending.

    Parameters
    ----------
    pantry:
        The user's current pantry items.
    all_recipes:
        Pre-filtered to status='ok' by the caller.  This function does not
        re-check status — the caller contract ensures only ok recipes arrive.
    recent_recipe_ids:
        Set of recipe IDs used in W-1 and W-2 (completed weeks only).
        Passed from the route handler's DB query; not fetched here.
    max_time:
        Hard filter on cooking_time (minutes). Recipes with cooking_time >
        max_time are excluded before scoring.  None = no filter.
        Recipes with cooking_time=None pass the filter (time unknown).
    n:
        Number of results to return.

    Returns
    -------
    list[ScoredRecipe]
        Top-n recipes with score > 0, sorted by score descending.
        Recipes with score == 0.0 are excluded.
    """
    candidates = []
    for recipe in all_recipes:
        # Hard filter: cooking_time must be within max_time if specified.
        if max_time is not None and recipe.cooking_time is not None:
            if recipe.cooking_time > max_time:
                continue

        score = await score_recipe_by_pantry(recipe, pantry, recent_recipe_ids, db=db)
        if score > 0.0:
            candidates.append(ScoredRecipe(recipe=recipe, score=score))

    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates[:n]
