# HANDOFF — Weekly Thermomix Planner
*Generated: April 2026 · Author: teowaits · Resume from: Step 11 (frontend)*

---

## 1. Project identity

**Repo handle:** `thermomix-planner`  
**GitHub user:** `teowaits`  
**Local path (MacBook Neo):** inferred as `~/Documents/Claude/thermomix-planner/`  
**Stack:** Python 3.12 + FastAPI + aiosqlite + cookidoo-api + rapidfuzz · Frontend TBD by Claude Code  
**License:** MIT  
**Phase:** 1 — local-only, localhost, no auth, no Docker  

---

## 2. What this project is

A local-first web app for planning weekly lunches and dinners cooked via Thermomix TM5 + Cookidoo.

Core workflow:
1. User picks recipes from their Cookidoo library for each meal slot (Mon–Sun × Lunch/Dinner)
2. App computes a scaled, pantry-subtracted shopping list
3. User pushes the week's recipes to the Cookidoo calendar → TM5 picks them up for guided cooking

**Phase 2 (future):** Docker-compose the same app onto a Synology Beestation (DiskStation Manager / Container Manager) for private household access outside the home.

---

## 3. Build status

### Completed steps

| Step | Module | Status | Notes |
|---|---|---|---|
| 1–7 | Project scaffold, models, DB schema | ✅ Done | |
| 8 | `backend/meal_plan.py` | ✅ Done | |
| 9 | `backend/recipe_cache.py` | ✅ Done | Includes `get_all_recipe_details()` added pre-Step 10 |
| 10 | `backend/main.py` | ✅ Done | All 17 routes, lifespan, get_db dependency |
| — | `backend/pantry.py` | ✅ Done | |
| — | `backend/shopping.py` | ✅ Done | |
| — | `backend/suggestions.py` | ✅ Done | |
| — | `backend/cookidoo_client.py` | ✅ Done | |
| — | `backend/models.py` | ✅ Done | |
| — | `tests/` | ✅ 107/107 passing | See coverage gaps in §9 |
| Phase 2, Item 1a | Preposition stripping | ✅ Done | backend + 15 tests |
| Phase 2, Item 1b | Fuzzy matching WRatio ≥ 85 | ✅ Done | backend + 7 tests |
| Phase 2, Item 1c | Unit normalisation, `check_units` flag | ✅ Done | backend + 6 tests |
| Phase 2, Item 2 | Custom recipe creation | ✅ Done | backend + frontend + 7 tests |
| Phase 2, Item 3 | Custom recipe badge | ✅ Done | frontend, included in Item 2 |
| Phase 2, Item 4 | Single-user Docker / NAS deployment | ✅ Done | 107 tests passing; local smoke test passed April 2026 |
| Display fix | Ingredient name preposition stripping at render | ✅ Done | frontend `utils/normalise.ts`, no backend change |
| Recipe hover tooltip | `MealCell.tsx` + `MealCell.css` | ✅ Done | CSS `:hover` on name wrapper shows cooking time + up to 10 ingredients. `pointer-events:none`. |
| Drag-and-drop slots | `WeekGrid.tsx`, `MealCell.tsx`, `App.tsx` | ✅ Done | `dragSourceRef` (ref not state). Move to empty slot; swap with filled slot. Both backed by API calls. |
| History tab | `HistoryTab.tsx` + `GET /api/plan/history` | ✅ Done | Groups by ISO week DESC. Shows day, meal, recipe name, cooking time. |

### Next step

Multilingual ingredient matching (synonyms.py + Claude API fallback).  
Prompt ready — see §14.

---

## 4. Architecture

```
thermomix-planner/
├── CLAUDE.md                  # lean spec for Claude Code (source of truth)
├── CLAUDE.docx                # full reasoning doc for humans
├── .env.example               # EMAIL, PASSWORD, LOCALE (e.g. en-GB)
├── backend/
│   ├── main.py                # FastAPI app, 17 routes, lifespan, get_db dep
│   ├── cookidoo_client.py     # async wrapper around cookidoo-api
│   ├── recipe_cache.py        # SQLite cache + _cache_status in-process dict
│   ├── shopping.py            # build_shopping_list(), scale_ingredients()
│   ├── suggestions.py         # score_recipe_by_pantry(), top_suggestions()
│   ├── pantry.py              # CRUD for pantry items
│   ├── meal_plan.py           # CRUD for weekly plan slots
│   └── models.py              # Pydantic: WeekSlot, PantryItem, ShoppingItem, etc.
├── db/
│   └── planner.db             # SQLite, auto-created on first run
├── tests/                     # pytest-asyncio, 67 tests passing
├── requirements.txt
└── docker-compose.yml         # Phase 2 only, not yet written
```

