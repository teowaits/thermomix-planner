import { useEffect, useRef, useState } from 'react'
import { api, CacheStatus as CacheStatusType } from '../api'
import './CacheStatus.css'

const POLL_INTERVAL_MS = 2000

export default function CacheStatus() {
  const [status, setStatus] = useState<CacheStatusType | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const fetchStatus = async () => {
    try {
      const s = await api.getCacheStatus()
      setStatus(s)
      if (s.state !== 'running') stopPolling()
    } catch {
      // silent — backend may not be up yet
    }
  }

  useEffect(() => {
    fetchStatus()
    return stopPolling
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const startPolling = () => {
    stopPolling()
    pollRef.current = setInterval(fetchStatus, POLL_INTERVAL_MS)
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    setDismissed(false)
    try {
      await api.startCacheRefresh()
    } catch (e: unknown) {
      // 409 = already running — that's fine, just start polling
      if (!(e instanceof Error && e.message.includes('409'))) {
        setRefreshing(false)
        return
      }
    }
    startPolling()
    await fetchStatus()
    setRefreshing(false)
  }

  const handleRetry = async () => {
    setRetrying(true)
    setDismissed(false)
    try {
      await api.retryCacheFailed()
    } catch (e: unknown) {
      if (!(e instanceof Error && e.message.includes('409'))) {
        setRetrying(false)
        return
      }
    }
    startPolling()
    await fetchStatus()
    setRetrying(false)
  }

  if (!status) return null

  const { state, progress, last_refreshed, error, recipe_count, unavailable_count } = status
  const isRunning = state === 'running'
  const isDone = state === 'done'
  const isError = state === 'error'
  // Truly empty: no recipes in DB at all (not just a restarted server)
  const isEmpty = recipe_count === 0

  // After dismiss: hide banner unless something actionable happens
  if (!isRunning && !isError && !isEmpty && dismissed) return null

  // Show the quiet status bar when we have recipes and nothing is happening
  if (!isRunning && !isError && !isDone && !isEmpty) {
    return (
      <div className="cache-status cache-status--quiet">
        <span className="cache-status__meta">
          {recipe_count.toLocaleString()} recipes cached
          {unavailable_count > 0 && ` · ${unavailable_count} failed`}
          {last_refreshed
            ? ` · last updated ${new Date(last_refreshed).toLocaleString()}`
            : ' · server restarted (refresh date unknown)'}
        </span>
        {unavailable_count > 0 && (
          <button
            className="cache-status__retry-btn"
            onClick={handleRetry}
            disabled={retrying}
            title="Re-fetch the recipes that failed during the last refresh (~90 s)"
          >
            {retrying ? 'Starting…' : `Retry ${unavailable_count} failed`}
          </button>
        )}
        <button
          className="cache-status__refresh-btn"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          {refreshing ? 'Starting…' : 'Refresh cache'}
        </button>
      </div>
    )
  }

  return (
    <div
      className={`cache-status cache-status--banner${isError ? ' cache-status--error' : ''}`}
      role="status"
    >
      <div className="cache-status__body">
        {isRunning && (
          <>
            <span className="cache-status__text">
              {progress.total === 0
                ? 'Scanning collections…'
                : `Caching recipes: ${progress.done.toLocaleString()} / ${progress.total.toLocaleString()}`}
            </span>
            {progress.total === 0 ? (
              <div className="cache-status__spinner" aria-label="Loading" />
            ) : (
              <div className="cache-status__bar-track">
                <div
                  className="cache-status__bar-fill"
                  style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }}
                />
              </div>
            )}
          </>
        )}

        {isEmpty && !isRunning && !isError && (
          <>
            <span className="cache-status__text">
              No recipes cached yet — click Refresh to load your Cookidoo library (~6 min).
            </span>
            <button
              className="cache-status__refresh-btn"
              onClick={handleRefresh}
              disabled={refreshing}
            >
              {refreshing ? 'Starting…' : 'Refresh now'}
            </button>
          </>
        )}

        {isDone && (
          <>
            <span className="cache-status__text">
              {recipe_count.toLocaleString()} recipes cached
              {unavailable_count > 0 ? `, ${unavailable_count} failed.` : '.'}
              {last_refreshed && ` Updated ${new Date(last_refreshed).toLocaleTimeString()}.`}
            </span>
            {unavailable_count > 0 && (
              <button
                className="cache-status__retry-btn"
                onClick={handleRetry}
                disabled={retrying}
                title="Re-fetch the recipes that failed during this refresh (~90 s)"
              >
                {retrying ? 'Starting…' : `Retry ${unavailable_count} failed`}
              </button>
            )}
            <button
              className="cache-status__refresh-btn"
              onClick={handleRefresh}
              disabled={refreshing}
            >
              Refresh again
            </button>
          </>
        )}

        {isError && (
          <>
            <span className="cache-status__text">
              Cache refresh failed{error ? `: ${error}` : ''}
              {recipe_count > 0 ? ` — ${recipe_count.toLocaleString()} previously cached recipes still available.` : '.'}
            </span>
            <button
              className="cache-status__refresh-btn cache-status__refresh-btn--error"
              onClick={handleRefresh}
              disabled={refreshing}
            >
              Retry
            </button>
          </>
        )}
      </div>

      {(isDone || isError) && (
        <button
          className="cache-status__dismiss"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss"
        >
          ×
        </button>
      )}
    </div>
  )
}
