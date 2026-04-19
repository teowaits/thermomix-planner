import { defaultServings, PantryItem, RecipeDetails, scoreRecipe, WeekSlot } from '../api'
import './MealCell.css'

interface Props {
  isoWeek: string
  day: number
  meal: number
  slot: WeekSlot | undefined
  recipe: RecipeDetails | undefined
  pantryItems: PantryItem[]
  servings: number
  isFocused: boolean
  onCellClick: () => void
  onClear: () => void
  onServingsChange: (delta: number) => void
}

export default function MealCell({
  meal,
  slot,
  recipe,
  pantryItems,
  servings,
  isFocused,
  onCellClick,
  onClear,
  onServingsChange,
}: Props) {
  const isEmpty = !slot?.recipe_id

  // Pantry score (only when we have recipe details)
  const score = recipe ? scoreRecipe(recipe, pantryItems) : null
  const scorePct = score != null ? Math.round(score * 100) : null

  const mealLabel = meal === 0 ? 'Lunch' : 'Dinner'

  return (
    <div
      className={[
        'meal-cell',
        isEmpty ? 'meal-cell--empty' : 'meal-cell--filled',
        isFocused ? 'meal-cell--focused' : '',
      ].filter(Boolean).join(' ')}
    >
      {/* Meal label */}
      <span className="meal-cell__label">{mealLabel}</span>

      {isEmpty ? (
        <button className="meal-cell__add" onClick={onCellClick} aria-label={`Add ${mealLabel} recipe`}>
          <span className="meal-cell__plus">+</span>
          <span className="meal-cell__add-text">Add recipe</span>
        </button>
      ) : (
        <>
          {/* Clear button */}
          <button
            className="meal-cell__clear"
            onClick={(e) => { e.stopPropagation(); onClear() }}
            aria-label="Remove recipe"
          >
            ×
          </button>

          {/* Recipe name — clickable to re-open picker */}
          <button className="meal-cell__name" onClick={onCellClick}>
            {recipe?.name ?? (slot?.recipe_id ? '(deleted)' : '…')}
          </button>

          {/* Score badge */}
          {scorePct != null && scorePct > 0 && (
            <span className="meal-cell__score" title="Pantry match">
              ✔ {scorePct}% from pantry
            </span>
          )}

          {/* Servings badge */}
          <div className="meal-cell__servings">
            <button
              className="meal-cell__serving-btn"
              onClick={(e) => { e.stopPropagation(); onServingsChange(-1) }}
              aria-label="Decrease servings"
            >
              −
            </button>
            <span className="meal-cell__serving-count">
              {servings} {servings === 1 ? 'serving' : 'servings'}
            </span>
            <button
              className="meal-cell__serving-btn"
              onClick={(e) => { e.stopPropagation(); onServingsChange(+1) }}
              aria-label="Increase servings"
            >
              +
            </button>
          </div>

          {/* Unavailable warning */}
          {recipe?.status === 'unavailable' && (
            <span className="meal-cell__unavailable">Not in cache</span>
          )}
        </>
      )}
    </div>
  )
}

// Re-export for WeekGrid convenience
export { defaultServings }
