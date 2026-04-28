import {
  Document,
  Page,
  StyleSheet,
  Text,
  View,
} from '@react-pdf/renderer'
import { normaliseIngredientName } from '../utils/normalise'
import { ClientShoppingItem, PantryItem, RecipeDetails, WeekSlot } from '../api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WeekPlanPDFProps {
  viewingWeek: string
  weekSlots: WeekSlot[]
  pantryItems: PantryItem[]
  shoppingItems: ClientShoppingItem[]
  recipeDetails: Map<string, RecipeDetails>
}

// ---------------------------------------------------------------------------
// ISO week helpers (no DOM APIs)
// ---------------------------------------------------------------------------

function isoWeekToDates(isoWeek: string): Date[] {
  const [yearStr, weekStr] = isoWeek.split('-W')
  const year = Number(yearStr)
  const week = Number(weekStr)
  const jan4 = new Date(year, 0, 4)
  const jan4Dow = jan4.getDay() === 0 ? 7 : jan4.getDay()
  const startOfWeek = new Date(jan4)
  startOfWeek.setDate(jan4.getDate() - (jan4Dow - 1) + (week - 1) * 7)
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(startOfWeek)
    d.setDate(startOfWeek.getDate() + i)
    return d
  })
}

function formatDayHeader(d: Date): string {
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

function formatDateRange(isoWeek: string): string {
  const dates = isoWeekToDates(isoWeek)
  const first = dates[0]!
  const last = dates[6]!
  const firstDay = first.getDate()
  const lastDay = last.getDate()
  const firstMonth = first.toLocaleDateString('en-GB', { month: 'long' })
  const lastMonth = last.toLocaleDateString('en-GB', { month: 'long' })
  const year = last.getFullYear()
  if (firstMonth === lastMonth) {
    return `${firstDay}\u2013${lastDay} ${lastMonth} ${year}`
  }
  return `${firstDay} ${firstMonth}\u2013${lastDay} ${lastMonth} ${year}`
}

function formatToday(): string {
  return new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const ACCENT = '#1a7f64'
const GREY = '#6b7280'
const LIGHT_GREY = '#e5e7eb'
const ALT_ROW = '#f8f9fa'

const styles = StyleSheet.create({
  // ---- shared ----
  footer: {
    position: 'absolute',
    bottom: 36,
    right: 54,
    fontSize: 8,
    color: GREY,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    marginBottom: 6,
  },
  headerTitle: {
    fontSize: 16,
    fontFamily: 'Helvetica-Bold',
    color: ACCENT,
  },
  headerRight: {
    fontSize: 12,
    color: GREY,
  },
  rule: {
    borderBottomWidth: 1,
    borderBottomColor: ACCENT,
    marginBottom: 10,
  },

  // ---- page 1 ----
  page1: {
    paddingHorizontal: 54,
    paddingTop: 54,
    paddingBottom: 54,
    fontFamily: 'Helvetica',
  },
  gridRow: {
    flexDirection: 'row',
  },
  rowLabelCol: {
    width: 40,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 4,
  },
  rowLabel: {
    fontSize: 9,
    color: GREY,
  },
  dayHeader: {
    flex: 1,
    textAlign: 'center',
    fontSize: 10,
    fontFamily: 'Helvetica-Bold',
    color: ACCENT,
    paddingVertical: 4,
    borderWidth: 0.5,
    borderColor: LIGHT_GREY,
  },
  cell: {
    flex: 1,
    borderWidth: 0.5,
    borderColor: LIGHT_GREY,
    padding: 4,
    minHeight: 60,
  },
  cellEmpty: {
    flex: 1,
    borderWidth: 0.5,
    borderColor: LIGHT_GREY,
    padding: 4,
    minHeight: 60,
    backgroundColor: '#f3f4f6',
  },
  cellName: {
    fontSize: 9,
    fontFamily: 'Helvetica-Bold',
    marginBottom: 2,
  },
  cellMeta: {
    fontSize: 8,
    color: GREY,
  },
  customPill: {
    fontSize: 7,
    color: '#7c3aed',
    borderWidth: 0.5,
    borderColor: '#7c3aed',
    borderRadius: 4,
    paddingHorizontal: 3,
    paddingVertical: 1,
    alignSelf: 'flex-start',
    marginTop: 2,
  },

  // ---- page 2 ----
  page2: {
    paddingHorizontal: 54,
    paddingTop: 54,
    paddingBottom: 54,
    fontFamily: 'Helvetica',
  },
  shopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 4,
    paddingHorizontal: 6,
  },
  shopRowAlt: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 4,
    paddingHorizontal: 6,
    backgroundColor: ALT_ROW,
  },
  shopName: {
    fontSize: 10,
    flex: 1,
  },
  shopQty: {
    fontSize: 10,
    color: GREY,
    textAlign: 'right',
  },
  emptyMsg: {
    fontSize: 10,
    color: GREY,
    fontFamily: 'Helvetica-Oblique',
    marginTop: 12,
  },
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatQty(qty: number | null, unit: string | null): string {
  if (qty == null && unit == null) return ''
  if (qty == null) return unit ?? ''
  const rounded = Math.round(qty * 100) / 100
  return unit ? `${rounded} ${unit}` : String(rounded)
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function WeekPlanPDF({
  viewingWeek,
  weekSlots,
  shoppingItems,
  recipeDetails,
}: WeekPlanPDFProps) {
  const dates = isoWeekToDates(viewingWeek)
  const dateRange = formatDateRange(viewingWeek)
  const today = formatToday()

  // Build slot lookup: (day, meal) → WeekSlot
  const slotMap = new Map<string, WeekSlot>()
  for (const s of weekSlots) {
    if (s.recipe_id) slotMap.set(`${s.day}|${s.meal}`, s)
  }

  // Shopping: unowned items, alphabetical by normalised name
  const unowned = shoppingItems
    .filter(item => !item.owned)
    .slice()
    .sort((a, b) =>
      normaliseIngredientName(a.name).localeCompare(normaliseIngredientName(b.name))
    )

  return (
    <Document>
      {/* ------------------------------------------------------------------ */}
      {/* PAGE 1 — Week grid (landscape Letter)                               */}
      {/* ------------------------------------------------------------------ */}
      <Page size="LETTER" orientation="landscape" style={styles.page1}>
        {/* Header */}
        <View style={styles.headerRow}>
          <Text style={styles.headerTitle}>Weekly Meal Plan</Text>
          <Text style={styles.headerRight}>{dateRange}</Text>
        </View>
        <View style={styles.rule} />

        {/* Column headers row */}
        <View style={styles.gridRow}>
          {/* spacer for row-label column */}
          <View style={styles.rowLabelCol} />
          {dates.map((d, i) => (
            <Text key={i} style={styles.dayHeader}>
              {formatDayHeader(d)}
            </Text>
          ))}
        </View>

        {/* Lunch row */}
        <View style={styles.gridRow}>
          <View style={styles.rowLabelCol}>
            <Text style={styles.rowLabel}>Lunch</Text>
          </View>
          {dates.map((_, dayIdx) => {
            const s = slotMap.get(`${dayIdx}|0`)
            if (!s) return <View key={dayIdx} style={styles.cellEmpty} />
            const r = s.recipe_id ? recipeDetails.get(s.recipe_id) : undefined
            const isCustom = r?.recipe_type === 'local_custom' || s.recipe_type === 'local_custom' || s.recipe_type === 'custom'
            return (
              <View key={dayIdx} style={styles.cell}>
                <Text style={styles.cellName}>
                  {r?.name ?? s.recipe_id ?? ''}
                </Text>
                {r?.cooking_time != null && (
                  <Text style={styles.cellMeta}>{r.cooking_time} min</Text>
                )}
                {r?.servings != null && (
                  <Text style={styles.cellMeta}>{r.servings} people</Text>
                )}
                {isCustom && <Text style={styles.customPill}>Custom</Text>}
              </View>
            )
          })}
        </View>

        {/* Dinner row */}
        <View style={styles.gridRow}>
          <View style={styles.rowLabelCol}>
            <Text style={styles.rowLabel}>Dinner</Text>
          </View>
          {dates.map((_, dayIdx) => {
            const s = slotMap.get(`${dayIdx}|1`)
            if (!s) return <View key={dayIdx} style={styles.cellEmpty} />
            const r = s.recipe_id ? recipeDetails.get(s.recipe_id) : undefined
            const isCustom = r?.recipe_type === 'local_custom' || s.recipe_type === 'local_custom' || s.recipe_type === 'custom'
            return (
              <View key={dayIdx} style={styles.cell}>
                <Text style={styles.cellName}>
                  {r?.name ?? s.recipe_id ?? ''}
                </Text>
                {r?.cooking_time != null && (
                  <Text style={styles.cellMeta}>{r.cooking_time} min</Text>
                )}
                {r?.servings != null && (
                  <Text style={styles.cellMeta}>{r.servings} people</Text>
                )}
                {isCustom && <Text style={styles.customPill}>Custom</Text>}
              </View>
            )
          })}
        </View>

        <Text style={styles.footer}>Generated {today}</Text>
      </Page>

      {/* ------------------------------------------------------------------ */}
      {/* PAGE 2 — Shopping list (portrait Letter)                            */}
      {/* ------------------------------------------------------------------ */}
      <Page size="LETTER" orientation="portrait" style={styles.page2}>
        {/* Header */}
        <View style={styles.headerRow}>
          <Text style={styles.headerTitle}>Shopping List</Text>
        </View>
        <Text style={{ fontSize: 11, color: GREY, marginBottom: 6 }}>
          Week of {dateRange}
        </Text>
        <View style={styles.rule} />

        {unowned.length === 0 ? (
          <Text style={styles.emptyMsg}>
            All ingredients are already in your pantry.
          </Text>
        ) : (
          unowned.map((item, idx) => (
            <View key={idx} style={idx % 2 === 0 ? styles.shopRow : styles.shopRowAlt}>
              <Text style={styles.shopName}>
                {normaliseIngredientName(item.name)}
              </Text>
              <Text style={styles.shopQty}>
                {formatQty(item.quantity, item.unit)}
              </Text>
            </View>
          ))
        )}

        <Text style={styles.footer}>Generated {today}</Text>
      </Page>
    </Document>
  )
}
