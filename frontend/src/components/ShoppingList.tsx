import { useState } from 'react'
import { api, ClientShoppingList, isoWeekToDateRange } from '../api'
import { normaliseIngredientName } from '../utils/normalise'
import './ShoppingList.css'

interface Props {
  shoppingList: ClientShoppingList
  viewingWeek: string
}

export default function ShoppingList({ shoppingList, viewingWeek }: Props) {
  const [hideOwned, setHideOwned] = useState(false)
  const [shoppingConfirm, setShoppingConfirm] = useState(false)
  const [syncing, setSyncing] = useState<'shopping' | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [syncSuccess, setSyncSuccess] = useState<string | null>(null)

  const { items, unavailableRecipes } = shoppingList
  const visibleItems = hideOwned ? items.filter(i => !i.owned) : items
  const ownedCount = items.filter(i => i.owned).length

  const dateRange = viewingWeek ? isoWeekToDateRange(viewingWeek) : ''

  const doShoppingSync = async () => {
    setShoppingConfirm(false)
    setSyncing('shopping')
    setSyncError(null)
    setSyncSuccess(null)
    try {
      await api.syncShopping()
      setSyncSuccess('Shopping list synced to Cookidoo.')
    } catch (e) {
      setSyncError(`Shopping sync failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSyncing(null)
    }
  }

  return (
    <div className="shopping">
      <div className="shopping__header">
        <div className="shopping__title-row">
          <h2 className="shopping__title">Shopping List</h2>
          {viewingWeek && <span className="shopping__week">{dateRange}</span>}
        </div>

        <div className="shopping__actions">
          <label className="shopping__owned-toggle">
            <input
              type="checkbox"
              checked={hideOwned}
              onChange={e => setHideOwned(e.target.checked)}
            />
            Hide owned ({ownedCount})
          </label>

          <button
            className="shopping__sync-btn shopping__sync-btn--primary"
            onClick={() => setShoppingConfirm(true)}
            disabled={syncing !== null}
          >
            {syncing === 'shopping' ? 'Syncing…' : 'Sync to Cookidoo'}
          </button>
        </div>
      </div>

      {/* Sync note */}
      <p className="shopping__sync-note">
        Cookidoo sync uses default servings (lunch = 2, dinner = 4).
      </p>

      {/* Unavailable recipes warning */}
      {unavailableRecipes.length > 0 && (
        <div className="shopping__warning" role="alert">
          <strong>Some recipes could not supply ingredients:</strong>{' '}
          {unavailableRecipes.join(', ')}.
          These are not in the cache — refresh the recipe cache or remove them from the plan.
        </div>
      )}

      {/* Sync feedback */}
      {syncError && (
        <div className="shopping__alert shopping__alert--error" role="alert">
          {syncError}
          <button className="shopping__alert-close" onClick={() => setSyncError(null)}>×</button>
        </div>
      )}
      {syncSuccess && (
        <div className="shopping__alert shopping__alert--success" role="status">
          {syncSuccess}
          <button className="shopping__alert-close" onClick={() => setSyncSuccess(null)}>×</button>
        </div>
      )}

      {shoppingConfirm && (
        <div className="shopping__confirm" role="dialog" aria-modal="true">
          <p>
            Sync shopping list to Cookidoo? This will <strong>replace</strong> your
            current Cookidoo shopping list with ingredients for this week's recipes.
            Pantry-matched items will be marked as owned.
          </p>
          <div className="shopping__confirm-actions">
            <button className="shopping__sync-btn shopping__sync-btn--primary" onClick={doShoppingSync}>
              Confirm
            </button>
            <button className="shopping__sync-btn" onClick={() => setShoppingConfirm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Item list */}
      <div className="shopping__list">
        {items.length === 0 && (
          <p className="shopping__empty">
            No ingredients yet. Add recipes to the week plan to build your shopping list.
          </p>
        )}
        {visibleItems.map((item, i) => (
          <div
            key={i}
            className={`shopping__item${item.owned ? ' shopping__item--owned' : ''}`}
          >
            <span className="shopping__item-name">{normaliseIngredientName(item.name)}</span>
            {item.quantity != null && (
              <span className="shopping__item-qty">
                {Number.isInteger(item.quantity)
                  ? item.quantity
                  : item.quantity.toFixed(1)}
                {item.unit ? ` ${item.unit}` : ''}
              </span>
            )}
            {item.owned && <span className="shopping__item-owned-badge">✔ have it</span>}
            <span className="shopping__item-sources" title={item.recipeSources.join(', ')}>
              {item.recipeSources.length === 1
                ? item.recipeSources[0]
                : `${item.recipeSources.length} recipes`}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