### Layer summary

| Layer | Technology | Scope |
|---|---|---|
| Backend | FastAPI + aiosqlite | All business logic, DB, Cookidoo API calls |
| Cookidoo integration | cookidoo-api (pip, unofficial) | Recipe details, calendar sync, shopping list |
| Local DB | SQLite via aiosqlite | Recipes cache, pantry, week plan |
| Fuzzy matching | rapidfuzz WRatio ≥ 0.8 | Pantry → ingredient matching |
| Frontend | TBD (Step 11) | Single-page, 4 tabs |

---

## 5. All 17 API routes

```
GET    /api/weeks/current                     → {"current": "2026-W16", "next": "2026-W17"}
GET    /api/recipes                           → list[RecipeSummary]
GET    /api/recipes/search?q=&max_time=       → list[RecipeSummary]   ← MUST be before /{id}
GET    /api/recipes/{id}                      → RecipeDetails | 404
POST   /api/cache/refresh                     → 202 | 409
GET    /api/cache/status                      → CacheStatus
GET    /api/plan?week=                        → list[WeekSlot]
PUT    /api/plan/{iso_week}/{day}/{meal}       → WeekSlot | 400 | 404
DELETE /api/plan/{iso_week}/{day}/{meal}       → 204 | 404
GET    /api/plan/history                      → list[HistorySlot] (past weeks only, joined with recipe names, DESC)
GET    /api/pantry                            → list[PantryItem]
POST   /api/pantry                            → PantryItem
PUT    /api/pantry/{id}                       → PantryItem | 404
DELETE /api/pantry/{id}                       → 204 | 404
GET    /api/shopping-list?week=               → ShoppingList
GET    /api/suggestions?max_time=             → list[ScoredRecipe]
POST   /api/sync/calendar                     → 200 | 503
POST   /api/sync/shopping                     → 200 | 503
```

**Path param types:** `day: str` (e.g. `"Mon"`), `meal: str` (`"lunch"` | `"dinner"`). Both are strings — not int. Validate inside handler, raise 400 on invalid value.

---

## 6. All confirmed architectural decisions

### Data model
```python
WeekSlot = {
    "day": "Mon" | "Tue" | "Wed" | "Thu" | "Fri" | "Sat" | "Sun",
    "meal": "lunch" | "dinner",
    "recipe_id": str | None,
    "recipe_type": "cookidoo" | "custom",   # drives which calendar API call to use
    "servings": int,                         # default: lunch=2, dinner=4, editable per slot
}

PantryItem = {
    "id": str,            # local UUID
    "name": str,
    "normalised_name": str,  # lowercase, stored for fuzzy match
    "quantity": float | None,
    "unit": str | None,
}
```

### Meal defaults
- Lunch: 2 servings (editable per slot)
- Dinner: 4 servings (editable per slot)
- Global defaults editable in Settings; per-slot override always available

### DB connection pattern
- **NOT** a persistent connection on `app.state`
- Per-request dependency only:
```python
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(DB_PATH) as db:
        yield db
```
- Background refresh task opens its own connection independently:
```python
async def _run_refresh(cookidoo: Cookidoo) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await recipe_cache.refresh_cache(db, cookidoo)
```

### Cache refresh
- `asyncio.create_task()` — NOT FastAPI `BackgroundTasks`
- Task reference stored on `app.state.refresh_task`
- 409 if task exists and `not task.done()` → body: `{"state": "running", "progress": {"done": N, "total": M}}`
- Single DB transaction (atomic): one `db.commit()` at end; explicit `db.rollback()` in except before re-raising
- Call `count_managed_collections()` + `count_custom_collections()` before loop → set total in `_cache_status` upfront
- Paginate both managed AND custom collections (loop until empty page)
- 0.5s sleep between recipe detail fetches (rate limit)
- Per-recipe failure: store `{id, status='unavailable'}`, continue
- `recipe_type = "cookidoo" | "custom"` stored per recipe during upsert

