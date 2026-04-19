from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

RecipeStatus = Literal["ok", "unavailable"]


class Ingredient(BaseModel):
    name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None


class AggregatedIngredient(BaseModel):
    name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    recipe_sources: List[str]
    check_units: bool = False   # True when same ingredient has incompatible units


# ---------------------------------------------------------------------------
# Recipe types
# ---------------------------------------------------------------------------

class RecipeSummary(BaseModel):
    id: str
    name: str
    status: RecipeStatus = "ok"
    collection_id: Optional[str] = None
    cooking_time: Optional[int] = None  # minutes; None for unavailable recipes
    recipe_type: str = "cookidoo"       # 'cookidoo' | 'custom' | 'local_custom'


class RecipeDetails(BaseModel):
    id: str
    name: str
    status: RecipeStatus = "ok"
    collection_id: Optional[str] = None
    cooking_time: Optional[int] = None  # minutes; None for unavailable recipes
    servings: Optional[int] = None      # default servings from Cookidoo; None for unavailable
    ingredients: List[Ingredient] = []
    recipe_type: str = "cookidoo"       # 'cookidoo' | 'custom' | 'local_custom'
    source_url: Optional[str] = None    # user-supplied URL for local_custom recipes


class ScoredRecipe(BaseModel):
    recipe: RecipeDetails
    score: float  # [0.0, 1.0] — coverage minus recency penalty, clamped to 0


# ---------------------------------------------------------------------------
# Pantry
# ---------------------------------------------------------------------------

class PantryItem(BaseModel):
    id: str
    name: str       # normalised lowercase; stored as entered by user
    quantity: Optional[float] = None
    unit: Optional[str] = None


# ---------------------------------------------------------------------------
# Shopping list
# ---------------------------------------------------------------------------

class ShoppingItem(BaseModel):
    name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    owned: bool = False             # True if matched against a pantry item
    recipe_sources: List[str]       # recipe names that contribute this ingredient
    check_units: bool = False       # True when incompatible units detected for this ingredient


class ShoppingList(BaseModel):
    items: List[ShoppingItem]
    # Names of recipes that were in the plan but had status='unavailable'.
    # Their ingredients are excluded; caller should warn the user.
    unavailable_recipes: List[str]


# ---------------------------------------------------------------------------
# Meal plan
# ---------------------------------------------------------------------------

class WeekSlot(BaseModel):
    iso_week: str           # e.g. '2025-W22'
    day: int                # 0=Mon … 6=Sun
    meal: int               # 0=lunch, 1=dinner
    recipe_id: Optional[str] = None
    recipe_type: str = "cookidoo"   # stub: 'cookidoo' | 'custom'
    assigned_at: Optional[str] = None  # ISO timestamp, UTC


# ---------------------------------------------------------------------------
# Cache status
# ---------------------------------------------------------------------------

class CacheProgress(BaseModel):
    done: int
    total: int


class CacheStatus(BaseModel):
    state: Literal["idle", "running", "done", "error"]
    progress: CacheProgress
    last_refreshed: Optional[str] = None  # ISO timestamp, UTC
    error: Optional[str] = None
    recipe_count: int = 0       # COUNT(*) WHERE status='ok'; 0 on error or pre-cache
    unavailable_count: int = 0  # COUNT(*) WHERE status='unavailable'
