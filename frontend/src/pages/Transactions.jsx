import { useState } from 'react'
import { CheckCircle2, Play, RefreshCw, RotateCcw, XCircle } from 'lucide-react'
import DataTable from '../components/DataTable'
import { Button, ErrorBanner, PageHeader, Panel, Spinner, StatusBadge, Tabs, useToast } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime, moneyExact, titleCase } from '../lib/format'
import { useAction, useFetch } from '../lib/hooks'

const ROLLBACK_FAILURES = [
  { value: 'foreign_key', label: 'Foreign key violation', help: 'Insert a fuel record for a vehicle that does not exist.' },
  { value: 'check_constraint', label: 'CHECK constraint violation', help: 'Insert an expense with a negative amount (needs MySQL 8.0.16+).' },
  { value: 'application', label: 'Application error', help: 'Application code detects a problem and aborts.' },
]

const CONCURRENCY_MODES = [
  { value: 'naive', label: 'No protection', help: 'Read the status, wait, then write. Both users can win: a race condition.' },
  { value: 'conditional', label: 'Conditional update', help: "UPDATE ... WHERE status = 'AVAILABLE'. The second update matches 0 rows." },
  { value: 'pessimistic', label: 'Row lock', help: 'SELECT ... FOR UPDATE. The second user waits for the lock, then sees the vehicle is taken.' },
]

const ACTOR_TONE = {
  'User A': 'border-route text-route',
  'User B': 'border-signal-dark text-signal-dark',
  Transaction: 'border-hw text-hw',
  Database: 'border-stop text-stop',
  Application: 'border-stop text-stop',
  'Audit log': 'border-muted text-muted',
  'Another connection': 'border-route text-route',
  System: 'border-line text-muted',
}

const STATE_LABELS = {
  vehicle_status: 'Vehicle status', odometer_km: 'Odometer (km)', expense_rows: 'Expense rows',
  expense_total: 'Expense total', booking_charges: 'Booking charges',
}

function Step({ step }) {
  return (
    <div className={`border-l-[3px] py-1.5 pl-3 ${ACTOR_TONE[step.actor] || 'border-line'}`}>
      <p className="text-xs font-semibold">{step.actor}</p>
      <p className="text-sm font-medium text-asphalt">{step.action}</p>
      {step.sql && <code className="mt-1 block overflow-x-auto whitespace-pre rounded bg-asphalt px-2 py-1 text-xs text-white">{step.sql}</code>}
      {step.outcome && <p className="mt-0.5 text-sm text-muted">{step.outcome}</p>}
    </div>
  )
}

