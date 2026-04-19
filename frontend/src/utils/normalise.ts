// Longest-first so compound forms match before their prefixes.
export const PREPOSITIONS = [
  "dell'", "d'",
  'de la ', 'de las ', 'de los ',
  'delle ', 'della ', 'dello ', 'degli ', 'dei ',
  'del ', 'di ', 'de ',
]

/** Strip language prepositions and capitalise for display. Display-only — not for pantry matching. */
export function normaliseIngredientName(raw: string): string {
  const lower = raw.toLowerCase().trim()

  let stripped = lower
  for (const prep of PREPOSITIONS) {
    if (lower.startsWith(prep)) {
      const candidate = lower.slice(prep.length).trim()
      if (candidate.length > 0) {
        stripped = candidate
      }
      break
    }
  }

  return stripped.charAt(0).toUpperCase() + stripped.slice(1)
}
