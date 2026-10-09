import { useMemo, useState } from 'react'
import { Ban, Flag, Play, Plus } from 'lucide-react'
import DataTable from '../components/DataTable'
import {
  Button, ErrorBanner, Modal, PageHeader, Plate, Select, Spinner, StatusBadge, Tabs, Textarea, useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime, km } from '../lib/format'
import { useAction, useFetch } from '../lib/hooks'

function CreateTrip({ onClose, onSaved }) {
  const notify = useToast()
  const vehicles = useFetch('/vehicles?status=AVAILABLE')
  const drivers = useFetch('/drivers?status=AVAILABLE')
  const places = useFetch('/places')
  const { busy, error, run } = useAction()
  const [form, setForm] = useState({ vehicle_id: '', driver_id: '', source_place_id: '', destination_place_id: '', notes: '' })

  const pickVehicle = (e) => {
    const id = e.target.value
    const vehicle = vehicles.data?.find((v) => String(v.id) === id)
    const regular = vehicle?.current_driver?.id
    const regularAvailable = drivers.data?.some((d) => d.id === regular)
    // Pre-fill the vehicle's regular driver when they are free.
    setForm((f) => ({ ...f, vehicle_id: id, driver_id: regularAvailable ? String(regular) : f.driver_id }))
  }
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    try {
      const { data } = await run(() => api.post('/trips', {
        ...form, vehicle_id: Number(form.vehicle_id), driver_id: Number(form.driver_id), notes: form.notes || null,
      }))
      notify(`Trip #${data.id} scheduled`)
      onSaved()
    } catch { /* shown */ }
  }

  const loading = vehicles.loading || drivers.loading || places.loading
  const placeOptions = (places.data || []).map((p) => ({ value: p.id, label: p.name }))

  return (
    <Modal open title="Schedule a trip" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="trip-form" busy={busy}>Schedule trip</Button></>}>
      {loading ? <Spinner /> : (
        <form id="trip-form" onSubmit={submit} className="flex flex-col gap-4">
          <ErrorBanner message={error || vehicles.error || drivers.error} />
          <Select label="Vehicle" required placeholder="Choose an available vehicle" value={form.vehicle_id} onChange={pickVehicle}
                  options={(vehicles.data || []).map((v) => ({ value: String(v.id), label: `${v.registration_no}, ${v.model}` }))}
                  hint={vehicles.data?.length === 0 ? 'No vehicles are available right now.' : undefined} />
          <Select label="Driver" required placeholder="Choose an available driver" value={form.driver_id} onChange={set('driver_id')}
                  options={(drivers.data || []).map((d) => ({ value: String(d.id), label: d.name }))}
                  hint="Drivers with an expired licence are refused when you schedule." />
          <div className="grid gap-4 sm:grid-cols-2">
            <Select label="From" required placeholder="Choose" value={form.source_place_id} onChange={set('source_place_id')} options={placeOptions} />
            <Select label="To" required placeholder="Choose" value={form.destination_place_id} onChange={set('destination_place_id')}
                    options={placeOptions.map((o) => ({ ...o, disabled: o.value === form.source_place_id }))} />
          </div>
          <Textarea label="Notes" maxLength={500} value={form.notes} onChange={set('notes')} placeholder="Optional" />
          <p className="text-sm text-muted">
            Scheduling locks the vehicle and driver in one database transaction, so nobody else can book them at the same moment.
          </p>
        </form>
      )}
    </Modal>
  )
}

const TABS = [
  { value: 'open', label: 'Open', statuses: ['SCHEDULED', 'ACTIVE'] },
  { value: 'COMPLETED', label: 'Completed', statuses: ['COMPLETED'] },
  { value: 'CANCELLED', label: 'Cancelled', statuses: ['CANCELLED'] },
  { value: 'all', label: 'All', statuses: null },
]

