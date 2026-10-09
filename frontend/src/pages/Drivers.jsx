import { useState } from 'react'
import { History, Pencil, Plus, Power } from 'lucide-react'
import DataTable from '../components/DataTable'
import {
  Button, ErrorBanner, Input, Modal, PageHeader, Plate, Select, Spinner, StatusBadge, useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateOnly, dateTime, km, titleCase } from '../lib/format'
import { useAction, useFetch } from '../lib/hooks'

const EDITABLE_STATUS = ['AVAILABLE', 'OFF_DUTY', 'INACTIVE'].map((v) => ({ value: v, label: titleCase(v) }))

function daysUntil(isoDate) {
  const today = new Date(); today.setHours(0, 0, 0, 0)
  return Math.round((new Date(`${isoDate}T00:00:00`) - today) / 86400000)
}

function LicenceExpiry({ date }) {
  const days = daysUntil(date)
  if (days < 0) return <span className="font-semibold text-stop">Expired {dateOnly(date)}</span>
  if (days <= 30) return <span className="font-semibold text-signal-dark">{dateOnly(date)} ({days} days)</span>
  return <span>{dateOnly(date)}</span>
}

function DriverForm({ driver, onClose, onSaved }) {
  const editing = Boolean(driver)
  const notify = useToast()
  const { busy, error, run } = useAction()
  const [form, setForm] = useState(() => ({
    name: driver?.name || '', license_no: driver?.license_no || '', license_expiry: driver?.license_expiry || '',
    phone: driver?.phone || '', status: driver?.status || 'AVAILABLE',
  }))
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    try {
      if (editing) {
        const body = { name: form.name, license_expiry: form.license_expiry, phone: form.phone, version: driver.version }
        if (driver.status !== 'ON_TRIP') body.status = form.status
        await run(() => api.put(`/drivers/${driver.id}`, body))
        notify('Driver updated')
      } else {
        await run(() => api.post('/drivers', form))
        notify('Driver added')
      }
      onSaved()
    } catch { /* shown */ }
  }

  return (
    <Modal open title={editing ? 'Edit driver' : 'Add driver'} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="driver-form" busy={busy}>{editing ? 'Save changes' : 'Add driver'}</Button></>}>
      <form id="driver-form" onSubmit={submit} className="flex flex-col gap-4">
        <ErrorBanner message={error} />
        <Input label="Full name" required minLength={2} value={form.name} onChange={set('name')} />
        <Input label="Licence number" required disabled={editing} value={form.license_no} onChange={set('license_no')}
               placeholder="UK0720190012345" hint={editing ? 'Licence numbers cannot be changed.' : undefined} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Licence valid until" type="date" required value={form.license_expiry} onChange={set('license_expiry')} />
          <Input label="Phone" type="tel" required value={form.phone} onChange={set('phone')} placeholder="+91 98765 43210" />
        </div>
        {editing && (driver.status === 'ON_TRIP'
          ? <p className="text-sm text-muted">Status is set by trips while this driver is on the road.</p>
          : <Select label="Status" options={EDITABLE_STATUS} value={form.status} onChange={set('status')} />)}
      </form>
    </Modal>
  )
}

function DriverTrips({ driver, onClose }) {
  const { data, error, loading } = useFetch(`/drivers/${driver.id}/trips`)
  return (
    <Modal open wide title={`Trips by ${driver.name}`} onClose={onClose}>
      <ErrorBanner message={error} />
      {loading ? <Spinner /> : data?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line text-left text-muted">
              <th className="py-2 pr-4">Vehicle</th><th className="py-2 pr-4">Route</th><th className="py-2 pr-4">Started</th>
              <th className="py-2 pr-4">Distance</th><th className="py-2">Status</th></tr></thead>
            <tbody>{data.map((t) => (
              <tr key={t.id} className="border-b border-line/70 last:border-0">
                <td className="py-2 pr-4"><Plate reg={t.vehicle_registration} size="sm" /></td>
                <td className="py-2 pr-4">{t.source} to {t.destination}</td>
                <td className="py-2 pr-4 tabular">{dateTime(t.start_time)}</td>
                <td className="py-2 pr-4 tabular">{km(t.distance_km)}</td>
                <td className="py-2"><StatusBadge status={t.status} /></td>
              </tr>))}</tbody>
          </table>
        </div>
      ) : <p className="py-6 text-center text-muted">No trips yet.</p>}
    </Modal>
  )
}

export default function Drivers() {
  const { can } = useAuth()
  const notify = useToast()
  const { data, error, loading, reload } = useFetch('/drivers')
  const [modal, setModal] = useState(null)
  const close = () => setModal(null)
  const saved = () => { close(); reload(true) }

  const deactivate = async (d) => {
    if (!window.confirm(`Deactivate ${d.name}? Their trip history is kept.`)) return
    try {
      await api.delete(`/drivers/${d.id}`)
      notify('Driver deactivated')
      reload(true)
    } catch (e) {
      notify(e.response?.data?.detail || 'Could not deactivate the driver', 'error')
    }
  }

  const columns = [
    { key: 'name', header: 'Name', render: (d) => <span className="font-semibold">{d.name}</span> },
    { key: 'license_no', header: 'Licence', className: 'tabular' },
    { key: 'license_expiry', header: 'Valid until', render: (d) => <LicenceExpiry date={d.license_expiry} /> },
    { key: 'phone', header: 'Phone', className: 'tabular whitespace-nowrap' },
    { key: 'vehicle', header: 'Regular vehicle', sortValue: (d) => d.assigned_vehicle?.registration_no || '',
      render: (d) => d.assigned_vehicle ? <Plate reg={d.assigned_vehicle.registration_no} size="sm" /> : <span className="text-muted">None</span> },
    { key: 'status', header: 'Status', render: (d) => <StatusBadge status={d.status} /> },
    { key: 'actions', header: '', sortable: false, align: 'right', render: (d) => (
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="ghost" icon={History} onClick={() => setModal({ type: 'trips', driver: d })} aria-label={`Trips by ${d.name}`} />
        {can('MANAGER') && <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setModal({ type: 'edit', driver: d })} aria-label={`Edit ${d.name}`} />}
        {can('ADMIN') && !['INACTIVE', 'ON_TRIP'].includes(d.status) &&
          <Button size="sm" variant="ghost" icon={Power} onClick={() => deactivate(d)} aria-label={`Deactivate ${d.name}`} />}
      </div>
    ) },
  ]

  return (
    <>
      <PageHeader title="Drivers" description="Driver records, licence validity and who is on the road."
        actions={can('MANAGER') && <Button icon={Plus} onClick={() => setModal({ type: 'create' })}>Add driver</Button>} />
      <ErrorBanner message={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : (
        <DataTable columns={columns} rows={data || []}
          searchText={(d) => `${d.name} ${d.license_no} ${d.phone} ${d.assigned_vehicle?.registration_no || ''}`}
          searchPlaceholder="Search name, licence or phone"
          emptyTitle="No drivers yet" emptyText="Add drivers so you can assign them to vehicles and trips." />
      )}
      {modal?.type === 'create' && <DriverForm onClose={close} onSaved={saved} />}
      {modal?.type === 'edit' && <DriverForm driver={modal.driver} onClose={close} onSaved={saved} />}
      {modal?.type === 'trips' && <DriverTrips driver={modal.driver} onClose={close} />}
    </>
  )
}