### Ingredient parsing
- Parse `description` string (e.g. `"200 g"`) eagerly during cache fill
- Store enriched JSON: `[{name, description, quantity_float, unit_str}, ...]`
- Regex: `r"^([\d.,]+)\s*([a-zA-Zµ]+)?"` — handle None/empty gracefully
- No re-parsing on read

### Shopping list
- Aggregate across all week slots, scaled per slot's servings
- `scaled_qty = default_qty × (slot.servings / recipe.default_servings)`
- Pantry subtraction via rapidfuzz WRatio ≥ 0.8 on normalised names
- If `get_recipe_details` returns None for a slot's recipe_id: add that `recipe_id` to `unavailable_recipes: list[str]` in the response — do NOT silently skip
- Frontend shows warning banner for unavailable recipes

### Suggestion engine
- `score = matched_ingredients / total_ingredients` (0.0–1.0)
- Top 10, score > 0, `max_time` filter applies
- Phase 2 upgrade path: Claude API for ambiguous matches (0.6–0.8 range)

### Sync
- `CookidooAuthException` → 503
- All other exceptions → 500 (propagate)
- Calendar sync: `add_recipes_to_calendar()` for cookidoo type, `add_custom_recipes_to_calendar()` for custom type

### CORS
- Phase 1: `allow_origins=["*"]`
- Phase 2: tighten to specific origin, add HTTP Basic Auth via nginx

### Frontend (Step 11 — decision pending)
- Claude Code chooses React (Vite) vs plain HTML
- Lean toward whichever avoids unnecessary build complexity for a household tool
- Reactive state for 14 slots + live shopping list updates favours React
- Zero build tooling favours plain HTML + `<script type="module">`

---

## 7. Frontend spec (Step 11 input)

### Tab layout

| Tab | Primary content | Key interactions |
|---|---|---|
| Week plan | 7×2 meal grid (Mon–Sun × Lunch/Dinner) | Click slot → open recipe picker; adjust servings ±; clear slot; "Send to Thermomix" button |
| Recipe picker | Collection browser + search toggle | Time filter; pantry match score badge; click to assign to focused slot |
| Pantry | Ingredient list with qty/unit | Add / edit / delete; bulk import (newline-separated); clear all |
| Shopping list | Aggregated, scaled, owned-flagged list | Toggle show/hide owned; "Sync to Cookidoo" button; print view; warning banner if unavailable_recipes non-empty |
| History | Past weeks grouped by ISO week, row per meal: day · meal label · recipe name · cooking time | Read-only. Weeks shown in DESC order. |

### UX enhancements (added post-Phase 2)

- **Recipe hover tooltip:** hovering a filled `MealCell` shows a dark card with cooking time and up to 10 ingredients ("+N more" if longer). Rendered only when recipe details are loaded. `pointer-events:none` — does not block clicks on the name button.
- **Drag-and-drop:** filled cells are draggable. Drop onto empty slot = move; drop onto filled slot = swap. Both backed by `PUT`/`DELETE` API calls. `dragSourceRef` is a ref (not state) to avoid re-renders during drag. `dragOverKey` local state in `WeekGrid` drives the drop-target highlight.

### Meal slot card anatomy
- Recipe name (truncated to 2 lines)
- Serving badge: "2 people" with − / + buttons
- Pantry match score: e.g. "✔ 80% from pantry" in green
- Clear button (top-right, small)
- Empty state: "+ Add recipe" placeholder, grey dashed border

### Design tokens

| Token | Value |
|---|---|
| Accent | `#1a7f64` (Thermomix green adjacency) |
| Surface | `#f8f9fa` |
| Border | `#dee2e6` |
| Warning | `#f59e0b` |
| Text primary | `#212529` |
| Font | System UI stack |
| Min tap target | 44px |

### Cache status polling
- Poll `GET /api/cache/status` every 2s while `state == "running"`
- Stop polling when `state == "done"` or `state == "error"`
- No WebSocket

---

## 8. Key API constraints (must not be forgotten)

| Constraint | Implication |
|---|---|
| No recipe search by ingredient in Cookidoo API | Suggestion engine is 100% local; limited to user's saved collections |
| No full catalogue browse | Users must save recipes in Cookidoo first |
| Unofficial API (reverse-engineered) | May break without notice; monitor miaucl/cookidoo-api releases |
| Shopping list API uses unscaled quantities | Display scaled list locally; Cookidoo sync is best-effort |
| `add_recipes_to_calendar()` is serving-agnostic | Sends recipe ID only; all quantity scaling is local |
| TM5 vs TM6 behaviour unconfirmed | Verify calendar sync on actual TM5 before building Phase 4 |

