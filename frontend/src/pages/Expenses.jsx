import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import DataTable from '../components/DataTable'
import {
  Button, Checkbox, ErrorBanner, Input, Modal, PageHeader, Plate, Select, Spinner, StatusBadge, Tabs, useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateOnly, dateTime, km, moneyExact, number, titleCase, todayISO } from '../lib/format'
import { useAction, useFetch } from '../lib/hooks'

function useVehicleOptions(filter = () => true) {
  const { data } = useFetch('/vehicles?include_inactive=false')
  return {
    vehicles: data || [],
    options: (data || []).filter(filter).map((v) => ({ value: String(v.id), label: `${v.registration_no}, ${v.model}` })),
  }
}

function FormModal({ title, formId, busy, onClose, submitLabel, children }) {
  return (
    <Modal open title={title} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form={formId} busy={busy}>{submitLabel}</Button></>}>
      {children}
    </Modal>
  )
}

function FuelForm({ onClose, onSaved }) {
  const notify = useToast()
  const { busy, error, run } = useAction()
  const { vehicles, options } = useVehicleOptions((v) => v.fuel_type !== 'ELECTRIC')
  const [form, setForm] = useState({ vehicle_id: '', quantity_l: '', price_per_l: '', odometer_km: '', station: '' })
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })
  const vehicle = vehicles.find((v) => String(v.id) === form.vehicle_id)
  const total = Number(form.quantity_l) * Number(form.price_per_l)

  const submit = async (e) => {
    e.preventDefault()
    try {
      await run(() => api.post('/fuel-records', { ...form, vehicle_id: Number(form.vehicle_id), station: form.station || null }))
      notify('Fuel purchase recorded')
      onSaved()
    } catch { /* shown */ }
  }

  return (
    <FormModal title="Record fuel purchase" formId="fuel-form" busy={busy} onClose={onClose} submitLabel="Save fuel record">
      <form id="fuel-form" onSubmit={submit} className="flex flex-col gap-4">
        <ErrorBanner message={error} />
        <Select label="Vehicle" required placeholder="Choose a vehicle" options={options} value={form.vehicle_id} onChange={set('vehicle_id')}
                hint="Electric vehicles are not listed. Record charging under Other expenses." />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Quantity (litres or kg)" type="number" min="0.01" step="0.01" required value={form.quantity_l} onChange={set('quantity_l')} />
          <Input label="Price per unit (₹)" type="number" min="0.01" step="0.01" required value={form.price_per_l} onChange={set('price_per_l')} />
        </div>
        <Input label="Odometer reading (km)" type="number" min="0" step="0.1" required value={form.odometer_km} onChange={set('odometer_km')}
               hint={vehicle ? `Last recorded: ${km(vehicle.odometer_km)}. The new reading cannot be lower.` : undefined} />
        <Input label="Fuel station" maxLength={120} value={form.station} onChange={set('station')} placeholder="Optional" />
        {total > 0 && <p className="rounded-md bg-surface px-3 py-2 text-sm">Total cost <span className="font-semibold tabular">{moneyExact(total)}</span>, saved as a fuel expense in the same transaction.</p>}
      </form>
    </FormModal>
  )
}

function MaintenanceForm({ onClose, onSaved }) {
  const notify = useToast()
  const { busy, error, run } = useAction()
  const { options } = useVehicleOptions()
  const [form, setForm] = useState({
    vehicle_id: '', service_type: '', description: '', service_date: todayISO(), cost: '',
    odometer_km: '', next_service_date: '', put_in_maintenance: false,
  })
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    try {
      await run(() => api.post('/maintenance', {
        ...form, vehicle_id: Number(form.vehicle_id),
        odometer_km: form.odometer_km || null, next_service_date: form.next_service_date || null,
      }))
      notify('Service recorded')
      onSaved()
    } catch { /* shown */ }
  }

  return (
    <FormModal title="Record service" formId="maint-form" busy={busy} onClose={onClose} submitLabel="Save service record">
      <form id="maint-form" onSubmit={submit} className="flex flex-col gap-4">
        <ErrorBanner message={error} />
        <Select label="Vehicle" required placeholder="Choose a vehicle" options={options} value={form.vehicle_id} onChange={set('vehicle_id')} />
        <Input label="Service type" required minLength={2} maxLength={60} value={form.service_type} onChange={set('service_type')}
               placeholder="General service, brake pads" list="service-types" />
        <datalist id="service-types">
          {['General service', 'Oil and filter change', 'Brake pads', 'Tyre replacement', 'Battery replacement', 'Wheel alignment'].map((s) => <option key={s} value={s} />)}
        </datalist>
        <Input label="Details" maxLength={500} value={form.description} onChange={set('description')} placeholder="Optional" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Service date" type="date" required max={todayISO()} value={form.service_date} onChange={set('service_date')} />
          <Input label="Cost (₹)" type="number" min="0" step="0.01" required value={form.cost} onChange={set('cost')} />
          <Input label="Odometer (km)" type="number" min="0" step="0.1" value={form.odometer_km} onChange={set('odometer_km')} placeholder="Optional" />
          <Input label="Next service due" type="date" min={form.service_date} value={form.next_service_date} onChange={set('next_service_date')} />
        </div>
        <Checkbox label="Vehicle is staying in the workshop" hint="Sets its status to Maintenance so it cannot take trips."
                  checked={form.put_in_maintenance} onChange={set('put_in_maintenance')} />
      </form>
    </FormModal>
  )
}

