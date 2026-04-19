// api.ts — typed fetch wrappers for all 17 backend routes.
// All response shapes mirror backend/models.py exactly.

const BASE = '/api'

// ---------------------------------------------------------------------------
// Response types
// ---------------------------------------------------------------------------

export interface Ingredient {
  name: string
  quantity: number | null
  unit: string | null
}

export interface RecipeSummary {
  id: string
  name: string
  status: 'ok' | 'unavailable'
  collection_id: string | null
  cooking_time: number | null  // minutes
  recipe_type: string          // 'cookidoo' | 'custom' | 'local_custom'
}

export interface RecipeDetails extends RecipeSummary {
  servings: number | null
  ingredients: Ingredient[]
  source_url: string | null
}

export interface CustomRecipeBody {
  name: string
  servings: number | null
  cooking_time: number | null
  ingredients: Ingredient[]
  source_url: string | null
}

export interface WeekSlot {
  iso_week: string  // e.g. '2026-W16'
  day: number       // 0=Mon … 6=Sun
  meal: number      // 0=lunch, 1=dinner
  recipe_id: string | null
  recipe_type: string
  assigned_at: string | null
}

export interface PantryItem {
  id: string
  name: string
  quantity: number | null
  unit: string | null
}

export interface ShoppingItem {
  name: string
  quantity: number | null
  unit: string | null
  owned: boolean
  recipe_sources: string[]
}

export interface ShoppingList {
  items: ShoppingItem[]
  unavailable_recipes: string[]
}

export interface ScoredRecipe {
  recipe: RecipeDetails
  score: number  // 0.0–1.0
}

export interface CacheStatus {
  state: 'idle' | 'running' | 'done' | 'error'
  progress: { done: number; total: number }
  last_refreshed: string | null
  error: string | null
  recipe_count: number       // ok-status recipes in DB; 0 after server restart until first fetch
  unavailable_count: number  // recipes whose detail fetch failed during last refresh
}

export interface WeeksResponse {
  current: string
  next: string
}

// ---------------------------------------------------------------------------
// Client-side scoring — mirrors suggestions.py normalisation + fuzzy matching
// ---------------------------------------------------------------------------

// Longest-first: compound forms must match before their prefixes. Mirrors PREPOSITIONS in suggestions.py.
const PREPOSITIONS = [
  "dell'", "d'",
  'de la ', 'de las ', 'de los ',
  'delle ', 'della ', 'dello ', 'degli ', 'dei ',
  'del ', 'di ', 'de ',
]

/** Normalise an ingredient name for pantry matching. Mirrors suggestions.py. */
export function normaliseIngredientName(name: string): string {
  let n = name.trim().toLowerCase()
  for (const prep of PREPOSITIONS) {
    if (n.startsWith(prep)) {
      const candidate = n.slice(prep.length)
      if (candidate.trim()) { n = candidate; break }
    }
  }
  if (n.endsWith('s') && n.length >= 4) {
    const candidate = n.slice(0, -1)
    if (candidate.length >= 3) return candidate
  }
  return n
}

/** Levenshtein ratio in [0, 1] — approximates rapidfuzz WRatio for short strings. */
function _levenshteinRatio(a: string, b: string): number {
  if (a === b) return 1
  const m = a.length, n = b.length
  if (m === 0 || n === 0) return 0
  const dp: number[] = Array(n + 1).fill(0).map((_, j) => j)
  for (let i = 1; i <= m; i++) {
    let prev = dp[0]
    dp[0] = i
    for (let j = 1; j <= n; j++) {
      const temp = dp[j]
      dp[j] = a[i - 1] === b[j - 1]
        ? prev
        : 1 + Math.min(prev, dp[j], dp[j - 1])
      prev = temp
    }
  }
  return 1 - dp[n] / Math.max(m, n)
}

const FUZZY_THRESHOLD = 0.85

/** Returns true if ingredient name fuzzy-matches any pantry name. Mirrors score_recipe_by_pantry(). */
function _fuzzyMatch(ingredient: string, pantryNames: string[]): boolean {
  for (const p of pantryNames) {
    if (ingredient === p) return true
    // Substring check handles qualifiers ("zucchero" ⊂ "zucchero a velo")
    if (ingredient.includes(p) || p.includes(ingredient)) return true
    if (_levenshteinRatio(ingredient, p) >= FUZZY_THRESHOLD) return true
  }
  return false
}

/** Score a recipe against the current pantry (0.0–1.0).
 *  Mirrors backend score_recipe_by_pantry() without the recency penalty
 *  (recency is a backend-only concept; frontend shows raw coverage).
 */