---

## 9. Test coverage status

| Module | Coverage | Notes |
|---|---|---|
| `meal_plan.py` | ✅ Covered | In-memory DB harness pattern established here |
| `shopping.py` | ✅ Covered | Pure functions, well tested |
| `suggestions.py` | ✅ Covered | |
| `models.py` | ✅ Covered | |
| `recipe_cache.py` | ⚠️ Partial | DB read functions untested; `_parse_description` tested inline only |
| `pantry.py` | ❌ No tests | All four CRUD functions uncovered |
| `main.py` | ❌ No tests | All 17 routes uncovered |
| `cookidoo_client.py` | 🔄 Deferred | `_iso_week_day_to_date` and owned-item matching are the two testable units without network |

**Agreed policy:** Route tests and DB tests deferred until a bug surfaces during manual integration. Manual integration against live Cookidoo account is the gate for Step 11 sign-off.

**Known limitation:** Unhandled exception in `_run_refresh` after `state='error'` is set is logged via `logger.exception()` but `app.state.refresh_task.exception()` is never checked. Acceptable for Phase 1.

**Phase 1 known limitation — ingredient name prepositions:**
Cookidoo ingredient names carry language prepositions from the `description` field ("40 g de pan" → name stored as "de pan", not "pan"). Exact pantry matching requires the user to add the prefixed form. Affects Spanish ("de/del/de la") and Italian ("di/del/della/d'") recipes. Phase 2 fix: strip these prefixes inside `normalise_ingredient_name()` in `suggestions.py`, or adopt fuzzy matching (WRatio ≥ 0.8 already mentioned in HANDOFF §4).

**ISO week calendar arithmetic — not a bug:**
When syncing the current week (e.g. 2026-W16, tested 2026-04-16 Thursday), `_iso_week_day_to_date("2026-W16", 0)` correctly returns 2026-04-13 (Monday of W16, which is in the past by mid-week). This is correct ISO 8601 behaviour. If today is Thursday and you sync "this week Monday", the calendar entry lands on the already-passed Monday. Next Monday (April 20) is W17. `date.fromisocalendar(year, week, weekday)` verified correct.

---

## 10. Inline Pydantic models (in main.py only, not in models.py)

```python
class SlotBody(BaseModel):
    recipe_id: str

class PantryItemBody(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None
```

---

## 11. SQLite schema (reference)

```sql
recipes(
    id TEXT PRIMARY KEY,
    title TEXT,
    total_time INTEGER,          -- minutes
    default_servings INTEGER,
    ingredients JSON,            -- [{name, description, quantity_float, unit_str}, ...]
    collection_id TEXT,
    recipe_type TEXT,            -- "cookidoo" | "custom"
    status TEXT,                 -- "ok" | "unavailable"
    cached_at TIMESTAMP
)

collections(
    id TEXT PRIMARY KEY,
    title TEXT,
    type TEXT,                   -- "managed" | "custom"
    cached_at TIMESTAMP
)

week_plan(
    day TEXT,                    -- "Mon".."Sun"
    meal TEXT,                   -- "lunch" | "dinner"
    iso_week TEXT,               -- "2026-W16"
    recipe_id TEXT,
    recipe_type TEXT,            -- "cookidoo" | "custom"
    servings INTEGER,
    PRIMARY KEY(iso_week, day, meal)
)

pantry(
    id TEXT PRIMARY KEY,         -- UUID
    name TEXT,
    normalised_name TEXT,        -- lowercase, used for fuzzy match
    quantity REAL,
    unit TEXT
)
```

---

## 12. Phase 2 NAS deployment — ✅ Done (April 2026)

- Same app wrapped in Docker Compose: backend + nginx + named volume for `db/`
- nginx: proxy `/api/` → `backend:8000`; serve frontend static files; `auth_basic` block
- Auth: `BASIC_AUTH_USER` / `BASIC_AUTH_PASS` in `.env`; nginx reads from `.htpasswd`
- Synology DSM: upload via Container Manager; mount volume to Beestation folder
- External access: Synology VPN Server (OpenVPN) — do NOT expose port directly
- CORS: tightened to specific origin via `CORS_ORIGINS` env var

---

