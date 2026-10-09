import { useMemo, useState } from 'react'
import { Gauge, Navigation, Search } from 'lucide-react'
import FleetMap from '../components/FleetMap'
import { ErrorBanner, PageHeader, Plate, Spinner, StatusBadge } from '../components/ui'
import { dateTime, timeAgo } from '../lib/format'
import { useFetch } from '../lib/hooks'

function ProgressBar({ value }) {
  if (value === null || value === undefined) return null
  const pct = Math.round(value * 100)
  return (
    <div className="mt-2">
      <div className="h-1.5 overflow-hidden rounded-full bg-surface" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-signal transition-[width] duration-700" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-muted tabular">{pct}% of the way</p>
    </div>
  )
}

export default function Tracking() {
  const live = useFetch('/tracking/live', { pollMs: 3000 })
  const [selectedId, setSelectedId] = useState(null)
  const [query, setQuery] = useState('')
  const [flyTarget, setFlyTarget] = useState(null)

  const vehicles = useMemo(() => live.data || [], [live.data])
  const selected = vehicles.find((v) => v.vehicle_id === selectedId)
  const trail = useFetch(selectedId ? `/vehicles/${selectedId}/history?limit=1000` : null, {
    pollMs: 4000, enabled: Boolean(selectedId),
  })

  const filtered = vehicles.filter((v) => {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return [v.registration_no, v.model, v.driver_name, v.trip?.destination].filter(Boolean)
      .some((s) => s.toLowerCase().includes(q))
  })
  const moving = vehicles.filter((v) => v.trip?.status === 'ACTIVE').length

  const select = (v) => {
    setSelectedId(v.vehicle_id)
    if (v.location) setFlyTarget([v.location.latitude, v.location.longitude])
  }

  return (
    <>
      <PageHeader
        title="Live tracking"
        description={`${moving} of ${vehicles.length} vehicles on the road. Positions refresh every 3 seconds.`}
      />
      <p className="-mt-3 mb-4 inline-block rounded-sm border-l-[3px] border-route bg-route-tint px-3 py-1.5 text-sm text-route">
        Positions are simulated in software. No GPS hardware is connected.
      </p>
      <ErrorBanner message={live.error} onRetry={live.reload} />

      <div className="mt-2 grid gap-4 lg:grid-cols-[320px_1fr]">
        <aside className="flex max-h-[70vh] flex-col overflow-hidden rounded-lg border border-line bg-white lg:h-[640px] lg:max-h-none">
          <label className="relative border-b border-line p-3">
            <span className="sr-only">Find a vehicle</span>
            <Search className="absolute left-6 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Plate, driver or destination"
                   className="h-9 w-full rounded-md border border-line pl-9 pr-3 text-sm focus:border-route focus:outline-none focus:ring-2 focus:ring-route/20" />
          </label>
          {live.loading && !live.data ? <Spinner /> : (
            <ul className="flex-1 divide-y divide-line overflow-y-auto">
              {filtered.map((v) => (
                <li key={v.vehicle_id}>
                  <button type="button" onClick={() => select(v)}
                          className={`w-full px-4 py-3 text-left hover:bg-surface ${v.vehicle_id === selectedId ? 'bg-hw-tint' : ''}`}>
                    <div className="flex items-center justify-between gap-2">
                      <Plate reg={v.registration_no} size="sm" />
                      <StatusBadge status={v.trip?.status === 'ACTIVE' ? 'ACTIVE' : v.status}
                                   label={v.trip?.status === 'ACTIVE' ? 'Moving' : undefined} />
                    </div>
                    <p className="mt-1.5 text-sm">{v.trip ? `To ${v.trip.destination}` : v.model}</p>
                    <p className="text-xs text-muted">{v.driver_name || 'No driver assigned'}, updated {timeAgo(v.location?.recorded_at)}</p>
                  </button>
                </li>
              ))}
              {filtered.length === 0 && <li className="px-4 py-8 text-center text-sm text-muted">No vehicles match "{query}".</li>}
            </ul>
          )}
        </aside>

        <div className="relative h-[480px] overflow-hidden rounded-lg border border-line lg:h-[640px]">
          <FleetMap vehicles={vehicles} selectedId={selectedId} onSelect={(id) => setSelectedId(id)}
                    trail={selectedId ? trail.data : null} flyTarget={flyTarget} />

          {selected && (
            <div className="absolute bottom-3 left-3 right-3 z-[500] rounded-lg border border-line bg-white p-4 shadow-lg sm:right-auto sm:w-80">
              <div className="flex items-start justify-between gap-2">
                <Plate reg={selected.registration_no} />
                <button type="button" onClick={() => setSelectedId(null)} className="text-sm text-muted hover:text-asphalt">Close</button>
              </div>
              <p className="mt-2 font-semibold">{selected.model}</p>
              <p className="text-sm text-muted">{selected.driver_name || 'No driver assigned'}</p>
              {selected.trip ? (
                <div className="mt-3 text-sm">
                  <p className="flex items-center gap-1.5"><Navigation className="size-4 text-hw" aria-hidden />
                    {selected.trip.source} to {selected.trip.destination}</p>
                  <ProgressBar value={selected.trip.progress} />
                </div>
              ) : <p className="mt-3 text-sm text-muted">Not on a trip.</p>}
              {selected.location && (
                <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-line pt-3 text-sm">
                  <div><dt className="text-muted">Speed</dt>
                    <dd className="flex items-center gap-1 font-semibold tabular"><Gauge className="size-4" aria-hidden />{selected.location.speed_kmh} km/h</dd></div>
                  <div><dt className="text-muted">Last update</dt><dd className="font-semibold tabular">{dateTime(selected.location.recorded_at)}</dd></div>
                  <div className="col-span-2 text-xs text-muted tabular">
                    {selected.location.latitude.toFixed(5)}, {selected.location.longitude.toFixed(5)}
                    {selected.location.is_simulated && ' (simulated)'}
                  </div>
                </dl>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
