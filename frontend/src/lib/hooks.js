import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'

/**
 * Load JSON from the API with loading and error state.
 * pollMs refreshes silently in the background (used by the live map).
 */
export function useFetch(path, { pollMs = 0, enabled = true } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(Boolean(enabled && path))
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  const load = useCallback(async (silent = false) => {
    if (!path) return
    if (!silent) setLoading(true)
    try {
      const response = await api.get(path)
      if (alive.current) { setData(response.data); setError('') }
    } catch (e) {
      if (alive.current) setError(errorMessage(e))
    } finally {
      if (alive.current && !silent) setLoading(false)
    }
  }, [path])

  useEffect(() => {
    if (!enabled || !path) return undefined
    load()
    if (!pollMs) return undefined
    const id = setInterval(() => load(true), pollMs)
    return () => clearInterval(id)
  }, [load, pollMs, enabled, path])

  return { data, error, loading, reload: load, setData }
}

/** Wrap a mutating API call with busy and error state. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = useCallback(async (fn) => {
    setBusy(true)
    setError('')
    try {
      return await fn()
    } catch (e) {
      setError(errorMessage(e))
      throw e
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, error, setError, run }
}
