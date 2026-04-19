import { useEffect, useMemo, useRef, useState } from 'react'
import { api, DAY_NAMES, MEAL_NAMES, PantryItem, RecipeDetails, RecipeSummary, scoreRecipe } from '../api'
import { normaliseIngredientName } from '../utils/normalise'
import type { FocusedSlot } from '../App'
import CustomRecipeModal from './CustomRecipeModal'
import RecipeCard from './RecipeCard'
import TimeSlider, { ANY_SENTINEL, sliderToMaxTime } from './TimeSlider'
import './RecipesTab.css'

type SortOption = 'score' | 'time' | 'name'

interface Props {
  pantryItems: PantryItem[]
  recipeDetails: Map<string, RecipeDetails>
  focusedSlot: FocusedSlot | null
  viewingWeek: string
  onRecipeDetailsFetched: (r: RecipeDetails) => void
  onAssign: (recipeId: string) => void                                              // focused-slot assign
  onDirectAssign: (recipeId: string, isoWeek: string, day: number, meal: number) => void  // picker assign
  onRecipeCreated: (r: RecipeDetails) => void
  onRecipeUpdated: (r: RecipeDetails) => void
  onRecipeDeleted: (id: string) => void
}

function sortRecipes(
  recipes: RecipeSummary[],
  sort: SortOption,
  detailsMap: Map<string, RecipeDetails>,
  pantry: PantryItem[],
): RecipeSummary[] {
  const arr = [...recipes]
  if (sort === 'score') {
    arr.sort((a, b) => {
      const da = detailsMap.get(a.id)
      const db = detailsMap.get(b.id)
      const sa = da ? scoreRecipe(da, pantry) : 0
      const sb = db ? scoreRecipe(db, pantry) : 0
      if (sb !== sa) return sb - sa
      return a.name.localeCompare(b.name)
    })
  } else if (sort === 'time') {
    arr.sort((a, b) => {
      if (a.cooking_time == null && b.cooking_time == null) return a.name.localeCompare(b.name)
      if (a.cooking_time == null) return 1
      if (b.cooking_time == null) return -1
      if (a.cooking_time !== b.cooking_time) return a.cooking_time - b.cooking_time
      return a.name.localeCompare(b.name)
    })
  }
  return arr
}