export function scoreRecipe(recipe: RecipeDetails, pantryItems: PantryItem[]): number {
  if (recipe.ingredients.length === 0) return 0
  const pantryNames = pantryItems.map(p => normaliseIngredientName(p.name))
  const matched = recipe.ingredients.filter(
    ing => _fuzzyMatch(normaliseIngredientName(ing.name), pantryNames)
  ).length
  return matched / recipe.ingredients.length
}

// ---------------------------------------------------------------------------
// ISO week helpers
// ---------------------------------------------------------------------------

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
export type DayName = (typeof DAY_NAMES)[number]
export const MEAL_NAMES = ['lunch', 'dinner'] as const
export type MealName = (typeof MEAL_NAMES)[number]

/** Parse '2026-W16' → { year: 2026, week: 16 } */
function parseIsoWeek(isoWeek: string): { year: number; week: number } {
  const [yearStr, weekStr] = isoWeek.split('-W')
  return { year: parseInt(yearStr!, 10), week: parseInt(weekStr!, 10) }
}

/** date.fromisocalendar equivalent: ISO week + 0-based day → Date.
 *  Mirrors _iso_week_day_to_date() in cookidoo_client.py.
 */
export function isoWeekDayToDate(isoWeek: string, day: number): Date {
  const { year, week } = parseIsoWeek(isoWeek)
  // Jan 4 is always in week 1 of its ISO year
  const jan4 = new Date(year, 0, 4)
  const jan4Dow = jan4.getDay() === 0 ? 7 : jan4.getDay()  // 1=Mon…7=Sun
  const week1Mon = new Date(jan4)
  week1Mon.setDate(jan4.getDate() - (jan4Dow - 1))
  const result = new Date(week1Mon)
  result.setDate(week1Mon.getDate() + (week - 1) * 7 + day)
  return result
}

const DATE_FMT = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
})

/** '2026-W16' → 'Mon 13 Apr 2026 – Sun 19 Apr 2026' */
export function isoWeekToDateRange(isoWeek: string): string {
  const mon = isoWeekDayToDate(isoWeek, 0)
  const sun = isoWeekDayToDate(isoWeek, 6)
  return `${DATE_FMT.format(mon)} – ${DATE_FMT.format(sun)}`
}

/** '2026-W16' → 'Week of Mon 13 Apr' (compact form for UI) */
export function isoWeekLabel(isoWeek: string): string {
  const mon = isoWeekDayToDate(isoWeek, 0)
  return `Week of ${new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).format(mon)}`
}

export { DAY_NAMES }

// ---------------------------------------------------------------------------
// Client-side shopping list computation
// (used instead of GET /api/shopping-list so per-slot serving overrides apply)
// ---------------------------------------------------------------------------

export interface SlotServings {
  isoWeek: string
  day: number
  meal: number
  servings: number
}

export interface ClientShoppingItem {
  name: string
  quantity: number | null
  unit: string | null
  owned: boolean
  recipeSources: string[]
}

export interface ClientShoppingList {
  items: ClientShoppingItem[]
  unavailableRecipes: string[]
}

/** Build a shopping list client-side from slot data + recipe details + pantry.
 *  Mirrors build_shopping_list() in backend/shopping.py.
 *  Uses per-slot serving overrides instead of DEFAULT_SERVINGS.
 */
export function buildShoppingList(
  slots: WeekSlot[],
  servingsMap: Map<string, number>,   // key: slotKey(isoWeek, day, meal)
  recipeDetails: Map<string, RecipeDetails>,
  pantryItems: PantryItem[],
): ClientShoppingList {
  const unavailableRecipes: string[] = []
  const pantryNames = pantryItems.map(p => normaliseIngredientName(p.name))

  // Aggregate: (normName, unit) → { displayName, quantity, unit, sources }
  const agg = new Map<string, ClientShoppingItem>()
  const order: string[] = []

  for (const slot of slots) {
    if (!slot.recipe_id) continue
    const details = recipeDetails.get(slot.recipe_id)
    if (!details || details.status === 'unavailable') {
      unavailableRecipes.push(details?.name ?? slot.recipe_id)
      continue
    }

    const targetServings = servingsMap.get(slotKey(slot.iso_week, slot.day, slot.meal))
      ?? defaultServings(slot.meal)
    const recipeDefault = details.servings ?? targetServings

    for (const ing of details.ingredients) {
      const scaledQty = ing.quantity != null
        ? (ing.quantity / recipeDefault) * targetServings
        : null

      const norm = normaliseIngredientName(ing.name)
      const unitKey = (ing.unit ?? '').trim().toLowerCase()
      // Use sentinel for null-qty ingredients so they never merge
      const key = scaledQty == null ? `${norm}||__none__||${details.name}` : `${norm}||${unitKey}`

      if (agg.has(key)) {
        const existing = agg.get(key)!
        if (scaledQty != null && existing.quantity != null) {
          existing.quantity = existing.quantity + scaledQty
        }
        if (!existing.recipeSources.includes(details.name)) {
          existing.recipeSources.push(details.name)
        }
      } else {
        const item: ClientShoppingItem = {
          name: ing.name,
          quantity: scaledQty,
          unit: ing.unit,
          owned: _fuzzyMatch(norm, pantryNames),
          recipeSources: [details.name],
        }
        agg.set(key, item)
        order.push(key)
      }
    }
  }

  return {
    items: order.map(k => agg.get(k)!),
    unavailableRecipes: [...new Set(unavailableRecipes)],
  }
}

