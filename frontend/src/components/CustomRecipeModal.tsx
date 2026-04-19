import { useEffect, useRef, useState } from 'react'
import { api, CustomRecipeBody, Ingredient, RecipeDetails } from '../api'
import './CustomRecipeModal.css'

interface Props {
  /** Null = create mode, non-null = edit mode */
  existing?: RecipeDetails
  knownIngredients?: string[]
  onSave: (recipe: RecipeDetails) => void
  onClose: () => void
}

const EMPTY_INGREDIENT: Ingredient = { name: '', quantity: null, unit: null }

export default function CustomRecipeModal({ existing, knownIngredients = [], onSave, onClose }: Props) {
  const [name, setName] = useState(existing?.name ?? '')
  const [servings, setServings] = useState<string>(existing?.servings?.toString() ?? '')
  const [cookingTime, setCookingTime] = useState<string>(existing?.cooking_time?.toString() ?? '')
  const [sourceUrl, setSourceUrl] = useState(existing?.source_url ?? '')
  const [ingredients, setIngredients] = useState<Ingredient[]>(
    existing?.ingredients.length ? [...existing.ingredients] : [{ ...EMPTY_INGREDIENT }]
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    nameRef.current?.focus()
  }, [])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const setIng = (i: number, field: keyof Ingredient, val: string) => {
    setIngredients(prev => {
      const next = [...prev]
      if (field === 'quantity') {
        const n = parseFloat(val)
        next[i] = { ...next[i], quantity: isNaN(n) ? null : n }
      } else {
        next[i] = { ...next[i], [field]: val || null }
      }
      return next
    })
  }

  const addIngredient = () => setIngredients(prev => [...prev, { ...EMPTY_INGREDIENT }])
  const removeIngredient = (i: number) =>
    setIngredients(prev => prev.length > 1 ? prev.filter((_, j) => j !== i) : prev)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setError('Recipe name is required.'); return }

    setSaving(true)
    setError(null)
    const body: CustomRecipeBody = {
      name: name.trim(),
      servings: servings ? parseInt(servings, 10) : null,
      cooking_time: cookingTime ? parseInt(cookingTime, 10) : null,
      source_url: sourceUrl.trim() || null,
      ingredients: ingredients.filter(i => i.name.trim()),
    }
    try {
      const saved = existing
        ? await api.updateCustomRecipe(existing.id, body)
        : await api.createCustomRecipe(body)
      onSave(saved)
    } catch {
      setError('Failed to save recipe. Please try again.')
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className="modal__header">
          <h2 className="modal__title">{existing ? 'Edit recipe' : 'New custom recipe'}</h2>
          <button className="modal__close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <form className="modal__body" onSubmit={handleSubmit} noValidate>
          <label className="modal__field">
            <span className="modal__label">Name <span aria-hidden>*</span></span>
            <input
              ref={nameRef}
              className="modal__input"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Recipe name"
              required
            />
          </label>

          <div className="modal__row">
            <label className="modal__field modal__field--half">
              <span className="modal__label">Servings</span>
              <input
                className="modal__input"
                type="number"
                min={1}
                value={servings}
                onChange={e => setServings(e.target.value)}
                placeholder="e.g. 4"
              />
            </label>
            <label className="modal__field modal__field--half">
              <span className="modal__label">Time (min)</span>
              <input
                className="modal__input"
                type="number"
                min={1}
                value={cookingTime}
                onChange={e => setCookingTime(e.target.value)}
                placeholder="e.g. 30"
              />
            </label>
          </div>

          <label className="modal__field">
            <span className="modal__label">Source URL (optional)</span>
            <input
              className="modal__input"
              type="url"
              value={sourceUrl}
              onChange={e => setSourceUrl(e.target.value)}
              placeholder="https://…"
            />
          </label>

          <div className="modal__section-head">
            <span className="modal__label">Ingredients</span>
            <button type="button" className="modal__add-ing" onClick={addIngredient}>+ Add</button>
          </div>

          {knownIngredients.length > 0 && (
            <datalist id="ingredient-suggestions">
              {knownIngredients.map(n => <option key={n} value={n} />)}
            </datalist>
          )}

          <div className="modal__ingredients">
            {ingredients.map((ing, i) => (
              <div key={i} className="modal__ing-row">
                <input
                  className="modal__input modal__ing-name"
                  value={ing.name}
                  onChange={e => setIng(i, 'name', e.target.value)}
                  placeholder="Name"
                  aria-label={`Ingredient ${i + 1} name`}
                  list={knownIngredients.length > 0 ? 'ingredient-suggestions' : undefined}
                />
                <input
                  className="modal__input modal__ing-qty"
                  type="number"
                  min={0}
                  step="any"
                  value={ing.quantity ?? ''}
                  onChange={e => setIng(i, 'quantity', e.target.value)}
                  placeholder="Qty"
                  aria-label={`Ingredient ${i + 1} quantity`}
                />
                <input
                  className="modal__input modal__ing-unit"
                  value={ing.unit ?? ''}
                  onChange={e => setIng(i, 'unit', e.target.value)}
                  placeholder="Unit"
                  aria-label={`Ingredient ${i + 1} unit`}
                />
                <button
                  type="button"
                  className="modal__ing-remove"
                  onClick={() => removeIngredient(i)}
                  aria-label={`Remove ingredient ${i + 1}`}
                  disabled={ingredients.length === 1}
                >×</button>
              </div>
            ))}
          </div>

          {error && <p className="modal__error" role="alert">{error}</p>}

          <div className="modal__footer">
            <button type="button" className="modal__btn modal__btn--cancel" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="modal__btn modal__btn--save" disabled={saving}>
              {saving ? 'Saving…' : (existing ? 'Save changes' : 'Create recipe')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