/** Two users side by side, so the overlap of their transactions is visible. */
function Lanes({ steps }) {
  const lanes = ['User A', 'User B']
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-line text-left text-muted">
            <th className="w-20 py-2 pr-3 font-semibold">Time</th>
            {lanes.map((l) => <th key={l} className="py-2 pr-3 font-semibold">{l}</th>)}
          </tr>
        </thead>
        <tbody>
          {steps.map((s, i) => (
            <tr key={i} className="border-b border-line/60 align-top last:border-0">
              <td className="py-2 pr-3 tabular text-muted">{s.t_ms} ms</td>
              {lanes.includes(s.actor)
                ? lanes.map((l) => <td key={l} className="py-1 pr-3">{s.actor === l && <Step step={s} />}</td>)
                : <td colSpan={2} className="py-1 pr-3"><Step step={s} /></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StateCompare({ before, after }) {
  const keys = Object.keys(before).filter((k) => STATE_LABELS[k])
  const fmt = (k, v) => (k === 'expense_total' ? moneyExact(v) : String(v))
  return (
    <table className="w-full text-sm">
      <thead><tr className="border-b border-line text-left text-muted">
        <th className="py-1.5 pr-3 font-semibold">Test vehicle</th><th className="py-1.5 pr-3 font-semibold">Before</th><th className="py-1.5 font-semibold">After</th>
      </tr></thead>
      <tbody>{keys.map((k) => {
        const changed = before[k] !== after[k]
        return (
          <tr key={k} className="border-b border-line/60 last:border-0">
            <td className="py-1.5 pr-3">{STATE_LABELS[k]}</td>
            <td className="py-1.5 pr-3 tabular">{fmt(k, before[k])}</td>
            <td className={`py-1.5 tabular ${changed ? 'font-semibold text-asphalt' : 'text-muted'}`}>{fmt(k, after[k])}{changed ? '' : ' (unchanged)'}</td>
          </tr>
        )
      })}</tbody>
    </table>
  )
}

function Result({ result }) {
  if (!result) return null
  const concurrent = result.steps.some((s) => s.actor === 'User B')
  const good = ['COMMITTED', 'ROLLED_BACK', 'PROTECTED'].includes(result.final_status)
  return (
    <Panel title="Result" className="mt-6"
      actions={<StatusBadge status={result.final_status} label={titleCase(result.final_status)} />}>
      <p className={`flex items-start gap-2 ${good ? 'text-asphalt' : 'text-stop'}`}>
        {good ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-hw" /> : <XCircle className="mt-0.5 size-5 shrink-0" />}
        {result.message}
      </p>
      <div className="mt-5 grid gap-6 xl:grid-cols-[1fr_320px]">
        <div>
          <h3 className="mb-2 font-display text-lg font-semibold">What happened, step by step</h3>
          {concurrent ? <Lanes steps={result.steps} /> : (
            <ol className="flex flex-col gap-2">
              {result.steps.map((s, i) => (
                <li key={i} className="flex gap-3">
                  <span className="w-16 shrink-0 pt-1.5 text-sm tabular text-muted">{s.t_ms} ms</span>
                  <div className="min-w-0 flex-1"><Step step={s} /></div>
                </li>
              ))}
            </ol>
          )}
        </div>
        <div>
          <h3 className="mb-2 font-display text-lg font-semibold">Committed state</h3>
          <StateCompare before={result.before} after={result.after} />
          <p className="mt-3 text-sm text-muted">Both columns were read through a separate database connection, the way another user would see the data.</p>
          {result.audit_ids.length > 0 && <p className="mt-2 text-sm text-muted">Audit rows written: {result.audit_ids.map((id) => `#${id}`).join(', ')}</p>}
        </div>
      </div>
    </Panel>
  )
}

function Choice({ options, value, onChange, name }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="sr-only">{name}</legend>
      {options.map((o) => (
        <label key={o.value} className={`flex cursor-pointer gap-3 rounded-md border p-3 text-sm ${value === o.value ? 'border-hw bg-hw-tint' : 'border-line hover:border-asphalt/30'}`}>
          <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} className="mt-0.5 accent-hw" />
          <span><span className="font-semibold">{o.label}</span><span className="block text-muted">{o.help}</span></span>
        </label>
      ))}
    </fieldset>
  )
}

function Demos() {
  const { can } = useAuth()
  const notify = useToast()
  const { busy, error, run } = useAction()
  const [failure, setFailure] = useState('foreign_key')
  const [mode, setMode] = useState('naive')
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState('')

  const go = async (key, path, body) => {
    setRunning(key)
    setResult(null)
    try {
      const { data } = await run(() => api.post(path, body))
      setResult(data)
    } catch { /* shown */ } finally { setRunning('') }
  }
  const reset = async () => {
    try {
      await run(() => api.post('/transactions/demo/reset'))
      setResult(null)
      notify('Test vehicle reset')
    } catch { /* shown */ }
  }

  if (!can('MANAGER')) {
    return <p className="rounded-md bg-surface px-4 py-3 text-muted">Running demonstrations needs the manager role. You can still read the audit log and consistency checks.</p>
  }

  return (
    <>
      <p className="mb-4 max-w-3xl text-muted">
        Every demonstration works on one hidden test vehicle, so real fleet data is never touched.
        The test vehicle and its expenses are excluded from lists and reports.
      </p>
      <ErrorBanner message={error} />
      <div className="mt-2 grid gap-4 lg:grid-cols-3">
        <Panel title="Commit">
          <p className="text-sm text-muted">Insert an expense and update the odometer in one transaction, then commit. Midway, a second connection checks that it cannot see the uncommitted changes.</p>
          <Button className="mt-4 w-full" icon={Play} busy={running === 'commit'} disabled={busy}
                  onClick={() => go('commit', '/transactions/demo/commit')}>Run commit demo</Button>
        </Panel>
        <Panel title="Rollback">
          <p className="mb-3 text-sm text-muted">Same two writes, then a third step fails. Everything is rolled back.</p>
          <Choice name="Failure type" options={ROLLBACK_FAILURES} value={failure} onChange={setFailure} />
          <Button className="mt-4 w-full" icon={Play} busy={running === 'rollback'} disabled={busy}
                  onClick={() => go('rollback', '/transactions/demo/rollback', { failure })}>Run rollback demo</Button>
        </Panel>
        <Panel title="Two users, one vehicle">
          <p className="mb-3 text-sm text-muted">User A and User B try to book the same vehicle 150 ms apart.</p>
          <Choice name="Protection" options={CONCURRENCY_MODES} value={mode} onChange={setMode} />
          <Button className="mt-4 w-full" icon={Play} busy={running === 'concurrency'} disabled={busy}
                  onClick={() => go('concurrency', '/transactions/demo/concurrency', { mode })}>Run race</Button>
        </Panel>
      </div>
      <div className="mt-3 flex justify-end">
        <Button variant="ghost" size="sm" icon={RotateCcw} onClick={reset} disabled={busy}>Reset test vehicle</Button>
      </div>
      {running && <Spinner label="Running transaction" />}
      <Result result={result} />
    </>
  )
}

function Consistency() {
  const { data, error, loading, reload } = useFetch('/transactions/consistency')
  const [open, setOpen] = useState(null)
  if (loading && !data) return <Spinner />
  const failed = (data || []).filter((c) => !c.passed).length
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className={failed ? 'font-semibold text-stop' : 'text-muted'}>
          {failed ? `${failed} check(s) found inconsistent data.` : 'Every check returned zero violations: the data is consistent.'}
        </p>
        <Button variant="secondary" icon={RefreshCw} onClick={() => reload()}>Run checks again</Button>
      </div>
      <ErrorBanner message={error} />
      <ul className="divide-y divide-line rounded-lg border border-line bg-white">
        {(data || []).map((c, i) => (
          <li key={c.name} className="px-5 py-4">
            <div className="flex items-start gap-3">
              {c.passed ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-hw" /> : <XCircle className="mt-0.5 size-5 shrink-0 text-stop" />}
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{c.name}</p>
                <p className="text-sm text-muted">{c.description}</p>
                <button type="button" className="mt-1 text-sm font-semibold text-route hover:underline" onClick={() => setOpen(open === i ? null : i)}>
                  {open === i ? 'Hide SQL' : 'Show SQL'}
                </button>
                {open === i && <pre className="mt-2 overflow-x-auto rounded bg-asphalt p-3 text-xs text-white">{c.sql}</pre>}
              </div>
              <span className={`tabular text-sm font-semibold ${c.passed ? 'text-hw' : 'text-stop'}`}>{c.violations} rows</span>
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}

function AuditLog() {
  const [status, setStatus] = useState('')
  const { data, error, loading, reload } = useFetch(`/transactions?limit=300${status ? `&status=${status}` : ''}`)
  return (
    <>
      <ErrorBanner message={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : (
        <DataTable rows={data || []} pageSize={20}
          searchText={(a) => `${a.operation} ${a.message} ${a.user_name || ''}`}
          searchPlaceholder="Search operation, message or user"
          emptyTitle="No transactions recorded yet"
          toolbar={<>
            <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by result" className="h-9 rounded-md border border-line px-2 text-sm">
              <option value="">All results</option><option value="COMMITTED">Committed</option><option value="ROLLED_BACK">Rolled back</option>
            </select>
            <Button size="sm" variant="secondary" icon={RefreshCw} onClick={() => reload()}>Refresh</Button>
          </>}
          columns={[
            { key: 'id', header: '#', render: (a) => <span className="tabular text-muted">{a.id}</span> },
            { key: 'created_at', header: 'When', render: (a) => <span className="whitespace-nowrap tabular">{dateTime(a.created_at)}</span> },
            { key: 'operation', header: 'Operation', render: (a) => <code className="text-xs">{a.operation}</code> },
            { key: 'status', header: 'Result', render: (a) => <StatusBadge status={a.status} /> },
            { key: 'message', header: 'Message', render: (a) => <span className="line-clamp-2 max-w-md">{a.message}</span> },
            { key: 'user_name', header: 'By', render: (a) => a.user_name || <span className="text-muted">System</span> },
            { key: 'duration_ms', header: 'Time', align: 'right', render: (a) => (a.duration_ms === null ? '-' : `${a.duration_ms} ms`) },
          ]} />
      )}
    </>
  )
}

export default function Transactions() {
  const [tab, setTab] = useState('demos')
  return (
    <>
      <PageHeader title="Transaction lab"
        description="See COMMIT, ROLLBACK and concurrency control happen in the real database, step by step." />
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: 'demos', label: 'Demonstrations' }, { value: 'checks', label: 'Consistency checks' }, { value: 'log', label: 'Audit log' },
      ]} />
      {tab === 'demos' && <Demos />}
      {tab === 'checks' && <Consistency />}
      {tab === 'log' && <AuditLog />}
    </>
  )
}
