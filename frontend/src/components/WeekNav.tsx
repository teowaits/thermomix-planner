import { useState } from 'react'
import { api, isoWeekLabel, isoWeekToDateRange } from '../api'
import './WeekNav.css'

interface Props {
  viewingWeek: string
  currentWeek: string
  nextWeek: string
  onWeekChange: (week: string) => void
  onExportPDF?: () => Promise<void>
}

export default function WeekNav({ viewingWeek, currentWeek, nextWeek, onWeekChange, onExportPDF }: Props) {
  const canGoPrev = viewingWeek === nextWeek
  const canGoNext = viewingWeek === currentWeek

  const [confirm, setConfirm] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<{ ok: boolean; msg: string } | null>(null)
  const [exporting, setExporting] = useState(false)

  const handleExportPDF = async () => {
    if (!onExportPDF || exporting) return
    setExporting(true)
    try {
      await onExportPDF()
    } finally {
      setExporting(false)
    }
  }

  const dateRange = isoWeekToDateRange(viewingWeek)

  const doCalendarSync = async () => {
    setConfirm(false)
    setSyncing(true)
    setSyncResult(null)
    try {
      await api.syncCalendar()
      setSyncResult({ ok: true, msg: 'Recipes sent to Thermomix calendar.' })
    } catch (e) {
      setSyncResult({ ok: false, msg: `Failed: ${e instanceof Error ? e.message : String(e)}` })
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="week-nav">
      <button
        className="week-nav__btn"
        onClick={() => canGoPrev && onWeekChange(currentWeek)}
        disabled={!canGoPrev}
        aria-label="Previous week"
      >
        ←
      </button>

      <div className="week-nav__label">
        <span className="week-nav__week">{isoWeekLabel(viewingWeek)}</span>
        {viewingWeek === currentWeek && <span className="week-nav__badge">Current</span>}
        {viewingWeek === nextWeek && <span className="week-nav__badge week-nav__badge--next">Next</span>}
      </div>

      <button
        className="week-nav__btn"
        onClick={() => canGoNext && onWeekChange(nextWeek)}
        disabled={!canGoNext}
        aria-label="Next week"
      >
        →
      </button>

      <button
        className="week-nav__sync-btn"
        onClick={() => { setSyncResult(null); setConfirm(true) }}
        disabled={syncing}
        title={`Send ${dateRange} to Thermomix`}
      >
        {syncing ? 'Sending…' : 'Send to Thermomix'}
      </button>

      {onExportPDF && (
        <button
          className="week-nav__export-btn"
          onClick={handleExportPDF}
          disabled={exporting}
          title="Download week plan as PDF"
        >
          {exporting ? 'Generating…' : '⬇ Export PDF'}
        </button>
      )}

      {syncResult && (
        <span className={`week-nav__sync-result${syncResult.ok ? '' : ' week-nav__sync-result--error'}`}>
          {syncResult.msg}
          <button className="week-nav__sync-dismiss" onClick={() => setSyncResult(null)} aria-label="Dismiss">×</button>
        </span>
      )}

      {confirm && (
        <div className="week-nav__confirm" role="dialog" aria-modal="true">
          <p>
            Send <strong>{dateRange}</strong> to Thermomix?
            Recipes will be added to the Cookidoo calendar on their respective days.
            Days already in the past will still be sent.
          </p>
          <div className="week-nav__confirm-actions">
            <button className="week-nav__confirm-btn week-nav__confirm-btn--primary" onClick={doCalendarSync}>
              Confirm
            </button>
            <button className="week-nav__confirm-btn" onClick={() => setConfirm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
