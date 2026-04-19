import { useEffect, useRef, useState } from 'react'
import { api, DAY_NAMES, MEAL_NAMES, PantryItem, RecipeDetails, RecipeSummary } from '../api'
import type { FocusedSlot } from '../App'
import RecipeCard from './RecipeCard'
import TimeSlider, { ANY_SENTINEL, sliderToMaxTime } from './TimeSlider'
import './RecipePicker.css'

interface Props {
  focusedSlot: FocusedSlot
  pantryItems: PantryItem[]
  recipeDetails: Map<string, RecipeDetails>
  onAssign: (recipeId: string) => void
  onClose: () => void
  onRecipeDetailsFetched: (r: RecipeDetails) => void
}

export default function RecipePicker({
  focusedSlot,
  pantryItems,
  recipeDetails,
  onAssign,
  onClose,
  onRecipeDetailsFetched,
}: Props) {
  const [query, setQuery] = useState('')
  const [maxTimeSlider, setMaxTimeSlider] = useState(ANY_SENTINEL)
  const [debouncedMaxTime, setDebouncedMaxTime] = useState(ANY_SENTINEL)
  const [results, setResults] = useState<RecipeSummary[]>([])
  const [loading, setLoading] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)

  const dayName = DAY_NAMES[focusedSlot.day]
  const mealName = MEAL_NAMES[focusedSlot.meal]
  const title = focusedSlot.mode === 'assign'
    ? `Add recipe — ${dayName} ${mealName}`
    : `Replace recipe — ${dayName} ${mealName}`

  useEffect(() => {
    searchRef.current?.focus()
  }, [])

  useEffect(() => {
    const t = setTimeout(() => setDebouncedMaxTime(maxTimeSlider), 300)
    return () => clearTimeout(t)
  }, [maxTimeSlider])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    const maxTime = sliderToMaxTime(debouncedMaxTime)
    api.searchRecipes(query, maxTime).then(r => {
      if (!controller.signal.aborted) {
        setResults(r)
        setLoading(false)
        const missing = r.filter(s => !recipeDetails.has(s.id)).slice(0, 20)
        missing.forEach(s => {
          api.getRecipe(s.id).then(onRecipeDetailsFetched).catch(() => {})
        })
      }
    }).catch(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [query, debouncedMaxTime]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <aside className="recipe-picker" aria-label="Recipe picker">
      <div className="recipe-picker__header">
        <h2 className="recipe-picker__title">{title}</h2>
        <button className="recipe-picker__close" onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className="recipe-picker__search">
        <input
          ref={searchRef}
          type="search"
          className="recipe-picker__input"
          placeholder="Search recipes…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          aria-label="Search recipes"
        />
      </div>

      <div className="recipe-picker__time-filter">
        <TimeSlider
          label="Max time"
          value={maxTimeSlider}
          onChange={setMaxTimeSlider}
        />
      </div>

      <div className="recipe-picker__results">
        {loading && <div className="recipe-picker__loading">Searching…</div>}
        {!loading && results.length === 0 && (
          <div className="recipe-picker__empty">No recipes found.</div>
        )}
        {!loading && results.map(recipe => (
          <RecipeCard
            key={recipe.id}
            recipe={recipe}
            pantryItems={pantryItems}
            details={recipeDetails.get(recipe.id)}
            onClick={() => onAssign(recipe.id)}
            actionLabel="Assign"
          />
        ))}
      </div>
    </aside>
  )
}