## NAS Deployment — Synology Beestation

Tested on: DiskStation Manager 7.x, Container Manager V2

**Prerequisites:**
- Docker Desktop installed and tested locally (smoke test passed)
- Project directory copied to NAS via scp or Synology Drive

**Steps:**

1. Copy project to NAS:
   ```
   scp -r ~/Documents/Claude/thermomix-planner nas-user@nas-ip:/volume1/docker/
   ```
2. SSH into NAS or open Container Manager terminal
3. Copy `.env.docker.example` to `.env` and fill in real credentials:
   - `COOKIDOO_EMAIL`, `COOKIDOO_PASSWORD` — your Cookidoo account
   - `COOKIDOO_COUNTRY=it`, `COOKIDOO_LANGUAGE=it-IT`
   - `CORS_ORIGINS=http://<NAS-IP>:8080`
   - `APP_PORT=8080`
   - `BASIC_AUTH_USER`, `BASIC_AUTH_PASS` — shared household password
4. In Container Manager → Project → Create → select `docker-compose.yml`
5. DSM creates and manages the `db_data` named volume automatically
6. Access at `http://<NAS-IP>:8080` on local network
7. On first run: log in, trigger cache refresh (~6 min), verify 1031 recipes cached

**External access:**
- Use Synology VPN Server (OpenVPN) to reach home network securely
- Do NOT expose port 8080 directly to the internet
- HTTPS termination handled by home router or VPN, not by this app

**Updating the app:**
- Pull latest code to NAS
- In Container Manager: stop project → rebuild → start
- `db_data` volume is preserved across rebuilds — no data loss
- If DB schema changes: run migration manually or wipe `db_data` and re-cache (recipes re-fetch from Cookidoo; pantry and meal plan will be lost)

**Known working configuration:**
- `python:3.12-slim` backend
- `node:20-alpine` + `nginx:alpine` frontend
- `openssl passwd -apr1` for `.htpasswd` generation (no extra packages)
- `proxy_read_timeout 600s` for cache refresh

---

## Phase 2 — Completion summary

All Phase 2 items complete as of April 2026:

| Item | Description | Status |
|---|---|---|
| 1a | Preposition stripping (backend + 15 tests) | ✅ Done |
| 1b | Fuzzy matching threshold WRatio ≥ 85 (backend + 7 tests) | ✅ Done |
| 1c | Unit normalisation with `check_units` flag (backend + 6 tests) | ✅ Done |
| 2 | Custom recipe creation (backend + frontend + 7 tests) | ✅ Done |
| 3 | Custom recipe badge (frontend, included in Item 2) | ✅ Done |
| 4 | Single-user Docker, NAS deployment (107 tests, smoke tested) | ✅ Done |
| Display fix | Ingredient name preposition stripping at render time (`frontend/utils/normalise.ts`, no backend change) | ✅ Done |

**Total tests: 107 passing.**

Deferred to Phase 3: ingredient substitutability (see §15).  
Deferred: multi-user Docker, suggestions tab improvements, PWA.

---

## 13. References

- cookidoo-api docs: https://miaucl.github.io/cookidoo-api/
- cookidoo-api reference: https://miaucl.github.io/cookidoo-api/reference/
- Prior art (MCP + Gemini): https://github.com/alexandrepa/mcp-cookidoo/
- rapidfuzz: https://github.com/maxbachmann/RapidFuzz
- FastAPI: https://fastapi.tiangolo.com/
- Synology Container Manager: https://kb.synology.com/en-global/DSM/help/ContainerManager/

---

## 14. Step 11 kickoff prompt

Paste this at the start of the next Claude Code session:

