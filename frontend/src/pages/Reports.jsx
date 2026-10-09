import { useState } from 'react'
import { Download } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import DataTable from '../components/DataTable'
import { Button, ErrorBanner, PageHeader, Panel, Plate, Spinner, useToast } from '../components/ui'
import { downloadFile, errorMessage } from '../lib/api'
import { km, money, moneyExact, monthLabel, number, titleCase } from '../lib/format'
import { useFetch } from '../lib/hooks'

const CATEGORY_COLORS = {
  FUEL: '#0e5a43', MAINTENANCE: '#f0a202', TOLL: '#1d5fa8', INSURANCE: '#7a8b90', PARKING: '#9fc3b5', OTHER: '#c0362c',
}

function Figure({ label, value }) {
  return (
    <div className="bg-white px-5 py-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 font-display text-2xl font-semibold tabular">{value}</p>
    </div>
  )
}

export default function Reports() {
  const notify = useToast()
  const [days, setDays] = useState(30)
  const [months, setMonths] = useState(6)
  const summary = useFetch(`/reports/summary?days=${days}`)
  const utilization = useFetch(`/reports/utilization?days=${days}`)
  const expenses = useFetch(`/reports/expenses?months=${months}`)
  const [exporting, setExporting] = useState('')

  const exportCsv = async (kind, period) => {
    setExporting(kind)
    try {
      await downloadFile(`/reports/export?kind=${kind}&days=${period}`, `tracktech-${kind}.csv`)
    } catch (e) {
      notify(errorMessage(e), 'error')
    } finally {
      setExporting('')
    }
  }

  const periodSelect = (value, onChange, opts, label) => (
    <select value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label}
            className="h-9 rounded-md border border-line bg-white px-2 text-sm">
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )

  const s = summary.data
  const categories = expenses.data?.categories || []
  const usedCategories = categories.filter((c) => (expenses.data?.totals?.[c] || 0) > 0)

  return (
    <>
      <PageHeader title="Reports" description="Costs, distance and how hard each vehicle is working."
        actions={<>
          {periodSelect(days, setDays, [[7, 'Last 7 days'], [30, 'Last 30 days'], [90, 'Last 90 days'], [365, 'Last 12 months']], 'Report period')}
          <Button variant="secondary" icon={Download} busy={exporting === 'trips'} onClick={() => exportCsv('trips', days)}>Trips CSV</Button>
        </>} />

      <ErrorBanner message={summary.error || utilization.error || expenses.error} onRetry={() => { summary.reload(); utilization.reload(); expenses.reload() }} />

      {s && (
        <section className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-5">
          <Figure label="Trips completed" value={s.completed_trips} />
          <Figure label="Distance driven" value={km(s.distance_km)} />
          <Figure label="Total cost" value={money(s.total_cost)} />
          <Figure label="Cost per km" value={s.cost_per_km === null ? '-' : moneyExact(s.cost_per_km)} />
          <Figure label="Average utilisation" value={`${number(s.avg_utilization_pct)}%`} />
        </section>
      )}

      <Panel title="Spending by month" className="mt-6"
        actions={<div className="flex gap-2">
          {periodSelect(months, setMonths, [[3, '3 months'], [6, '6 months'], [12, '12 months']], 'Months to show')}
          <Button size="sm" variant="secondary" icon={Download} busy={exporting === 'expenses'} onClick={() => exportCsv('expenses', months * 31)}>Expenses CSV</Button>
        </div>}>
        {expenses.loading && !expenses.data ? <Spinner /> : (
          <>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={expenses.data?.rows || []} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="#e5eae8" />
                  <XAxis dataKey="month" tickFormatter={monthLabel} tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis tickFormatter={(v) => `₹${Math.round(v / 1000)}k`} tickLine={false} axisLine={false} fontSize={12} width={48} />
                  <Tooltip formatter={(v) => money(v)} labelFormatter={monthLabel} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
                  {usedCategories.map((c) => <Bar key={c} dataKey={c} name={titleCase(c)} stackId="e" fill={CATEGORY_COLORS[c]} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
            <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 border-t border-line pt-4 text-sm">
              {usedCategories.map((c) => (
                <div key={c}><dt className="text-muted">{titleCase(c)}</dt><dd className="font-semibold tabular">{money(expenses.data.totals[c])}</dd></div>
              ))}
              <div><dt className="text-muted">Total</dt><dd className="font-semibold tabular">{money(expenses.data?.totals?.total)}</dd></div>
            </dl>
          </>
        )}
      </Panel>

      <div className="mb-3 mt-8 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl font-semibold">Vehicle utilisation</h2>
          <p className="text-muted">Utilisation is hours on completed trips divided by all hours in the period.</p>
        </div>
        <Button variant="secondary" icon={Download} busy={exporting === 'utilization'} onClick={() => exportCsv('utilization', days)}>Utilisation CSV</Button>
      </div>
      {utilization.loading && !utilization.data ? <Spinner /> : (
        <DataTable rows={utilization.data || []} rowKey={(r) => r.vehicle_id}
          searchText={(r) => `${r.registration_no} ${r.model}`} searchPlaceholder="Search plate or model"
          emptyTitle="No vehicles to report on"
          columns={[
            { key: 'registration_no', header: 'Vehicle', render: (r) => <Plate reg={r.registration_no} size="sm" /> },
            { key: 'completed_trips', header: 'Trips', align: 'right' },
            { key: 'distance_km', header: 'Distance', align: 'right', render: (r) => km(r.distance_km) },
            { key: 'utilization_pct', header: 'Utilisation', render: (r) => (
              <div className="flex min-w-32 items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface"><div className="h-full bg-hw" style={{ width: `${r.utilization_pct}%` }} /></div>
                <span className="w-12 text-right text-sm tabular">{number(r.utilization_pct)}%</span>
              </div>
            ) },
            { key: 'fuel_cost', header: 'Fuel', align: 'right', render: (r) => money(r.fuel_cost) },
            { key: 'maintenance_cost', header: 'Service', align: 'right', render: (r) => money(r.maintenance_cost) },
            { key: 'total_cost', header: 'Total', align: 'right', render: (r) => <span className="font-semibold">{money(r.total_cost)}</span> },
            { key: 'cost_per_km', header: 'Per km', align: 'right', render: (r) => (r.cost_per_km === null ? '-' : moneyExact(r.cost_per_km)) },
          ]} />
      )}
    </>
  )
}
