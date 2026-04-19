import { DAY_NAMES, defaultServings, PantryItem, RecipeDetails, slotKey, WeekSlot } from '../api'
import type { FocusedSlot } from '../App'
import MealCell from './MealCell'
import './WeekGrid.css'

interface Props {
  isoWeek: string
  slots: WeekSlot[]
  recipeDetails: Map<string, RecipeDetails>
  pantryItems: PantryItem[]
  servingsMap: Map<string, number>
  focusedSlot: FocusedSlot | null
  onSlotClick: (isoWeek: string, day: number, meal: number, hasRecipe: boolean) => void
  onSlotClear: (isoWeek: string, day: number, meal: number) => void
  onServingsChange: (isoWeek: string, day: number, meal: number, delta: number) => void
}

// Day abbreviations and full names for the grid header
const DAY_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const

export default function WeekGrid({
  isoWeek,
  slots,
  recipeDetails,
  pantryItems,
  servingsMap,
  focusedSlot,
  onSlotClick,
  onSlotClear,
  onServingsChange,
}: Props) {
  // Build lookup: (day, meal) → WeekSlot
  const slotMap = new Map<string, WeekSlot>()
  for (const s of slots) {
    if (s.iso_week === isoWeek) {
      slotMap.set(slotKey(s.iso_week, s.day, s.meal), s)
    }
  }

  return (
    <div className="week-grid" role="grid" aria-label="Weekly meal plan">
      {/* Day headers */}
      {DAY_NAMES.map((abbr, dayIdx) => (
        <div key={abbr} className="week-grid__day-header" role="columnheader">
          <span className="week-grid__day-abbr">{abbr}</span>
          <span className="week-grid__day-full">{DAY_FULL[dayIdx]}</span>
        </div>
      ))}

      {/* Meal cells — 7 days × 2 meals */}
      {DAY_NAMES.map((_abbr, dayIdx) => (
        <div key={dayIdx} className="week-grid__day-col">
          {[0, 1].map((mealIdx) => {
            const key = slotKey(isoWeek, dayIdx, mealIdx)
            const slot = slotMap.get(key)
            const recipe = slot?.recipe_id ? recipeDetails.get(slot.recipe_id) : undefined
            const servings = servingsMap.get(key) ?? defaultServings(mealIdx)
            const isFocused =
              focusedSlot?.isoWeek === isoWeek &&
              focusedSlot.day === dayIdx &&
              focusedSlot.meal === mealIdx

            return (
              <MealCell
                key={mealIdx}
                isoWeek={isoWeek}
                day={dayIdx}
                meal={mealIdx}
                slot={slot}
                recipe={recipe}
                pantryItems={pantryItems}
                servings={servings}
                isFocused={isFocused}
                onCellClick={() => onSlotClick(isoWeek, dayIdx, mealIdx, !!slot?.recipe_id)}
                onClear={() => onSlotClear(isoWeek, dayIdx, mealIdx)}
                onServingsChange={(delta) => onServingsChange(isoWeek, dayIdx, mealIdx, delta)}
              />
            )
          })}
        </div>
      ))}
    </div>
  )
}
