import { Link } from 'react-router-dom'
import { AlertTriangle, Info, RefreshCw } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Button, ErrorBanner, PageHeader, Panel, Plate, Spinner, StatusBadge } from '../components/ui'
import { dateTime, money, monthLabel } from '../lib/format'
import { useFetch } from '../lib/hooks'

const STATUS_ORDER = [
  ['IN_USE', 'On a trip', 'bg-signal'],
  ['AVAILABLE', 'Available', 'bg-hw'],
  ['MAINTENANCE', 'In maintenance', 'bg-stop'],
]

function Stat({ label, value, sub }) {
  return (
    <div className="bg-white px-5 py-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 font-display text-3xl font-semibold tabular leading-none">{value}</p>
      {sub && <p className="mt-1.5 text-sm text-muted">{sub}</p>}
    </div>
  )
}

function FleetBar({ byStatus, total }) {
  if (!total) return null
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-surface" role="img"
           aria-label={STATUS_ORDER.map(([k, l]) => `${byStatus[k] || 0} ${l.toLowerCase()}`).join(', ')}>
        {STATUS_ORDER.map(([key, , color]) => (
          <div key={key} className={color} style={{ width: `${((byStatus[key] || 0) / total) * 100}%` }} />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {STATUS_ORDER.map(([key, label, color]) => (
          <li key={key} className="flex items-center gap-2">
            <span className={`size-2.5 rounded-full ${color}`} aria-hidden />
            {label} <span className="font-semibold tabular">{byStatus[key] || 0}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const ALERT_STYLE = {
  danger: 'border-stop text-stop',
  warning: 'border-signal text-signal-dark',
  info: 'border-route text-route',
}

export default function Dashboard() {
  const { data, error, loading, reload } = useFetch('/dashboard/stats', { pollMs: 15000 })

  if (loading && !data) return <Spinner />
  if (error && !data) return <ErrorBanner message={error} onRetry={reload} />

  const { vehicles, drivers, trips, costs, monthly_costs: monthly, recent_trips: recent, alerts } = data
  const monthTotal = costs.fuel_this_month + costs.maintenance_this_month + costs.other_this_month

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Where the fleet stands right now. Refreshes every 15 seconds."
        actions={<Button variant="secondary" icon={RefreshCw} onClick={() => reload()}>Refresh</Button>}
      />

      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-4">
        <Stat label="Vehicles in service" value={vehicles.total} sub={`${vehicles.by_status.AVAILABLE} available`} />
        <Stat label="Trips on the road" value={trips.active} sub={`${trips.scheduled} scheduled`} />
        <Stat label="Drivers available" value={drivers.available} sub={`of ${drivers.total} active drivers`} />
        <Stat label="Spent this month" value={money(monthTotal)} sub={`${trips.completed_this_month} trips completed`} />
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Panel title="Costs over six months" className="lg:col-span-2">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthly} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="#e5eae8" />
                <XAxis dataKey="month" tickFormatter={monthLabel} tickLine={false} axisLine={false} fontSize={12} />
                <YAxis tickFormatter={(v) => `₹${Math.round(v / 1000)}k`} tickLine={false} axisLine={false} fontSize={12} width={48} />
                <Tooltip formatter={(v) => money(v)} labelFormatter={monthLabel} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
                <Bar dataKey="FUEL" name="Fuel" stackId="c" fill="#0e5a43" />
                <Bar dataKey="MAINTENANCE" name="Maintenance" stackId="c" fill="#f0a202" />
                <Bar dataKey="OTHER" name="Other" stackId="c" fill="#1d5fa8" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Needs attention" bodyClass="p-0">
          {alerts.length === 0 ? (
            <p className="px-5 py-8 text-center text-muted">Nothing needs attention. Licences, services and trips are all on track.</p>
          ) : (
            <ul className="divide-y divide-line">
              {alerts.map((a, i) => (
                <li key={i}>
                  <Link to={a.link} className={`flex gap-3 border-l-[3px] px-4 py-3 text-sm hover:bg-surface ${ALERT_STYLE[a.level]}`}>
                    {a.level === 'info' ? <Info className="mt-0.5 size-4 shrink-0" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0" />}
                    <span className="text-asphalt">{a.message}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Panel title="Fleet status">
          <FleetBar byStatus={vehicles.by_status} total={vehicles.by_status.IN_USE + vehicles.by_status.AVAILABLE + vehicles.by_status.MAINTENANCE} />
          <dl className="mt-6 grid grid-cols-2 gap-4 text-sm">
            <div><dt className="text-muted">Fuel this month</dt><dd className="font-semibold tabular">{money(costs.fuel_this_month)}</dd></div>
            <div><dt className="text-muted">Maintenance</dt><dd className="font-semibold tabular">{money(costs.maintenance_this_month)}</dd></div>
            <div><dt className="text-muted">Tolls and other</dt><dd className="font-semibold tabular">{money(costs.other_this_month)}</dd></div>
            <div><dt className="text-muted">Drivers on trips</dt><dd className="font-semibold tabular">{drivers.on_trip}</dd></div>
          </dl>
        </Panel>

        <Panel title="Recent trips" className="lg:col-span-2" bodyClass="p-0"
               actions={<Link to="/trips" className="text-sm font-semibold text-route hover:underline">All trips</Link>}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <tbody>
                {recent.map((t) => (
                  <tr key={t.id} className="border-b border-line/70 last:border-0">
                    <td className="px-5 py-3"><Plate reg={t.vehicle_registration} size="sm" /></td>
                    <td className="px-2 py-3">
                      <p className="font-medium">{t.source} to {t.destination}</p>
                      <p className="text-muted">{t.driver_name}</p>
                    </td>
                    <td className="px-2 py-3 text-muted tabular whitespace-nowrap">{dateTime(t.start_time || t.created_at)}</td>
                    <td className="px-5 py-3 text-right"><StatusBadge status={t.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {recent.length === 0 && <p className="px-5 py-8 text-center text-muted">No trips yet. Create one from the Trips page.</p>}
          </div>
        </Panel>
      </div>
    </>
  )
}
