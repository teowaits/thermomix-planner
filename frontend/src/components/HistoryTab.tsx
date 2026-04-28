import { useEffect, useState } from 'react'
import { api, HistorySlot, isoWeekToDateRange } from '../api'
import './HistoryTab.css'

const MEAL_LABEL = ['Lunch', 'Dinner'] as const
const DAY_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const

export default function HistoryTab() {
  const [slots, setSlots] = useState<HistorySlot[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getHistory()
      .then(setSlots)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="history-tab history-tab--state">Loading…</div>
  if (error) return <div className="history-tab history-tab--state history-tab--error">{error}</div>
  if (slots.length === 0) return (
    <div className="history-tab history-tab--state">No past meals recorded yet.</div>
  )

  // Group by iso_week (backend returns DESC order)
  const byWeek = new Map<string, HistorySlot[]>()
  for (const slot of slots) {
    if (!byWeek.has(slot.iso_week)) byWeek.set(slot.iso_week, [])
    byWeek.get(slot.iso_week)!.push(slot)
  }

  return (
    <div className="history-tab">
      {[...byWeek.entries()].map(([week, weekSlots]) => (
        <section key={week} className="history-week">
          <h2 className="history-week__title">{isoWeekToDateRange(week)}</h2>
          <ul className="history-week__list">
            {weekSlots.map(slot => (
              <li key={`${slot.day}-${slot.meal}`} className="history-slot">
                <span className="history-slot__day">{DAY_FULL[slot.day]}</span>
                <span className="history-slot__meal">{MEAL_LABEL[slot.meal]}</span>
                <span className="history-slot__recipe">{slot.recipe_name}</span>
                {slot.cooking_time != null && (
                  <span className="history-slot__time">{slot.cooking_time} min</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
