# CLAUDE.md — Thermomix Meal Planner

> Full design documentation and decision rationale are in `CLAUDE.docx` in this directory.
> This file is the quick-reference for Claude Code sessions.

---

## What this project is

A local-first web app for planning Thermomix meals across a rolling 2-week window, backed by a cached Cookidoo recipe library. The pantry-matching suggestions engine is the core value feature. Phase 1 is a single-user local tool; Docker + multi-user is Phase 2.

---

## Hard constraints

| Constraint | Rule |
|---|---|
| DB async | ALL SQLite access via `aiosqlite` — never `sqlite3` directly |
| Cookidoo isolation | All Cookidoo network calls live exclusively in `cookidoo_client.py` |
| aiohttp session | `aiohttp.ClientSession` created **once** in FastAPI lifespan, stored in `app.state.http`; passed into `Cookidoo()` constructor — never created per-request or inside `cookidoo_client.py` |
| Cookidoo singleton | `Cookidoo` client instantiated **once** in lifespan after `login()`; stored as `app.state.cookidoo`; reused across all requests; re-login attempted once on `CookidooAuthException` before raising 503 |
| Single-worker only | Do not run with `--workers > 1` — `app.state.cookidoo`, `app.state.http`, and `_cache_status` dict are all process-local |
| Pure function boundary | `shopping.py` and `suggestions.py` are pure — no DB handles, no network calls |
| Route handler responsibility | Route handlers do all DB reads, then pass plain data to pure functions |
| Custom recipes | Phase 2 only — `recipe_type` field stubbed in model, no creation UI |
| Credentials | `.env` only — `COOKIDOO_EMAIL`, `COOKIDOO_PASSWORD` via `python-dotenv`; `.env` in `.gitignore`; bad credentials = startup crash (intentional) |

---

## Week plan scope

- **Planning window:** current ISO week + next ISO week only (2 weeks total)
- **Write enforcement:** `meal_plan.py` rejects writes outside the 2-week window
- **History retention:** old rows are never deleted — used by `suggestions.py` for diversity scoring
- **DB key:** `(iso_week TEXT, day INTEGER, meal INTEGER)` — iso_week format: `'2025-W22'`

---

## Database schemas

### `meal_plan` table

```sql
CREATE TABLE IF NOT EXISTS meal_plan (
  iso_week  TEXT    NOT NULL,   -- e.g. '2025-W22'
  day       INTEGER NOT NULL,   -- 0=Mon … 6=Sun
  meal      INTEGER NOT NULL,   -- 0=lunch, 1=dinner
  recipe_id TEXT,
  recipe_type TEXT DEFAULT 'cookidoo',  -- stub: 'cookidoo' | 'custom'
  assigned_at TEXT,             -- ISO timestamp, UTC always
  PRIMARY KEY (iso_week, day, meal)
);
```

### `recipes` table

```sql
CREATE TABLE IF NOT EXISTS recipes (
  id               TEXT PRIMARY KEY,
  name             TEXT NOT NULL,     -- always stored, even for unavailable recipes
  status           TEXT NOT NULL DEFAULT 'ok',  -- 'ok' | 'unavailable'
  collection_id    TEXT,              -- nullable
  cooking_time     INTEGER,           -- nullable for unavailable recipes
  servings         INTEGER,           -- nullable for unavailable recipes
  ingredients_json TEXT,              -- nullable; JSON array of ingredient objects
  raw_json         TEXT               -- nullable; full Cookidoo payload (debugging aid)
);
```

`name NOT NULL` is the only hard constraint — if a recipe fetch fails, name is stored and everything else is null. `raw_json` costs nothing to store and prevents re-fetching to diagnose parse failures.

---

## Suggestions scoring formula

