import { useCallback, useEffect, useRef, useState } from 'react'
import { pdf } from '@react-pdf/renderer'
import {
  api,
  buildShoppingList,
  ClientShoppingList,
  DAY_NAMES,
  defaultServings,
  DayName,
  MealName,
  MEAL_NAMES,
  PantryItem,
  RecipeDetails,
  slotKey,
  WeekSlot,
} from './api'
import WeekPlanPDF from './components/WeekPlanPDF'
import CacheStatus from './components/CacheStatus'
import HistoryTab from './components/HistoryTab'
import PantryManager from './components/PantryManager'
import RecipePicker from './components/RecipePicker'
import RecipesTab from './components/RecipesTab'
import ShoppingList from './components/ShoppingList'
import WeekGrid from './components/WeekGrid'
import WeekNav from './components/WeekNav'
import './App.css'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ActiveTab = 'plan' | 'recipes' | 'pantry' | 'shopping' | 'history'

export interface FocusedSlot {
  isoWeek: string
  day: number
  meal: number
  mode: 'assign' | 'replace'
}

// ---------------------------------------------------------------------------
// localStorage helpers for serving overrides
// ---------------------------------------------------------------------------

/** Remove servings-{isoWeek} keys older than 4 weeks to avoid localStorage bloat. */
function pruneStaleServings() {
  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() - 28)
  const toDelete: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key?.startsWith('servings-')) continue
    // key format: servings-YYYY-WNN
    const weekStr = key.slice('servings-'.length)
    const [yearStr, weekNumStr] = weekStr.split('-W')
    if (!yearStr || !weekNumStr) continue
    const year = parseInt(yearStr, 10)
    const week = parseInt(weekNumStr, 10)
    if (isNaN(year) || isNaN(week)) continue
    // Monday of that ISO week
    const jan4 = new Date(year, 0, 4)
    const jan4Dow = jan4.getDay() === 0 ? 7 : jan4.getDay()
    const weekMon = new Date(jan4)
    weekMon.setDate(jan4.getDate() - (jan4Dow - 1) + (week - 1) * 7)
    if (weekMon < cutoff) toDelete.push(key)
  }
  toDelete.forEach(k => localStorage.removeItem(k))
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  // ---- Tab & navigation state ----
  const [activeTab, setActiveTab] = useState<ActiveTab>('plan')
  const [focusedSlot, setFocusedSlot] = useState<FocusedSlot | null>(null)
  const [currentWeek, setCurrentWeek] = useState<string>('')
  const [nextWeek, setNextWeek] = useState<string>('')
  const [viewingWeek, setViewingWeek] = useState<string>('')

  // ---- Plan state ----
  const [weekSlots, setWeekSlots] = useState<WeekSlot[]>([])

  // ---- Per-slot serving overrides: slotKey → servings ----
  // Initialised from localStorage once viewingWeek is known (see effect below).
  const [servingsMap, setServingsMap] = useState<Map<string, number>>(new Map())

  // ---- Recipe details cache: id → RecipeDetails ----
  const [recipeDetails, setRecipeDetails] = useState<Map<string, RecipeDetails>>(new Map())

  // ---- Pantry ----
  const [pantryItems, setPantryItems] = useState<PantryItem[]>([])

  // ---- Client-side shopping list (derived) ----
  const [shoppingList, setShoppingList] = useState<ClientShoppingList>({ items: [], unavailableRecipes: [] })

  // ---- Error banner ----
  const [error, setError] = useState<string | null>(null)

  // Ref to avoid stale closure in shopping list recompute
  const recipeDetailsRef = useRef(recipeDetails)
  recipeDetailsRef.current = recipeDetails

  // ---- Drag source ref (no state — avoids re-renders during drag) ----
  const dragSourceRef = useRef<{ isoWeek: string; day: number; meal: number; recipeId: string } | null>(null)

  // ---------------------------------------------------------------------------
  // Bootstrap: fetch weeks + plan + pantry
  // ---------------------------------------------------------------------------

  useEffect(() => {
    api.getCurrentWeeks().then(({ current, next }) => {
      setCurrentWeek(current)
      setNextWeek(next)
      setViewingWeek(current)
    }).catch(() => setError('Cannot reach backend. Is the server running?'))
  }, [])

  // Fetch plan when viewingWeek changes
  useEffect(() => {
    if (!viewingWeek) return
    api.getPlan(viewingWeek).then(setWeekSlots).catch(console.error)
  }, [viewingWeek])

  // Fetch pantry once on mount
  useEffect(() => {
    api.listPantry().then(setPantryItems).catch(console.error)
  }, [])

  // Prefetch recipe details for all assigned slots
  useEffect(() => {
    const ids = weekSlots.map(s => s.recipe_id).filter((id): id is string => id !== null)
    const missing = ids.filter(id => !recipeDetails.has(id))
    if (missing.length === 0) return
    Promise.all(missing.map(id => api.getRecipe(id))).then(results => {
      setRecipeDetails(prev => {
        const next = new Map(prev)
        results.forEach(r => next.set(r.id, r))
        return next
      })
    }).catch(console.error)
  }, [weekSlots]) // eslint-disable-line react-hooks/exhaustive-deps

  // Load servingsMap from localStorage when viewingWeek is first known
  useEffect(() => {
    if (!viewingWeek) return
    pruneStaleServings()
    const raw = localStorage.getItem(`servings-${viewingWeek}`)
    if (raw) {
      try {
        const obj = JSON.parse(raw) as Record<string, number>
        setServingsMap(new Map(Object.entries(obj)))
      } catch { /* ignore malformed */ }
    } else {
      setServingsMap(new Map())
    }
  }, [viewingWeek])

  // Persist servingsMap to localStorage whenever it changes
  useEffect(() => {
    if (!viewingWeek) return
    const obj: Record<string, number> = {}
    servingsMap.forEach((v, k) => { obj[k] = v })
    localStorage.setItem(`servings-${viewingWeek}`, JSON.stringify(obj))
  }, [servingsMap, viewingWeek])

  // Recompute shopping list whenever inputs change
  useEffect(() => {
    const list = buildShoppingList(weekSlots, servingsMap, recipeDetails, pantryItems)
    setShoppingList(list)
  }, [weekSlots, servingsMap, recipeDetails, pantryItems])

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleTabChange = useCallback((tab: ActiveTab) => {
    setActiveTab(tab)
    // Keep focusedSlot when switching to Recipes so the user can pick a recipe
    // from there. Clear it when going to any other tab.
    if (tab !== 'recipes') setFocusedSlot(null)
  }, [])

  const handleSlotClick = useCallback((isoWeek: string, day: number, meal: number, hasRecipe: boolean) => {
    setFocusedSlot({ isoWeek, day, meal, mode: hasRecipe ? 'replace' : 'assign' })
  }, [])

  const handleRecipeAssign = useCallback(async (recipeId: string) => {
    if (!focusedSlot) return
    const { isoWeek, day, meal } = focusedSlot
    const dayName = DAY_NAMES[day] as DayName
    const mealName = MEAL_NAMES[meal] as MealName
    try {
      const slot = await api.setPlanSlot(isoWeek, dayName, mealName, recipeId)
      setWeekSlots(prev => {
        const filtered = prev.filter(s => !(s.iso_week === isoWeek && s.day === day && s.meal === meal))
        return [...filtered, slot]
      })
      // Ensure recipe details are fetched
      if (!recipeDetails.has(recipeId)) {
        api.getRecipe(recipeId).then(r => {
          setRecipeDetails(prev => new Map(prev).set(r.id, r))
        }).catch(console.error)
      }
      setFocusedSlot(null)
    } catch (e) {
      setError(`Failed to assign recipe: ${e}`)
    }
  }, [focusedSlot, recipeDetails])

  const handleSlotClear = useCallback(async (isoWeek: string, day: number, meal: number) => {
    const dayName = DAY_NAMES[day] as DayName
    const mealName = MEAL_NAMES[meal] as MealName
    try {
      await api.clearPlanSlot(isoWeek, dayName, mealName)
      setWeekSlots(prev => prev.filter(
        s => !(s.iso_week === isoWeek && s.day === day && s.meal === meal)
      ))
      if (focusedSlot?.isoWeek === isoWeek && focusedSlot.day === day && focusedSlot.meal === meal) {
        setFocusedSlot(null)
      }
    } catch (e) {
      setError(`Failed to clear slot: ${e}`)
    }
  }, [focusedSlot])

  const handleServingsChange = useCallback((isoWeek: string, day: number, meal: number, delta: number) => {
    const key = slotKey(isoWeek, day, meal)
    setServingsMap(prev => {
      const current = prev.get(key) ?? defaultServings(meal)
      const next = Math.max(1, current + delta)
      const m = new Map(prev)
      m.set(key, next)
      return m
    })
  }, [])

  const handleDragStart = useCallback((isoWeek: string, day: number, meal: number, recipeId: string) => {
    dragSourceRef.current = { isoWeek, day, meal, recipeId }
  }, [])

  const handleDrop = useCallback(async (targetIsoWeek: string, targetDay: number, targetMeal: number) => {
    const src = dragSourceRef.current
    dragSourceRef.current = null
    if (!src) return
    if (src.isoWeek === targetIsoWeek && src.day === targetDay && src.meal === targetMeal) return

    const targetSlot = weekSlots.find(
      s => s.iso_week === targetIsoWeek && s.day === targetDay && s.meal === targetMeal
    )
    const targetRecipeId = targetSlot?.recipe_id ?? null

    const srcDay = DAY_NAMES[src.day] as DayName
    const srcMeal = MEAL_NAMES[src.meal] as MealName
    const tgtDay = DAY_NAMES[targetDay] as DayName
    const tgtMeal = MEAL_NAMES[targetMeal] as MealName

    try {
      const newTgt = await api.setPlanSlot(targetIsoWeek, tgtDay, tgtMeal, src.recipeId)
      if (targetRecipeId) {
        // Swap: put the displaced recipe back in the source slot
        const newSrc = await api.setPlanSlot(src.isoWeek, srcDay, srcMeal, targetRecipeId)
        setWeekSlots(prev => {
          const filtered = prev.filter(s =>
            !(s.iso_week === targetIsoWeek && s.day === targetDay && s.meal === targetMeal) &&
            !(s.iso_week === src.isoWeek && s.day === src.day && s.meal === src.meal)
          )
          return [...filtered, newTgt, newSrc]
        })
      } else {
        // Move: clear source slot
        await api.clearPlanSlot(src.isoWeek, srcDay, srcMeal)
        setWeekSlots(prev => {
          const filtered = prev.filter(s =>
            !(s.iso_week === targetIsoWeek && s.day === targetDay && s.meal === targetMeal) &&
            !(s.iso_week === src.isoWeek && s.day === src.day && s.meal === src.meal)
          )
          return [...filtered, newTgt]
        })
      }
    } catch (e) {
      setError(`Failed to move recipe: ${e}`)
    }
  }, [weekSlots])

  const handlePantryChange = useCallback(async () => {
    const items = await api.listPantry()
    setPantryItems(items)
  }, [])

  const handleExportPDF = useCallback(async () => {
    const backendList = await api.getShoppingList(viewingWeek)
    const clientItems = backendList.items.map(item => ({
      name: item.name,
      quantity: item.quantity,
      unit: item.unit,
      owned: item.owned,
      recipeSources: item.recipe_sources,
    }))
    const blob = await pdf(
      <WeekPlanPDF
        viewingWeek={viewingWeek}
        weekSlots={weekSlots}
        pantryItems={pantryItems}
        shoppingItems={clientItems}
        recipeDetails={recipeDetails}
      />
    ).toBlob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `meal-plan-${viewingWeek}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }, [viewingWeek, weekSlots, pantryItems, recipeDetails])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const tabs: { id: ActiveTab; label: string }[] = [
    { id: 'plan', label: 'Week Plan' },
    { id: 'recipes', label: 'Recipes' },
    { id: 'pantry', label: 'Pantry' },
    { id: 'shopping', label: 'Shopping' },
    { id: 'history', label: 'History' },
  ]

  return (
    <div className="app">
      {/* Top bar */}
      <header className="app-header">
        <span className="app-title">Thermomix Planner</span>
        <nav className="tab-nav" role="tablist">
          {tabs.map(t => (
            <button
              key={t.id}
              role="tab"
              aria-selected={activeTab === t.id}
              className={`tab-btn${activeTab === t.id ? ' tab-btn--active' : ''}`}
              onClick={() => handleTabChange(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      {/* Cache status banner — always visible */}
      <CacheStatus />

      {/* Error banner */}
      {error && (
        <div className="error-banner" role="alert">
          {error}
          <button className="error-close" onClick={() => setError(null)} aria-label="Dismiss">×</button>
        </div>
      )}

      {/* Main content */}
      <main className="app-main" role="tabpanel">
        {activeTab === 'plan' && (
          <div className={`plan-layout${focusedSlot ? ' plan-layout--panel-open' : ''}`}>
            <div className="plan-content">
              {viewingWeek && (
                <WeekNav
                  viewingWeek={viewingWeek}
                  currentWeek={currentWeek}
                  nextWeek={nextWeek}
                  onWeekChange={setViewingWeek}
                  onExportPDF={handleExportPDF}
                />
              )}
              {viewingWeek && (
                <WeekGrid
                  isoWeek={viewingWeek}
                  slots={weekSlots}
                  recipeDetails={recipeDetails}
                  pantryItems={pantryItems}
                  servingsMap={servingsMap}
                  focusedSlot={focusedSlot}
                  onSlotClick={handleSlotClick}
                  onSlotClear={handleSlotClear}
                  onServingsChange={handleServingsChange}
                  onDragStart={handleDragStart}
                  onDrop={handleDrop}
                />
              )}
            </div>
            {focusedSlot && (
              <RecipePicker
                focusedSlot={focusedSlot}
                pantryItems={pantryItems}
                recipeDetails={recipeDetails}
                onAssign={handleRecipeAssign}
                onClose={() => setFocusedSlot(null)}
                onRecipeDetailsFetched={(r) => setRecipeDetails(prev => new Map(prev).set(r.id, r))}
              />
            )}
          </div>
        )}

        {activeTab === 'recipes' && (
          <RecipesTab
            pantryItems={pantryItems}
            recipeDetails={recipeDetails}
            focusedSlot={focusedSlot}
            viewingWeek={viewingWeek}
            onRecipeDetailsFetched={(r) => setRecipeDetails(prev => new Map(prev).set(r.id, r))}
            onAssign={handleRecipeAssign}
            onDirectAssign={async (recipeId, isoWeek, day, meal) => {
              const dayName = DAY_NAMES[day] as DayName
              const mealName = MEAL_NAMES[meal] as MealName
              try {
                const slot = await api.setPlanSlot(isoWeek, dayName, mealName, recipeId)
                setWeekSlots(prev => {
                  const filtered = prev.filter(s => !(s.iso_week === isoWeek && s.day === day && s.meal === meal))
                  return [...filtered, slot]
                })
                if (!recipeDetails.has(recipeId)) {
                  api.getRecipe(recipeId).then(r => {
                    setRecipeDetails(prev => new Map(prev).set(r.id, r))
                  }).catch(console.error)
                }
              } catch (e) {
                setError(`Failed to assign recipe: ${e}`)
              }
            }}
            onRecipeCreated={(r) => setRecipeDetails(prev => new Map(prev).set(r.id, r))}
            onRecipeUpdated={(r) => setRecipeDetails(prev => new Map(prev).set(r.id, r))}
            onRecipeDeleted={(id) => setRecipeDetails(prev => { const m = new Map(prev); m.delete(id); return m })}
          />
        )}

        {activeTab === 'pantry' && (
          <PantryManager
            items={pantryItems}
            onChange={handlePantryChange}
          />
        )}

        {activeTab === 'shopping' && (
          <ShoppingList
            shoppingList={shoppingList}
            viewingWeek={viewingWeek}
          />
        )}

        {activeTab === 'history' && <HistoryTab />}
      </main>
    </div>
  )
}