export function slotKey(isoWeek: string, day: number, meal: number): string {
  return `${isoWeek}|${day}|${meal}`
}

export function defaultServings(meal: number): number {
  return meal === 0 ? 2 : 4  // 0=lunch→2, 1=dinner→4
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json() as Promise<T>
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: body != null ? { 'Content-Type': 'application/json' } : {},
    body: body != null ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`)
  // 202/204 have no body; some 200 responses (e.g. sync endpoints) also have no body
  if (res.status === 202 || res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`PUT ${path} → ${res.status}`)
  return res.json() as Promise<T>
}

async function del(path: string): Promise<void> {
  const res = await fetch(BASE + path, { method: 'DELETE' })
  if (!res.ok) throw new Error(`DELETE ${path} → ${res.status}`)
}

// ---------------------------------------------------------------------------
// Route wrappers
// ---------------------------------------------------------------------------

export const api = {
  // Weeks
  getCurrentWeeks: () => get<WeeksResponse>('/weeks/current'),

  // Recipes
  listRecipes: () => get<RecipeSummary[]>('/recipes'),
  searchRecipes: (q: string, maxTime?: number) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (maxTime != null) params.set('max_time', String(maxTime))
    const qs = params.toString()
    return get<RecipeSummary[]>(`/recipes/search${qs ? '?' + qs : ''}`)
  },
  getRecipe: (id: string) => get<RecipeDetails>(`/recipes/${id}`),

  // Cache
  startCacheRefresh: () => post<void>('/cache/refresh'),
  retryCacheFailed: () => post<void>('/cache/retry'),
  getCacheStatus: () => get<CacheStatus>('/cache/status'),

  // Plan
  getPlan: (week?: string) => get<WeekSlot[]>(`/plan${week ? '?week=' + week : ''}`),
  setPlanSlot: (isoWeek: string, day: DayName, meal: MealName, recipeId: string) =>
    put<WeekSlot>(`/plan/${isoWeek}/${day}/${meal}`, { recipe_id: recipeId }),
  clearPlanSlot: (isoWeek: string, day: DayName, meal: MealName) =>
    del(`/plan/${isoWeek}/${day}/${meal}`),

  // Pantry
  listPantry: () => get<PantryItem[]>('/pantry'),
  addPantryItem: (name: string, quantity?: number, unit?: string) =>
    post<PantryItem>('/pantry', { name, quantity: quantity ?? null, unit: unit ?? null }),
  updatePantryItem: (id: string, name: string, quantity?: number, unit?: string) =>
    put<PantryItem>(`/pantry/${id}`, { name, quantity: quantity ?? null, unit: unit ?? null }),
  deletePantryItem: (id: string) => del(`/pantry/${id}`),

  // Shopping list (backend version — used for Cookidoo sync reference only)
  getShoppingList: (week?: string) =>
    get<ShoppingList>(`/shopping-list${week ? '?week=' + week : ''}`),

  // Suggestions
  getSuggestions: (maxTime?: number) =>
    get<ScoredRecipe[]>(`/suggestions${maxTime != null ? '?max_time=' + maxTime : ''}`),

  // Sync
  syncCalendar: () => post<void>('/sync/calendar'),
  syncShopping: () => post<void>('/sync/shopping'),

  // Custom recipes (local_custom)
  createCustomRecipe: (body: CustomRecipeBody) => post<RecipeDetails>('/recipes/custom', body),
  updateCustomRecipe: (id: string, body: CustomRecipeBody) => put<RecipeDetails>(`/recipes/custom/${id}`, body),
  deleteCustomRecipe: (id: string) => del(`/recipes/custom/${id}`),
}