```python
# score_recipe_by_pantry() → float in [0.0, 1.0]
coverage      = matched_pantry_ingredients / total_ingredients   # 0.0–1.0
recency_penalty = 0.3 if used_in_last_2_iso_weeks else 0.0
final_score   = max(0.0, coverage - recency_penalty)

# top_suggestions(pantry, max_time, n=10)
# 1. Filter by cooking_time <= max_time (hard filter, not penalty)
# 2. Score all remaining recipes
# 3. Return top-n sorted by final_score desc
```

- "Used in last 2 ISO weeks" = rows in `meal_plan` where `iso_week` is W-1 or W-2 relative to the current ISO week (completed weeks only — current week excluded)
- Recency SQL: `WHERE iso_week IN (strftime('%G-W%V','now','-7 days'), strftime('%G-W%V','now','-14 days'))`
- Ingredient matching: normalise both sides to lowercase, strip plurals, exact match only (Phase 1 — no fuzzy)
- Unit normalisation: **skipped in Phase 1** — known limitation: "200g flour" and "0.2kg flour" aggregate as two lines

---

## Cache refresh — polling design

```
POST /api/cache/refresh        → 202 Accepted, starts asyncio background task
GET  /api/cache/status         → { state: "idle"|"running"|"done"|"error",
                                   progress: { done: int, total: int },
                                   last_refreshed: str | null,
                                   error: str | null }
```

- Frontend polls `/api/cache/status` every 2 s while `state == "running"`
- `state` is held in a module-level dict in `recipe_cache.py` (no DB needed for transient state)
- 0.5 s throttle between Cookidoo detail requests
- First-run UX: show empty state + dismissible "No recipes cached — click Refresh" banner; do **not** block interaction

---

## Route map

```
GET  /api/weeks/current               → { current: "2026-W16", next: "2026-W17" }
GET  /api/recipes                     recipe_cache.get_all_recipes()
GET  /api/recipes/search?q=&max_time= recipe_cache.search_recipes(q, max_time)
GET  /api/recipes/{id}                recipe_cache.get_recipe_details(id)
POST /api/cache/refresh               → 202, background task
GET  /api/cache/status                → CacheStatus
GET  /api/plan?week=                  meal_plan.get_week(iso_week)  [default: current]
PUT  /api/plan/{iso_week}/{day}/{meal} meal_plan.set_slot(...)
DELETE /api/plan/{iso_week}/{day}/{meal} meal_plan.clear_slot(...)
GET  /api/pantry                      pantry.list_items()
POST /api/pantry                      pantry.add_item()
PUT  /api/pantry/{id}                 pantry.update_item()
DELETE /api/pantry/{id}               pantry.delete_item()
GET  /api/shopping-list?week=         → ShoppingList { items, unavailable_recipes: list[str] }
GET  /api/suggestions?max_time=       top_suggestions(pantry, max_time)  — excludes unavailable
POST /api/sync/calendar               cookidoo_client.push_week_to_calendar()
POST /api/sync/shopping               cookidoo_client.sync_shopping_list()
```

---

## Key functions