function ExpenseForm({ onClose, onSaved }) {
  const notify = useToast()
  const { busy, error, run } = useAction()
  const { options } = useVehicleOptions()
  const [form, setForm] = useState({ vehicle_id: '', category: 'TOLL', amount: '', expense_date: todayISO(), description: '' })
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    try {
      await run(() => api.post('/expenses', { ...form, vehicle_id: Number(form.vehicle_id) }))
      notify('Expense recorded')
      onSaved()
    } catch { /* shown */ }
  }

  return (
    <FormModal title="Record expense" formId="expense-form" busy={busy} onClose={onClose} submitLabel="Save expense">
      <form id="expense-form" onSubmit={submit} className="flex flex-col gap-4">
        <ErrorBanner message={error} />
        <Select label="Vehicle" required placeholder="Choose a vehicle" options={options} value={form.vehicle_id} onChange={set('vehicle_id')} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Category" value={form.category} onChange={set('category')}
                  options={['TOLL', 'PARKING', 'INSURANCE', 'OTHER'].map((c) => ({ value: c, label: titleCase(c) }))} />
          <Input label="Amount (₹)" type="number" min="0" step="0.01" required value={form.amount} onChange={set('amount')} />
        </div>
        <Input label="Date" type="date" required max={todayISO()} value={form.expense_date} onChange={set('expense_date')} />
        <Input label="Description" maxLength={255} value={form.description} onChange={set('description')} placeholder="EV charging, highway toll" />
      </form>
    </FormModal>
  )
}

function useDelete(path, label, reload) {
  const notify = useToast()
  return async (id) => {
    if (!window.confirm(`Delete this ${label}? Its linked expense is deleted in the same transaction.`)) return
    try {
      await api.delete(`${path}/${id}`)
      notify(`${titleCase(label)} deleted`)
      reload(true)
    } catch (e) {
      notify(e.response?.data?.detail || 'Could not delete', 'error')
    }
  }
}