```
Read CLAUDE.md before doing anything else. Then read backend/ and tests/.

I'm building the Weekly Thermomix Planner. Steps 1–10 are complete:
all backend modules, 17 FastAPI routes, SQLite schema, and 67 passing tests.
Full spec is in CLAUDE.md. Full reasoning is in CLAUDE.docx. This handoff
document is HANDOFF.md.

Proceeding to Step 11: frontend.

Your first task is to decide: React (Vite) or plain HTML + vanilla JS?
State your choice with a one-paragraph justification before writing any code.
Criteria: this is a household tool, localhost-only in Phase 1, 4 tabs,
14 meal slots with reactive serving controls, live shopping list, and a
polling cache-status bar. Avoid unnecessary build complexity.

Backend is running on localhost:8000. All 17 routes are available.
Design tokens, tab layout, and meal slot card anatomy are in CLAUDE.md §Design language
and §App structure, and in HANDOFF.md §7.

Before writing any code, I want a plan. Specifically:

1. Frontend choice (React/Vite or plain HTML) with justification
2. Proposed file/component breakdown
3. Implementation order — what do you build first?
4. Any ambiguities or gaps you want clarified before starting

Constraints:
- Poll GET /api/cache/status every 2s while state == "running"; stop on "done"/"error"
- Meal slot day/meal path params are strings ("Mon", "lunch") — not integers
- Shopping list response includes unavailable_recipes: list[str] — show warning banner
- Min tap target 44px (kitchen use)
- Accent colour #1a7f64, system UI font stack, no custom fonts

Do not start coding yet. Just the plan.
```

---

---

## 15. Phase 3 — Future items

### Multilingual ingredient matching *(prompt ready, not yet coded)*

**Problem:** Cookidoo ingredient names are multilingual (Italian, Spanish, English). Fuzzy matching handles spelling variants but not cross-language synonyms (e.g. "pomodori" ↔ "tomatoes").

**Solution:** A two-tier lookup table. Tier 1: static JSON dictionary of known synonym groups. Tier 2: Claude API fallback for unknown terms, result cached permanently in SQLite.

**Files:**
- `backend/synonyms.py` — new module; `resolve(name) → canonical_name`
- `backend/db.py` — new `ingredient_synonyms` table migration
- `backend/suggestions.py` — pass resolved canonical names into `score_recipe_by_pantry()`
- `backend/shopping.py` — same resolution in the owned-flag step

**New SQLite table:**
```sql
CREATE TABLE IF NOT EXISTS ingredient_synonyms (
    normalised_name TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    source          TEXT NOT NULL,   -- 'dictionary' | 'claude_api' | 'user'
    resolved_at     TEXT             -- ISO timestamp, UTC
);
```

**Static dictionary:** `backend/data/ingredient_synonyms.json`  
103 canonical groups · 857 terms · languages: en / it / es_es / es_mx

**Claude API fallback:**
- Called once per unknown ingredient; result cached in `ingredient_synonyms` with `source='claude_api'`
- Requires `ANTHROPIC_API_KEY` in `.env` — if absent: passthrough (no crash, no resolution)
- Warm cache: runs after every full Cookidoo cache refresh to pre-resolve all unique ingredient names; daily use never hits the API

**New route:** `GET /api/synonyms/cache` → operational transparency (list of resolved terms + sources)

**Dependency note:** Ingredient substitutability (item below) depends on this feature being complete first.

---

### Ingredient substitutability (user-managed)

**Problem:** Fuzzy matching handles the same ingredient expressed differently
(e.g. "pomodoro" vs "pomodori"). It does not handle genuinely distinct
ingredients that are interchangeable in practice (e.g. "peperoni rossi"
vs "peperoni verdi", "farina tipo 0" vs "farina manitoba").

**Solution:** A user-managed substitution table in SQLite — pairs of
normalised ingredient names the user has declared interchangeable.
Pantry matching checks this table before concluding no match.

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS substitutes (
    id     TEXT PRIMARY KEY,
    name_a TEXT NOT NULL,   -- normalised ingredient name
    name_b TEXT NOT NULL    -- normalised ingredient name
);
```

**Backend changes:**
- `db.py` — add `substitutes` table migration
- `suggestions.py` — `score_recipe_by_pantry()` receives an additional
  `substitutes: set[tuple[str, str]]` parameter; a pantry item matches an
  ingredient if the fuzzy check passes OR if the (ingredient, pantry_name)
  pair appears in the substitutes set (in either order)
- `shopping.py` — same substitutes check in the owned-flag step
- `main.py` — new routes:
  ```
  GET    /api/substitutes           → list[Substitute]
  POST   /api/substitutes           → Substitute (201)
  DELETE /api/substitutes/{id}      → 204 | 404
  ```

**Frontend changes:** A "Substitutes" section in the Pantry tab — add a
pair (two autocomplete inputs from the cached recipe names) and remove
existing pairs. No edit — delete and re-add.

**Scope:** Backend (new table + migration + matching logic) + frontend
(CRUD UI in Pantry tab). No AI or external data needed.

---

*HANDOFF.md · teowaits · April 2026 · MIT*