```python
# shopping.py
DEFAULT_SERVINGS = {0: 2, 1: 4}   # 0=lunch → 2 portions, 1=dinner → 4 portions

def scale_ingredients(ingredients: list[Ingredient], servings: int) -> list[Ingredient]: ...
def aggregate_ingredients(ingredient_lists: list[list[Ingredient]]) -> list[AggregatedIngredient]: ...
def build_shopping_list(
    week_plan: dict,           # {(iso_week, day, meal): recipe_id}
    pantry_items: list[PantryItem],
    recipe_cache: dict[str, RecipeDetails]  # injected — no DB handle
) -> ShoppingList: ...
# ShoppingList = { items: list[ShoppingItem], unavailable_recipes: list[str] }
# Unavailable recipes: include name in unavailable_recipes list, no ingredients
# servings derived from meal slot: DEFAULT_SERVINGS[meal]

# suggestions.py
def normalise_ingredient_name(name: str) -> str: ...          # lowercase, strip plural (≥4 chars rule)
def score_recipe_by_pantry(
    recipe: RecipeDetails,
    pantry: list[PantryItem],
    recent_recipe_ids: set[str]                                # passed in from DB query
) -> float: ...
def top_suggestions(
    pantry: list[PantryItem],
    all_recipes: list[RecipeDetails],   # pre-filtered: status='ok' only
    recent_recipe_ids: set[str],
    max_time: int | None = None,
    n: int = 10
) -> list[ScoredRecipe]: ...

# cookidoo_client.py — wraps cookidoo-api==0.16.0 (miaucl/cookidoo-api, aiohttp-based)
# Receives app.state.cookidoo (singleton). On CookidooAuthException: re-login once, then raise.
# Key methods: get_managed_collections(), get_recipe_details(),
#              add_recipes_to_calendar(), add_ingredient_items_for_recipes(),
#              edit_ingredient_items_ownership(), clear_shopping_list()

# recipe_cache.py
async def refresh_cache(client: Cookidoo) -> None: ...  # ONLY function with network I/O
# On get_recipe_details() failure: store {id, name, status='unavailable'}, continue
async def get_all_recipes() -> list[RecipeSummary]: ...
async def get_recipe_details(recipe_id: str) -> RecipeDetails | None: ...
async def search_recipes(q: str, max_time: int | None) -> list[RecipeSummary]: ...

# main.py lifespan — nesting order: http (outer) → db (inner); both closed on shutdown
# SINGLE-WORKER ONLY — app.state.cookidoo, app.state.http, _cache_status are process-local
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiohttp.ClientSession() as session:
        app.state.http = session
        app.state.cookidoo = Cookidoo(session, CookidooConfig(...))
        await app.state.cookidoo.login()       # startup crash on bad credentials = intentional
        async with aiosqlite.connect(DB_PATH) as db:
            app.state.db = db
            await init_schema(db)
            yield
```

---

## Repo structure

```
thermomix-planner/
├── CLAUDE.md
├── CLAUDE.docx
├── .env                    # not committed
├── .env.example            # COOKIDOO_EMAIL=, COOKIDOO_PASSWORD= (bad credentials = startup crash)
├── .gitignore              # includes .env, db/, __pycache__/
├── requirements.txt        # runtime + test deps in one file
├── pytest.ini              # asyncio_mode=auto, testpaths=tests
├── backend/
│   ├── main.py             # FastAPI: routes, CORS, lifespan (http→cookidoo→db nesting order)
│   ├── db.py               # Schema owner: all CREATE TABLE IF NOT EXISTS, aiosqlite pool
│   ├── meal_plan.py        # CRUD for meal_plan table; enforces 2-week write window
│   ├── cookidoo_client.py  # Wraps cookidoo-api==0.16.0; uses app.state.cookidoo singleton
│   ├── recipe_cache.py     # DB queries (pure) + refresh_cache() (network); cache status dict
│   ├── shopping.py         # Pure: scale, aggregate, build_shopping_list; DEFAULT_SERVINGS
│   ├── suggestions.py      # Pure: normalise, score, top_suggestions (status='ok' only)
│   ├── pantry.py           # CRUD for pantry table
│   └── models.py           # All Pydantic models; RecipeStatus literal; ShoppingList type
├── tests/
│   ├── conftest.py         # pytest-asyncio mode, shared fixture dicts; no CookidooClient
│   ├── test_shopping.py    # Includes: unavailable recipe → name in unavailable_recipes list
│   └── test_suggestions.py # Includes: recency penalty; score clamp; unavailable filtered out
├── frontend/
│   ├── index.html
│   ├── vite.config.ts      # proxy: /api → localhost:8000
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx         # Tab shell; focusedSlot; viewingWeek (fetched from /api/weeks/current)
│   │   ├── tokens.css      # Design tokens only
│   │   ├── components/
│   │   │   ├── WeekGrid.tsx        # week param; calls GET /api/plan?week=
│   │   │   ├── MealCell.tsx        # onClick → set focusedSlot; mode: assign|replace
│   │   │   ├── WeekNav.tsx         # Prev/Next; initial week from GET /api/weeks/current
│   │   │   ├── RecipePicker.tsx    # Right panel on Plan tab; visible only when focusedSlot != null
│   │   │   ├── RecipeCard.tsx      # Shared: name, score badge, time badge, unavailable warning
│   │   │   ├── SuggestionsTab.tsx  # Read-only ranked list; no slot interaction
│   │   │   ├── CacheStatus.tsx     # Banner + progress bar; polls /api/cache/status
│   │   │   ├── PantryManager.tsx   # CRUD + bulk import textarea
│   │   │   └── ShoppingList.tsx    # items + unavailable_recipes warning callout; sync button
│   │   └── api.ts                  # Typed fetch wrappers for all endpoints
├── db/                     # Auto-created on first run (gitignored)
│   └── planner.db
└── docker-compose.yml      # Phase 2 stub — leave empty
```