export default function Expenses() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'fuel'
  const setTab = (t) => setParams({ tab: t }, { replace: true })
  const [form, setForm] = useState(null)

  const fuel = useFetch('/fuel-records', { enabled: tab === 'fuel' })
  const maintenance = useFetch('/maintenance', { enabled: tab === 'maintenance' })
  const expenses = useFetch('/expenses', { enabled: tab === 'other' })
  const upcoming = useFetch('/maintenance/upcoming?days=30', { enabled: tab === 'alerts' })

  const deleteFuel = useDelete('/fuel-records', 'fuel record', fuel.reload)
  const deleteService = useDelete('/maintenance', 'service record', maintenance.reload)

  const done = () => {
    setForm(null)
    ;({ fuel, maintenance, other: expenses, alerts: upcoming })[tab]?.reload(true)
  }
  const deleteButton = (fn, id) => can('ADMIN') && (
    <Button size="sm" variant="ghost" icon={Trash2} onClick={() => fn(id)} aria-label="Delete" />
  )

  const addButton = can('MANAGER') && {
    fuel: <Button icon={Plus} onClick={() => setForm('fuel')}>Record fuel</Button>,
    maintenance: <Button icon={Plus} onClick={() => setForm('maintenance')}>Record service</Button>,
    other: <Button icon={Plus} onClick={() => setForm('other')}>Record expense</Button>,
  }[tab]

  const current = { fuel, maintenance, other: expenses, alerts: upcoming }[tab]

  return (
    <>
      <PageHeader title="Fuel and maintenance" description="Fuel purchases, services, other running costs and upcoming service dates."
        actions={addButton} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: 'fuel', label: 'Fuel' }, { value: 'maintenance', label: 'Services' },
        { value: 'other', label: 'Other expenses' }, { value: 'alerts', label: 'Service alerts' },
      ]} />
      <ErrorBanner message={current.error} onRetry={current.reload} />
      {current.loading && !current.data ? <Spinner /> : (
        <>
          {tab === 'fuel' && (
            <DataTable rows={fuel.data || []} searchText={(r) => `${r.vehicle_registration} ${r.station || ''}`}
              searchPlaceholder="Search plate or station" emptyTitle="No fuel purchases recorded"
              columns={[
                { key: 'recorded_at', header: 'Date', render: (r) => <span className="tabular whitespace-nowrap">{dateTime(r.recorded_at)}</span> },
                { key: 'vehicle_registration', header: 'Vehicle', render: (r) => <Plate reg={r.vehicle_registration} size="sm" /> },
                { key: 'quantity_l', header: 'Quantity', align: 'right', render: (r) => number(r.quantity_l) },
                { key: 'price_per_l', header: 'Price', align: 'right', render: (r) => moneyExact(r.price_per_l) },
                { key: 'total_cost', header: 'Total', align: 'right', render: (r) => <span className="font-semibold">{moneyExact(r.total_cost)}</span> },
                { key: 'odometer_km', header: 'Odometer', align: 'right', render: (r) => km(r.odometer_km) },
                { key: 'station', header: 'Station', render: (r) => r.station || <span className="text-muted">-</span> },
                { key: 'x', header: '', sortable: false, align: 'right', render: (r) => deleteButton(deleteFuel, r.id) },
              ]} />
          )}
          {tab === 'maintenance' && (
            <DataTable rows={maintenance.data || []} searchText={(r) => `${r.vehicle_registration} ${r.service_type} ${r.description}`}
              searchPlaceholder="Search plate or service" emptyTitle="No services recorded"
              columns={[
                { key: 'service_date', header: 'Date', render: (r) => <span className="tabular">{dateOnly(r.service_date)}</span> },
                { key: 'vehicle_registration', header: 'Vehicle', render: (r) => <Plate reg={r.vehicle_registration} size="sm" /> },
                { key: 'service_type', header: 'Service' },
                { key: 'cost', header: 'Cost', align: 'right', render: (r) => <span className="font-semibold">{moneyExact(r.cost)}</span> },
                { key: 'next_service_date', header: 'Next due', render: (r) => <span className="tabular">{dateOnly(r.next_service_date)}</span> },
                { key: 'x', header: '', sortable: false, align: 'right', render: (r) => deleteButton(deleteService, r.id) },
              ]} />
          )}
          {tab === 'other' && (
            <DataTable rows={expenses.data || []} searchText={(r) => `${r.vehicle_registration} ${r.category} ${r.description}`}
              searchPlaceholder="Search plate, category or description" emptyTitle="No expenses recorded"
              columns={[
                { key: 'expense_date', header: 'Date', render: (r) => <span className="tabular">{dateOnly(r.expense_date)}</span> },
                { key: 'vehicle_registration', header: 'Vehicle', render: (r) => <Plate reg={r.vehicle_registration} size="sm" /> },
                { key: 'category', header: 'Category', render: (r) => titleCase(r.category) },
                { key: 'description', header: 'Description' },
                { key: 'amount', header: 'Amount', align: 'right', render: (r) => <span className="font-semibold">{moneyExact(r.amount)}</span> },
              ]} />
          )}
          {tab === 'alerts' && (
            <DataTable rows={upcoming.data || []} rowKey={(r) => r.vehicle_id}
              emptyTitle="No services due in the next 30 days"
              columns={[
                { key: 'vehicle_registration', header: 'Vehicle', render: (r) => <Plate reg={r.vehicle_registration} size="sm" /> },
                { key: 'service_type', header: 'Last service' },
                { key: 'next_service_date', header: 'Due', render: (r) => <span className="tabular">{dateOnly(r.next_service_date)}</span> },
                { key: 'days_left', header: 'When', render: (r) => r.days_left < 0
                  ? <StatusBadge status="ROLLED_BACK" label={`Overdue by ${-r.days_left} days`} />
                  : <StatusBadge status={r.days_left <= 7 ? 'ACTIVE' : 'SCHEDULED'} label={r.days_left === 0 ? 'Due today' : `In ${r.days_left} days`} /> },
              ]} />
          )}
        </>
      )}
      {form === 'fuel' && <FuelForm onClose={() => setForm(null)} onSaved={done} />}
      {form === 'maintenance' && <MaintenanceForm onClose={() => setForm(null)} onSaved={done} />}
      {form === 'other' && <ExpenseForm onClose={() => setForm(null)} onSaved={done} />}
    </>
  )
}
