import { PantryItem, RecipeDetails, RecipeSummary, scoreRecipe } from '../api'
import './RecipeCard.css'

interface Props {
  recipe: RecipeSummary | RecipeDetails
  pantryItems: PantryItem[]
  /** Full details needed for score — if absent score badge is hidden */
  details?: RecipeDetails
  onClick?: () => void
  actionLabel?: string
}

function hasIngredients(r: RecipeSummary | RecipeDetails): r is RecipeDetails {
  return 'ingredients' in r
}

export default function RecipeCard({ recipe, pantryItems, details, onClick, actionLabel }: Props) {
  const fullRecipe = details ?? (hasIngredients(recipe) ? recipe : undefined)
  const score = fullRecipe ? scoreRecipe(fullRecipe, pantryItems) : null
  const scorePct = score != null ? Math.round(score * 100) : null

  return (
    <div
      className={`recipe-card${onClick ? ' recipe-card--clickable' : ''}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
    >
      <div className="recipe-card__main">
        <span className={`recipe-card__name${recipe.status === 'unavailable' ? ' recipe-card__name--unavailable' : ''}`}>
          {recipe.name}
        </span>

        <div className="recipe-card__badges">
          {recipe.recipe_type === 'local_custom' && (
            <span className="recipe-card__badge recipe-card__badge--custom">
              Custom
            </span>
          )}
          {recipe.cooking_time != null && (
            <span className="recipe-card__badge recipe-card__badge--time">
              {recipe.cooking_time} min
            </span>
          )}
          {scorePct != null && scorePct > 0 && (
            <span className="recipe-card__badge recipe-card__badge--score">
              ✔ {scorePct}%
            </span>
          )}
          {recipe.status === 'unavailable' && (
            <span className="recipe-card__badge recipe-card__badge--warn">
              Not cached
            </span>
          )}
          {fullRecipe?.source_url && (
            <a
              className="recipe-card__badge recipe-card__badge--link"
              href={fullRecipe.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
            >
              Source
            </a>
          )}
        </div>
      </div>

      {actionLabel && onClick && (
        <button className="recipe-card__action" tabIndex={-1} aria-hidden="true">
          {actionLabel}
        </button>
      )}
    </div>
  )
}
