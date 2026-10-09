import { useState } from 'react'
import { History, Pencil, Plus, Power, UserPlus } from 'lucide-react'
import DataTable from '../components/DataTable'
import {
  Button, ErrorBanner, Input, Modal, PageHeader, Plate, Select, Spinner, StatusBadge, Tabs, useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateOnly, dateTime, km, moneyExact, number, titleCase } from '../lib/format'
import { useAction, useFetch } from '../lib/hooks'

const FUEL_TYPES = ['DIESEL', 'PETROL', 'CNG', 'ELECTRIC', 'HYBRID'].map((v) => ({ value: v, label: titleCase(v) }))
const EDITABLE_STATUS = ['AVAILABLE', 'MAINTENANCE', 'INACTIVE'].map((v) => ({ value: v, label: titleCase(v) }))

function VehicleForm({ vehicle, onClose, onSaved }) {
  const editing = Boolean(vehicle)
  const notify = useToast()
  const { busy, error, run } = useAction()
  const [form, setForm] = useState(() => ({
    registration_no: vehicle?.registration_no || '',
    model: vehicle?.model || '',
    fuel_type: vehicle?.fuel_type || 'DIESEL',
    odometer_km: vehicle ? String(vehicle.odometer_km) : '0',
    status: vehicle?.status || 'AVAILABLE',
  }))
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    try {
      if (editing) {
        const body = { model: form.model, fuel_type: form.fuel_type, odometer_km: form.odometer_km, version: vehicle.version }
        if (vehicle.status !== 'IN_USE') body.status = form.status
        await run(() => api.put(`/vehicles/${vehicle.id}`, body))
        notify('Vehicle updated')
      } else {
        await run(() => api.post('/vehicles', form))
        notify('Vehicle added')
      }
      onSaved()
    } catch { /* error shown in form */ }
  }

  return (
    <Modal open title={editing ? 'Edit vehicle' : 'Add vehicle'} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="vehicle-form" busy={busy}>{editing ? 'Save changes' : 'Add vehicle'}</Button></>}>
      <form id="vehicle-form" onSubmit={submit} className="flex flex-col gap-4">
        <ErrorBanner message={error} />
        {editing ? (
          <div><p className="mb-1.5 text-sm font-semibold">Registration</p><Plate reg={vehicle.registration_no} /></div>
        ) : (
          <Input label="Registration number" required placeholder="UK07AB1234" value={form.registration_no}
                 onChange={set('registration_no')} hint="Spaces and dashes are removed automatically." />
        )}
        <Input label="Make and model" required minLength={2} maxLength={100} value={form.model} onChange={set('model')} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Fuel type" options={FUEL_TYPES} value={form.fuel_type} onChange={set('fuel_type')} />
          <Input label="Odometer (km)" type="number" min="0" step="0.1" required value={form.odometer_km} onChange={set('odometer_km')} />
        </div>
        {editing && (vehicle.status === 'IN_USE'
          ? <p className="text-sm text-muted">Status is set by trips while this vehicle is on the road.</p>
          : <Select label="Status" options={EDITABLE_STATUS} value={form.status} onChange={set('status')}
                    hint="Inactive vehicles leave the map and cannot take trips." />)}
      </form>
    </Modal>
  )
}

function AssignDriver({ vehicle, onClose, onSaved }) {
  const notify = useToast()
  const drivers = useFetch('/drivers')
  const { busy, error, run } = useAction()
  const [driverId, setDriverId] = useState(vehicle.current_driver?.id ? String(vehicle.current_driver.id) : '')

  const options = (drivers.data || []).filter((d) => d.status !== 'INACTIVE').map((d) => ({
    value: String(d.id),
    label: d.assigned_vehicle && d.assigned_vehicle.id !== vehicle.id
      ? `${d.name} (now with ${d.assigned_vehicle.registration_no})` : d.name,
  }))

  const save = async () => {
    try {
      await run(() => api.post(`/vehicles/${vehicle.id}/assign-driver`, { driver_id: driverId ? Number(driverId) : null }))
      notify(driverId ? 'Driver assigned' : 'Driver removed')
      onSaved()
    } catch { /* shown */ }
  }

  return (
    <Modal open title="Assign driver" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={save} busy={busy}>Save assignment</Button></>}>
      <div className="flex flex-col gap-4">
        <Plate reg={vehicle.registration_no} />
        <ErrorBanner message={error || drivers.error} />
        {drivers.loading ? <Spinner /> : (
          <Select label="Regular driver" placeholder="No driver" options={options} value={driverId}
                  onChange={(e) => setDriverId(e.target.value)}
                  hint="A driver can be the regular driver of one vehicle. Choosing someone already assigned moves them here." />
        )}
      </div>
    </Modal>
  )
}