export default function Trips() {
  const { can } = useAuth()
  const notify = useToast()
  const { data, error, loading, reload } = useFetch('/trips?limit=500', { pollMs: 10000 })
  const [tab, setTab] = useState('open')
  const [creating, setCreating] = useState(false)
  const [busyId, setBusyId] = useState(null)

  const counts = useMemo(() => Object.fromEntries(TABS.map((t) => [
    t.value, (data || []).filter((trip) => !t.statuses || t.statuses.includes(trip.status)).length,
  ])), [data])
  const current = TABS.find((t) => t.value === tab)
  const rows = (data || []).filter((t) => !current.statuses || current.statuses.includes(t.status))

  const changeStatus = async (trip, status, verb) => {
    if (status === 'CANCELLED' && !window.confirm(`Cancel trip #${trip.id}? The vehicle and driver become available again.`)) return
    setBusyId(trip.id)
    try {
      await api.patch(`/trips/${trip.id}/status`, { status })
      notify(`Trip #${trip.id} ${verb}`)
      reload(true)
    } catch (e) {
      notify(e.response?.data?.detail || 'Could not update the trip', 'error')
    } finally {
      setBusyId(null)
    }
  }

  const columns = [
    { key: 'id', header: 'Trip', render: (t) => <span className="tabular text-muted">#{t.id}</span> },
    { key: 'vehicle_registration', header: 'Vehicle', render: (t) => <Plate reg={t.vehicle_registration} size="sm" /> },
    { key: 'driver_name', header: 'Driver' },
    { key: 'route', header: 'Route', sortValue: (t) => t.source,
      render: (t) => <span>{t.source} <span className="text-muted">to</span> {t.destination}</span> },
    { key: 'status', header: 'Status', render: (t) => <StatusBadge status={t.status} /> },
    { key: 'start_time', header: 'Started', render: (t) => <span className="tabular whitespace-nowrap">{dateTime(t.start_time)}</span> },
    { key: 'end_time', header: 'Ended', render: (t) => <span className="tabular whitespace-nowrap">{dateTime(t.end_time)}</span> },
    { key: 'distance_km', header: 'Distance', align: 'right', render: (t) => km(t.distance_km) },
    { key: 'actions', header: '', sortable: false, align: 'right', render: (t) => can('MANAGER') && (
      <div className="flex justify-end gap-1">
        {t.status === 'SCHEDULED' && <Button size="sm" variant="secondary" icon={Play} busy={busyId === t.id} onClick={() => changeStatus(t, 'ACTIVE', 'started')}>Start</Button>}
        {t.status === 'ACTIVE' && <Button size="sm" variant="secondary" icon={Flag} busy={busyId === t.id} onClick={() => changeStatus(t, 'COMPLETED', 'completed')}>Complete</Button>}
        {['SCHEDULED', 'ACTIVE'].includes(t.status) &&
          <Button size="sm" variant="ghost" icon={Ban} disabled={busyId === t.id} onClick={() => changeStatus(t, 'CANCELLED', 'cancelled')} aria-label={`Cancel trip ${t.id}`} />}
      </div>
    ) },
  ]

  return (
    <>
      <PageHeader title="Trips" description="Schedule trips, start them, and close them when the vehicle arrives."
        actions={can('MANAGER') && <Button icon={Plus} onClick={() => setCreating(true)}>Schedule trip</Button>} />
      <ErrorBanner message={error} onRetry={reload} />
      <Tabs value={tab} onChange={setTab} tabs={TABS.map((t) => ({ ...t, count: counts[t.value] }))} />
      {loading && !data ? <Spinner /> : (
        <DataTable columns={columns} rows={rows}
          searchText={(t) => `${t.id} ${t.vehicle_registration} ${t.driver_name} ${t.source} ${t.destination}`}
          searchPlaceholder="Search trip, plate, driver or place"
          emptyTitle={tab === 'open' ? 'No open trips' : 'No trips here'}
          emptyText={tab === 'open' ? 'Schedule a trip to put a vehicle on the road.' : undefined} />
      )}
      {creating && <CreateTrip onClose={() => setCreating(false)} onSaved={() => { setCreating(false); reload(true) }} />}
    </>
  )
}
