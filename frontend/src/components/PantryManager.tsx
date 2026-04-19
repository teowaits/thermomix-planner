import { useState } from 'react'
import { api, PantryItem } from '../api'
import './PantryManager.css'

interface Props {
  items: PantryItem[]
  onChange: () => Promise<void>
}

interface EditState {
  id: string
  name: string
  quantity: string
  unit: string
}

export default function PantryManager({ items, onChange }: Props) {
  // Add form
  const [addName, setAddName] = useState('')
  const [addQty, setAddQty] = useState('')
  const [addUnit, setAddUnit] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  // Inline edit
  const [editing, setEditing] = useState<EditState | null>(null)
  const [editError, setEditError] = useState<string | null>(null)

  // Bulk import
  const [bulkText, setBulkText] = useState('')
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = addName.trim()
    if (!name) { setAddError('Name is required'); return }
    setAddError(null)
    try {
      await api.addPantryItem(name, addQty ? parseFloat(addQty) : undefined, addUnit.trim() || undefined)
      setAddName(''); setAddQty(''); setAddUnit('')
      await onChange()
    } catch {
      setAddError('Failed to add item')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.deletePantryItem(id)
      await onChange()
    } catch {
      // Swallow — item may already be gone
    }
  }

  const startEdit = (item: PantryItem) => {
    setEditing({
      id: item.id,
      name: item.name,
      quantity: item.quantity != null ? String(item.quantity) : '',
      unit: item.unit ?? '',
    })
    setEditError(null)
  }

  const handleEditSave = async () => {
    if (!editing) return
    const name = editing.name.trim()
    if (!name) { setEditError('Name is required'); return }
    setEditError(null)
    try {
      await api.updatePantryItem(
        editing.id,
        name,
        editing.quantity ? parseFloat(editing.quantity) : undefined,
        editing.unit.trim() || undefined,
      )
      setEditing(null)
      await onChange()
    } catch {
      setEditError('Failed to save')
    }
  }

  const handleBulkImport = async () => {
    const lines = bulkText.split('\n').map(l => l.trim()).filter(Boolean)
    if (lines.length === 0) { setBulkError('Enter at least one ingredient'); return }
    setBulkError(null)
    try {
      await Promise.all(lines.map(name => api.addPantryItem(name)))
      setBulkText('')
      setBulkOpen(false)
      await onChange()
    } catch {
      setBulkError('Some items failed to import')
    }
  }

  return (
    <div className="pantry">
      <div className="pantry__header">
        <h2 className="pantry__title">Pantry</h2>
        <span className="pantry__count">{items.length} item{items.length !== 1 ? 's' : ''}</span>
        <button
          className="pantry__bulk-toggle"
          onClick={() => setBulkOpen(v => !v)}
        >
          {bulkOpen ? 'Cancel bulk' : 'Bulk import'}
        </button>
      </div>

      {/* Bulk import */}
      {bulkOpen && (
        <div className="pantry__bulk">
          <textarea
            className="pantry__bulk-textarea"
            placeholder={'One ingredient per line:\nflour\nolive oil\neggs'}
            value={bulkText}
            onChange={e => setBulkText(e.target.value)}
            rows={6}
          />
          {bulkError && <p className="pantry__error">{bulkError}</p>}
          <button className="pantry__btn pantry__btn--primary" onClick={handleBulkImport}>
            Import
          </button>
        </div>
      )}

      {/* Add form */}
      <form className="pantry__add-form" onSubmit={handleAdd} noValidate>
        <input
          className="pantry__input pantry__input--name"
          type="text"
          placeholder="Ingredient name"
          value={addName}
          onChange={e => setAddName(e.target.value)}
          aria-label="Ingredient name"
        />
        <input
          className="pantry__input pantry__input--qty"
          type="number"
          placeholder="Qty"
          value={addQty}
          onChange={e => setAddQty(e.target.value)}
          min={0}
          step="any"
          aria-label="Quantity"
        />
        <input
          className="pantry__input pantry__input--unit"
          type="text"
          placeholder="Unit"
          value={addUnit}
          onChange={e => setAddUnit(e.target.value)}
          aria-label="Unit"
        />
        <button type="submit" className="pantry__btn pantry__btn--primary">
          Add
        </button>
        {addError && <p className="pantry__error pantry__error--inline">{addError}</p>}
      </form>

      {/* Item list */}
      <div className="pantry__list">
        {items.length === 0 && (
          <p className="pantry__empty">No pantry items yet. Add ingredients you have at home.</p>
        )}
        {items.map(item => (
          <div key={item.id} className="pantry__item">
            {editing?.id === item.id ? (
              <div className="pantry__edit-row">
                <input
                  className="pantry__input pantry__input--name"
                  value={editing.name}
                  onChange={e => setEditing({ ...editing, name: e.target.value })}
                  aria-label="Edit name"
                />
                <input
                  className="pantry__input pantry__input--qty"
                  type="number"
                  value={editing.quantity}
                  onChange={e => setEditing({ ...editing, quantity: e.target.value })}
                  placeholder="Qty"
                  aria-label="Edit quantity"
                />
                <input
                  className="pantry__input pantry__input--unit"
                  value={editing.unit}
                  onChange={e => setEditing({ ...editing, unit: e.target.value })}
                  placeholder="Unit"
                  aria-label="Edit unit"
                />
                <button className="pantry__btn pantry__btn--primary pantry__btn--sm" onClick={handleEditSave}>
                  Save
                </button>
                <button className="pantry__btn pantry__btn--sm" onClick={() => setEditing(null)}>
                  Cancel
                </button>
                {editError && <p className="pantry__error pantry__error--inline">{editError}</p>}
              </div>
            ) : (
              <>
                <span className="pantry__item-name">{item.name}</span>
                {(item.quantity != null || item.unit) && (
                  <span className="pantry__item-qty">
                    {item.quantity != null ? item.quantity : ''}{item.unit ? ` ${item.unit}` : ''}
                  </span>
                )}
                <div className="pantry__item-actions">
                  <button
                    className="pantry__icon-btn"
                    onClick={() => startEdit(item)}
                    aria-label={`Edit ${item.name}`}
                  >
                    ✎
                  </button>
                  <button
                    className="pantry__icon-btn pantry__icon-btn--delete"
                    onClick={() => handleDelete(item.id)}
                    aria-label={`Delete ${item.name}`}
                  >
                    ×
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
