import './TimeSlider.css'

// Slider range: 5–120 min in steps of 5.
// Value 120 is treated as "Any" — no max_time filter applied.
const MIN = 5
const MAX = 120
const STEP = 5
export const ANY_SENTINEL = MAX  // exported so callers can compare

interface Props {
  value: number   // minutes; ANY_SENTINEL = no filter
  onChange: (value: number) => void
  label?: string  // optional prefix label, e.g. "Max time"
}

export default function TimeSlider({ value, onChange, label }: Props) {
  const displayLabel = value >= ANY_SENTINEL ? 'Any time' : `≤ ${value} min`

  return (
    <div className="time-slider">
      {label && <span className="time-slider__label">{label}</span>}
      <input
        type="range"
        className="time-slider__input"
        min={MIN}
        max={MAX}
        step={STEP}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        aria-label={label ?? 'Maximum cooking time'}
        aria-valuetext={displayLabel}
      />
      <span className="time-slider__value">{displayLabel}</span>
    </div>
  )
}

/** Convert slider value to the API max_time param (undefined = no filter). */
export function sliderToMaxTime(value: number): number | undefined {
  return value >= ANY_SENTINEL ? undefined : value
}