export default function RecipesTab({
  pantryItems,
  recipeDetails,
  focusedSlot,
  viewingWeek,
  onRecipeDetailsFetched,
  onAssign,
  onDirectAssign,
  onRecipeCreated,
  onRecipeUpdated,
  onRecipeDeleted,
}: Props) {
  const [query, setQuery] = useState('')
  const [maxTimeSlider, setMaxTimeSlider] = useState(ANY_SENTINEL)
  const [debouncedMaxTime, setDebouncedMaxTime] = useState(ANY_SENTINEL)
  const [sort, setSort] = useState<SortOption>('score')
  const [results, setResults] = useState<RecipeSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [pickerOpenId, setPickerOpenId] = useState<string | null>(null)
  const [modalMode, setModalMode] = useState<'create' | 'edit' | null>(null)
  const [editingRecipe, setEditingRecipe] = useState<RecipeDetails | undefined>(undefined)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    searchRef.current?.focus()
  }, [])

  // Debounce the time slider so rapid dragging doesn't thrash the search API
  useEffect(() => {
    const t = setTimeout(() => setDebouncedMaxTime(maxTimeSlider), 300)
    return () => clearTimeout(t)
  }, [maxTimeSlider])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setExpandedId(null)
    const maxTime = sliderToMaxTime(debouncedMaxTime)
    api.searchRecipes(query, maxTime).then(r => {
      if (!controller.signal.aborted) {
        setResults(r)
        setLoading(false)
        const missing = r.filter(s => !recipeDetails.has(s.id)).slice(0, 30)
        missing.forEach(s => {
          api.getRecipe(s.id).then(onRecipeDetailsFetched).catch(() => {})
        })
      }
    }).catch(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [query, debouncedMaxTime]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSaveModal = (recipe: RecipeDetails) => {
    if (modalMode === 'create') {
      onRecipeCreated(recipe)
      setResults(prev => [recipe, ...prev])
    } else {
      onRecipeUpdated(recipe)
      setResults(prev => prev.map(r => r.id === recipe.id ? recipe : r))
    }
    setModalMode(null)
    setEditingRecipe(undefined)
  }

  const handleDelete = async (id: string) => {
    setDeletingId(id)
    try {
      await api.deleteCustomRecipe(id)
      onRecipeDeleted(id)
      setResults(prev => prev.filter(r => r.id !== id))
    } catch {
      // leave in list on failure
    } finally {
      setDeletingId(null)
    }
  }

  const knownIngredients = useMemo(() => {
    const names = new Set<string>()
    pantryItems.forEach(p => names.add(p.name))
    recipeDetails.forEach(r => r.ingredients.forEach(i => { if (i.name) names.add(i.name) }))
    return Array.from(names).sort()
  }, [pantryItems, recipeDetails])

  const sorted = sortRecipes(results, sort, recipeDetails, pantryItems)

  const handleToggleExpand = (recipeId: string) => {
    // If a slot is focused, a click assigns rather than expands
    if (focusedSlot) {
      onAssign(recipeId)
      return
    }
    if (expandedId === recipeId) {
      setExpandedId(null)
      return
    }
    setExpandedId(recipeId)
    if (!recipeDetails.has(recipeId)) {
      api.getRecipe(recipeId).then(onRecipeDetailsFetched).catch(() => {})
    }
  }

  const focusedDayName = focusedSlot != null ? DAY_NAMES[focusedSlot.day] : null
  const focusedMealName = focusedSlot != null ? MEAL_NAMES[focusedSlot.meal] : null

  return (
    <div className="recipes-tab">
      {modalMode && (
        <CustomRecipeModal
          existing={editingRecipe}
          knownIngredients={knownIngredients}
          onSave={handleSaveModal}
          onClose={() => { setModalMode(null); setEditingRecipe(undefined) }}
        />
      )}

      {/* Focused-slot indicator (path A) */}
      {focusedSlot && (
        <div className="recipes-tab__slot-banner" role="status">
          Assigning to <strong>{focusedDayName} {focusedMealName}</strong> — click a recipe to assign it
        </div>
      )}

      <div className="recipes-tab__toolbar">
        <input
          ref={searchRef}
          type="search"
          className="recipes-tab__search"
          placeholder="Search recipes…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          aria-label="Search recipes"
        />

        <TimeSlider
          value={maxTimeSlider}
          onChange={setMaxTimeSlider}
          label="Max time"
        />

        <div className="recipes-tab__sort">
          <span className="recipes-tab__sort-label">Sort:</span>
          {(['score', 'time', 'name'] as SortOption[]).map(opt => (
            <button
              key={opt}
              className={`recipes-tab__sort-btn${sort === opt ? ' recipes-tab__sort-btn--active' : ''}`}
              onClick={() => setSort(opt)}
            >
              {opt === 'score' ? 'Best match' : opt === 'time' ? 'Quickest' : 'A–Z'}
            </button>
          ))}
        </div>

        <span className="recipes-tab__count">
          {!loading && `${results.length.toLocaleString()} recipe${results.length !== 1 ? 's' : ''}`}
        </span>

        <button
          className="recipes-tab__new-btn"
          onClick={() => { setModalMode('create'); setEditingRecipe(undefined) }}
        >
          + New recipe
        </button>
      </div>

      <div className="recipes-tab__list">
        {loading && <div className="recipes-tab__state">Searching…</div>}
        {!loading && results.length === 0 && (
          <div className="recipes-tab__state">No recipes found.</div>
        )}
        {!loading && sorted.map(recipe => {
          const isExpanded = expandedId === recipe.id && !focusedSlot
          const details = recipeDetails.get(recipe.id)
          const isPickerOpen = pickerOpenId === recipe.id

          return (
            <div key={recipe.id} className={`recipes-tab__item${isExpanded ? ' recipes-tab__item--expanded' : ''}`}>
              <div className="recipes-tab__item-row">
                <RecipeCard
                  recipe={recipe}
                  pantryItems={pantryItems}
                  details={details}
                  onClick={() => handleToggleExpand(recipe.id)}
                  actionLabel={focusedSlot ? 'Assign' : (isExpanded ? '▲' : '▼')}
                />

                {/* Edit/Delete for local custom recipes */}
                {!focusedSlot && recipe.recipe_type === 'local_custom' && (
                  <div className="recipes-tab__custom-actions">
                    <button
                      className="recipes-tab__edit-btn"
                      title="Edit recipe"
                      onClick={e => {
                        e.stopPropagation()
                        const det = recipeDetails.get(recipe.id)
                        setEditingRecipe(det)
                        setModalMode('edit')
                      }}
                      aria-label="Edit recipe"
                    >
                      Edit
                    </button>
                    <button
                      className="recipes-tab__del-btn"
                      title="Delete recipe"
                      disabled={deletingId === recipe.id}
                      onClick={e => {
                        e.stopPropagation()
                        if (confirm(`Delete "${recipe.name}"?`)) handleDelete(recipe.id)
                      }}
                      aria-label="Delete recipe"
                    >
                      {deletingId === recipe.id ? '…' : 'Del'}
                    </button>
                  </div>
                )}

                {/* Path B: "Add to plan" button — shown when no slot is focused */}
                {!focusedSlot && (
                  <div className="recipes-tab__add-wrap">
                    <button
                      className="recipes-tab__add-btn"
                      title="Add to plan"
                      onClick={e => {
                        e.stopPropagation()
                        setPickerOpenId(isPickerOpen ? null : recipe.id)
                      }}
                      aria-label="Add to plan"
                    >
                      +
                    </button>

                    {isPickerOpen && (
                      <div className="recipes-tab__slot-picker" role="dialog" aria-label="Pick a meal slot">
                        <div className="recipes-tab__slot-picker-head">
                          <span>Assign to:</span>
                          <button
                            className="recipes-tab__slot-picker-close"
                            onClick={() => setPickerOpenId(null)}
                            aria-label="Close"
                          >×</button>
                        </div>
                        <table className="recipes-tab__slot-grid">
                          <thead>
                            <tr>
                              <th></th>
                              {MEAL_NAMES.map(m => (
                                <th key={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {DAY_NAMES.map((day, dayIdx) => (
                              <tr key={day}>
                                <th>{day}</th>
                                {MEAL_NAMES.map((_, mealIdx) => (
                                  <td key={mealIdx}>
                                    <button
                                      className="recipes-tab__slot-cell"
                                      onClick={() => {
                                        setPickerOpenId(null)
                                        onDirectAssign(recipe.id, viewingWeek, dayIdx, mealIdx)
                                      }}
                                    >
                                      ✓
                                    </button>
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {isExpanded && (
                <div className="recipes-tab__detail">
                  {!details && (
                    <p className="recipes-tab__detail-loading">Loading details…</p>
                  )}
                  {details && details.status === 'unavailable' && (
                    <p className="recipes-tab__detail-unavailable">
                      This recipe is not available in the cache. Refresh the cache to retry.
                    </p>
                  )}
                  {details && details.status === 'ok' && (
                    <>
                      <div className="recipes-tab__detail-meta">
                        {details.servings != null && (
                          <span>{details.servings} servings</span>
                        )}
                        {details.cooking_time != null && (
                          <span>{details.cooking_time} min</span>
                        )}
                        {details.collection_id && (
                          <span className="recipes-tab__detail-collection" title={details.collection_id}>
                            {details.collection_id.replace(/VrkChipCollection-/i, '').split('-')[0]}
                          </span>
                        )}
                        {details.source_url && (
                          <a
                            className="recipes-tab__detail-source"
                            href={details.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={e => e.stopPropagation()}
                          >
                            Source ↗
                          </a>
                        )}
                      </div>
                      {details.ingredients.length > 0 && (
                        <ul className="recipes-tab__ingredients">
                          {details.ingredients.map((ing, i) => (
                            <li key={i} className="recipes-tab__ingredient">
                              <span className="recipes-tab__ing-name">{normaliseIngredientName(ing.name)}</span>
                              {(ing.quantity != null || ing.unit) && (
                                <span className="recipes-tab__ing-qty">
                                  {ing.quantity != null
                                    ? (Number.isInteger(ing.quantity)
                                        ? ing.quantity
                                        : ing.quantity.toFixed(1))
                                    : ''}
                                  {ing.unit ? ` ${ing.unit}` : ''}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