---

## Frontend state shape

```typescript
// App.tsx top-level state
type FocusedSlot = { isoWeek: string; day: number; meal: number; mode: 'assign' | 'replace' } | null;

interface AppState {
  activeTab: 'plan' | 'pantry' | 'shopping' | 'suggestions';
  focusedSlot: FocusedSlot;    // null → RecipePicker panel hidden
  viewingWeek: string;         // ISO week string; initialised from GET /api/weeks/current on mount
}

// focusedSlot resets to null on tab change
// MealCell: empty cell → mode='assign'; filled cell → mode='replace'
// WeekNav clamps: cannot navigate before current week or beyond current+1
```

---

## Implementation order

0. Project scaffold — `.gitignore`, `.env.example`, `requirements.txt`, `pytest.ini`, directory stubs
1. `models.py` — all Pydantic types
2. `shopping.py` — pure functions + `DEFAULT_SERVINGS`
3. `suggestions.py` — pure functions (include recency param from day 1)
4. `tests/` — `conftest.py` + `test_shopping.py` + `test_suggestions.py`
5. `db.py` — schema, aiosqlite pool
6. `pantry.py` — CRUD
7. `meal_plan.py` — CRUD + 2-week write enforcement + `get_recent_ids()`
8. `cookidoo_client.py` — aiohttp wrapper (type reference; can't integration-test yet)
9. `recipe_cache.py` — DB query functions + `refresh_cache()` in one sitting (cookidoo_client type now available)
10. `main.py` — all routes + CORS + lifespan (`app.state.db` + `app.state.http`)
11. Manual integration test — refresh against real Cookidoo; verify DB + suggestions pipeline
12. Frontend: Vite scaffold → `api.ts` → `tokens.css` → `App.tsx` → `WeekGrid`+`WeekNav` → `RecipePicker`+`RecipeCard`+`CacheStatus` → Suggestions tab → `PantryManager` → `ShoppingList`

---

## Design language

- Single `tokens.css` — no CSS framework, no Tailwind
- No Redux, no router library (tabs via `useState`)
- Inherit nothing visually from prior projects — greenfield aesthetic
- Suggested palette: warm off-white background, deep teal primary, amber accent for score badges

---

## Known Phase 1 limitations (do not fix, do document)

- Unit normalisation skipped: "200g flour" and "0.2kg flour" produce two shopping list lines
- Custom recipe creation: `recipe_type='custom'` field exists in schema; no creation UI
- Ingredient fuzzy matching: exact normalised string match only

---

## References

- **cookidoo-api** — `pip install cookidoo-api==0.16.0` · PyPI: https://pypi.org/project/cookidoo-api/ · GitHub: https://github.com/miaucl/cookidoo-api · Docs: https://miaucl.github.io/cookidoo-api/reference/ · Requires Python ≥ 3.12 · aiohttp-based · `Cookidoo(session, cfg)` constructor
- FastAPI docs: https://fastapi.tiangolo.com
- aiosqlite: https://aiosqlite.omnilib.dev
- Vite proxy config: https://vitejs.dev/config/server-options#server-proxy

---
*Author: teowaits · April 2026 · Private*