function Records({ vehicle, onClose }) {
  const { data, error, loading } = useFetch(`/vehicles/${vehicle.id}/records`)
  const [tab, setTab] = useState('trips')
  return (
    <Modal open wide title="Vehicle history" onClose={onClose}>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Plate reg={vehicle.registration_no} />
        <span className="text-muted">{vehicle.model}, {km(vehicle.odometer_km)}</span>
      </div>
      <ErrorBanner message={error} />
      {loading || !data ? <Spinner /> : (
        <>
          <Tabs value={tab} onChange={setTab} tabs={[
            { value: 'trips', label: 'Trips', count: data.trips.length },
            { value: 'fuel', label: 'Fuel', count: data.fuel.length },
            { value: 'maintenance', label: 'Service', count: data.maintenance.length },
            { value: 'drivers', label: 'Drivers', count: data.assignments.length },
          ]} />
          <div className="overflow-x-auto text-sm">
            {tab === 'trips' && <SimpleTable rows={data.trips} cols={[
              ['Route', (t) => `${t.source} to ${t.destination}`], ['Driver', (t) => t.driver_name],
              ['Started', (t) => dateTime(t.start_time)], ['Distance', (t) => km(t.distance_km)],
              ['Status', (t) => <StatusBadge status={t.status} />]]} />}
            {tab === 'fuel' && <SimpleTable rows={data.fuel} cols={[
              ['Date', (f) => dateTime(f.recorded_at)], ['Litres', (f) => number(f.quantity_l)],
              ['Cost', (f) => moneyExact(f.total_cost)], ['Odometer', (f) => km(f.odometer_km)]]} />}
            {tab === 'maintenance' && <SimpleTable rows={data.maintenance} cols={[
              ['Date', (m) => dateOnly(m.service_date)], ['Service', (m) => m.service_type],
              ['Cost', (m) => moneyExact(m.cost)], ['Next due', (m) => dateOnly(m.next_service_date)]]} />}
            {tab === 'drivers' && <SimpleTable rows={data.assignments} cols={[
              ['Driver', (a) => a.driver_name], ['From', (a) => dateOnly(a.start_date)],
              ['Until', (a) => (a.end_date ? dateOnly(a.end_date) : 'Current')]]} />}
          </div>
        </>
      )}
    </Modal>
  )
}

function SimpleTable({ rows, cols }) {
  if (!rows.length) return <p className="py-6 text-center text-muted">No records yet.</p>
  return (
    <table className="w-full">
      <thead><tr className="border-b border-line text-left text-muted">{cols.map(([h]) => <th key={h} className="py-2 pr-4 font-semibold">{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={r.id ?? i} className="border-b border-line/70 last:border-0">{cols.map(([h, f]) => <td key={h} className="py-2 pr-4 tabular">{f(r)}</td>)}</tr>
      ))}</tbody>
    </table>
  )
}

export default function Vehicles() {
  const { can } = useAuth()
  const notify = useToast()
  const [status, setStatus] = useState('')
  const { data, error, loading, reload } = useFetch(`/vehicles${status ? `?status=${status}` : ''}`)
  const [modal, setModal] = useState(null) // { type, vehicle }
  const close = () => setModal(null)
  const saved = () => { close(); reload(true) }

  const deactivate = async (v) => {
    if (!window.confirm(`Deactivate ${v.registration_no}? Its history is kept, but it can no longer take trips.`)) return
    try {
      await api.delete(`/vehicles/${v.id}`)
      notify('Vehicle deactivated')
      reload(true)
    } catch (e) {
      notify(e.response?.data?.detail || 'Could not deactivate the vehicle', 'error')
    }
  }

  const columns = [
    { key: 'registration_no', header: 'Registration', render: (v) => <Plate reg={v.registration_no} size="sm" /> },
    { key: 'model', header: 'Model' },
    { key: 'fuel_type', header: 'Fuel', render: (v) => titleCase(v.fuel_type) },
    { key: 'status', header: 'Status', render: (v) => <StatusBadge status={v.status} /> },
    { key: 'driver', header: 'Regular driver', sortValue: (v) => v.current_driver?.name || '',
      render: (v) => v.current_driver?.name || <span className="text-muted">None</span> },
    { key: 'odometer_km', header: 'Odometer', align: 'right', render: (v) => km(v.odometer_km) },
    { key: 'actions', header: '', sortable: false, align: 'right', render: (v) => (
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="ghost" icon={History} onClick={() => setModal({ type: 'records', vehicle: v })} aria-label={`History of ${v.registration_no}`} />
        {can('MANAGER') && v.status !== 'INACTIVE' && <>
          <Button size="sm" variant="ghost" icon={UserPlus} onClick={() => setModal({ type: 'assign', vehicle: v })} aria-label={`Assign driver to ${v.registration_no}`} />
          <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setModal({ type: 'edit', vehicle: v })} aria-label={`Edit ${v.registration_no}`} />
        </>}
        {can('ADMIN') && v.status !== 'INACTIVE' && v.status !== 'IN_USE' &&
          <Button size="sm" variant="ghost" icon={Power} onClick={() => deactivate(v)} aria-label={`Deactivate ${v.registration_no}`} />}
      </div>
    ) },
  ]

  return (
    <>
      <PageHeader title="Vehicles" description="Every vehicle in the fleet, its status and its regular driver."
        actions={can('MANAGER') && <Button icon={Plus} onClick={() => setModal({ type: 'create' })}>Add vehicle</Button>} />
      <ErrorBanner message={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : (
        <DataTable
          columns={columns}
          rows={data || []}
          searchText={(v) => `${v.registration_no} ${v.model} ${v.current_driver?.name || ''}`}
          searchPlaceholder="Search plate, model or driver"
          emptyTitle="No vehicles yet"
          emptyText="Add your first vehicle to start tracking it."
          toolbar={(
            <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status"
                    className="h-9 rounded-md border border-line px-2 text-sm">
              <option value="">All statuses</option>
              {['AVAILABLE', 'IN_USE', 'MAINTENANCE', 'INACTIVE'].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </select>
          )}
        />
      )}
      {modal?.type === 'create' && <VehicleForm onClose={close} onSaved={saved} />}
      {modal?.type === 'edit' && <VehicleForm vehicle={modal.vehicle} onClose={close} onSaved={saved} />}
      {modal?.type === 'assign' && <AssignDriver vehicle={modal.vehicle} onClose={close} onSaved={saved} />}
      {modal?.type === 'records' && <Records vehicle={modal.vehicle} onClose={close} />}
    </>
  )
}
