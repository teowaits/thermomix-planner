import { defaultServings, PantryItem, RecipeDetails, scoreRecipe, WeekSlot } from '../api'
import './MealCell.css'
import './RecipeCard.css'

interface Props {
  isoWeek: string
  day: number
  meal: number
  slot: WeekSlot | undefined
  recipe: RecipeDetails | undefined
  pantryItems: PantryItem[]
  servings: number
  isFocused: boolean
  isDragOver?: boolean
  onCellClick: () => void
  onClear: () => void
  onServingsChange: (delta: number) => void
  onDragStart?: () => void
  onDragOver?: () => void
  onDragLeave?: () => void
  onDrop?: () => void
}

export default function MealCell({
  meal,
  slot,
  recipe,
  pantryItems,
  servings,
  isFocused,
  isDragOver,
  onCellClick,
  onClear,
  onServingsChange,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDrop,
}: Props) {
  const isEmpty = !slot?.recipe_id

  const score = recipe ? scoreRecipe(recipe, pantryItems) : null
  const scorePct = score != null ? Math.round(score * 100) : null

  const mealLabel = meal === 0 ? 'Lunch' : 'Dinner'

  return (
    <div
      className={[
        'meal-cell',
        isEmpty ? 'meal-cell--empty' : 'meal-cell--filled',
        isFocused ? 'meal-cell--focused' : '',
        isDragOver ? 'meal-cell--drag-over' : '',
      ].filter(Boolean).join(' ')}
      draggable={!isEmpty}
      onDragStart={!isEmpty ? (e) => { e.dataTransfer.effectAllowed = 'move'; onDragStart?.() } : undefined}
      onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; onDragOver?.() }}
      onDragLeave={onDragLeave}
      onDrop={(e) => { e.preventDefault(); onDrop?.() }}
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

          {/* Recipe name with hover tooltip */}
          <div className="meal-cell__name-wrap">
            <button className="meal-cell__name" onClick={onCellClick}>
              {recipe?.name ?? (slot?.recipe_id ? '(deleted)' : '…')}
            </button>
            {recipe && (recipe.cooking_time != null || recipe.ingredients.length > 0) && (
              <div className="meal-cell__tooltip" role="tooltip">
                {recipe.cooking_time != null && (
                  <div className="meal-cell__tooltip-time">⏱ {recipe.cooking_time} min</div>
                )}
                {recipe.ingredients.length > 0 && (
                  <ul className="meal-cell__tooltip-ingredients">
                    {recipe.ingredients.slice(0, 10).map((ing, i) => (
                      <li key={i}>{ing.name}</li>
                    ))}
                    {recipe.ingredients.length > 10 && (
                      <li className="meal-cell__tooltip-more">
                        +{recipe.ingredients.length - 10} more
                      </li>
                    )}
                  </ul>
                )}
              </div>
            )}
          </div>

          {/* Custom recipe badge */}
          {recipe?.recipe_type === 'local_custom' && (
            <span className="recipe-card__badge recipe-card__badge--custom">
              Custom
            </span>
          )}

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
