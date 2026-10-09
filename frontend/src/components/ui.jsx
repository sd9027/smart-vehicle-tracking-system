import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, X } from 'lucide-react'
import { formatPlate, titleCase } from '../lib/format'

/* ------------------------------ Buttons ------------------------------ */

const BUTTON_STYLES = {
  primary: 'bg-hw text-white hover:bg-hw-dark disabled:bg-hw/50',
  secondary: 'bg-white text-asphalt border border-line hover:border-asphalt/40 disabled:text-muted',
  danger: 'bg-stop text-white hover:bg-stop/90 disabled:bg-stop/50',
  ghost: 'text-asphalt hover:bg-asphalt/5 disabled:text-muted',
}

export function Button({ variant = 'primary', size = 'md', busy = false, icon: Icon, children, className = '', ...props }) {
  const sizes = size === 'sm' ? 'h-8 px-2.5 text-sm gap-1.5' : 'h-10 px-4 gap-2'
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center rounded-md font-semibold transition-colors disabled:cursor-not-allowed ${sizes} ${BUTTON_STYLES[variant]} ${className}`}
      disabled={busy || props.disabled}
      {...props}
    >
      {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : Icon && <Icon className="size-4" aria-hidden />}
      {children}
    </button>
  )
}

/* ------------------------------ Form fields ------------------------------ */

const inputClass =
  'w-full h-10 rounded-md border border-line bg-white px-3 text-asphalt placeholder:text-muted/70 ' +
  'focus:border-route focus:outline-none focus:ring-2 focus:ring-route/20 disabled:bg-surface'

export function Field({ label, hint, error, children }) {
  const id = useId()
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold text-asphalt">{label}</label>
      {typeof children === 'function' ? children(id) : children}
      {error ? <p className="text-sm text-stop">{error}</p> : hint && <p className="text-sm text-muted">{hint}</p>}
    </div>
  )
}

export function Input({ label, hint, error, className = '', ...props }) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id) => <input id={id} className={`${inputClass} ${className}`} {...props} />}
    </Field>
  )
}

export function Select({ label, hint, error, options, placeholder, className = '', ...props }) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id) => (
        <select id={id} className={`${inputClass} ${className}`} {...props}>
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
          ))}
        </select>
      )}
    </Field>
  )
}

export function Textarea({ label, hint, error, ...props }) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id) => <textarea id={id} rows={3} className={`${inputClass} h-auto py-2`} {...props} />}
    </Field>
  )
}

export function Checkbox({ label, hint, ...props }) {
  return (
    <label className="flex items-start gap-2.5 text-sm">
      <input type="checkbox" className="mt-0.5 size-4 accent-hw" {...props} />
      <span><span className="font-semibold">{label}</span>{hint && <span className="block text-muted">{hint}</span>}</span>
    </label>
  )
}

/* ------------------------------ Status and plates ------------------------------ */

const STATUS_TONE = {
  AVAILABLE: 'hw', COMPLETED: 'hw', COMMITTED: 'hw', PROTECTED: 'hw',
  IN_USE: 'signal', ON_TRIP: 'signal', ACTIVE: 'signal',
  SCHEDULED: 'route',
  MAINTENANCE: 'stop', ROLLED_BACK: 'stop', DOUBLE_BOOKED: 'stop', INCONSISTENT: 'stop', ERROR: 'stop',
  OFF_DUTY: 'muted', INACTIVE: 'muted', CANCELLED: 'muted',
}
const TONE_CLASS = {
  hw: 'bg-hw-tint text-hw border-hw',
  signal: 'bg-signal-tint text-signal-dark border-signal',
  route: 'bg-route-tint text-route border-route',
  stop: 'bg-stop-tint text-stop border-stop',
  muted: 'bg-surface text-muted border-muted/50',
}

/** A status label styled like a lane marking: tinted block with a solid left edge. */
export function StatusBadge({ status, label }) {
  const tone = STATUS_TONE[status] || 'muted'
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-sm border-l-[3px] px-2 py-0.5 text-xs font-semibold ${TONE_CLASS[tone]}`}>
      {label || titleCase(status)}
    </span>
  )
}

/** Registration number drawn as an Indian number plate. */
export function Plate({ reg, size = 'md' }) {
  if (!reg) return <span className="text-muted">-</span>
  const sizeClass = size === 'sm' ? 'plate-sm' : size === 'lg' ? 'plate-lg' : ''
  return (
    <span className={`plate ${sizeClass}`} aria-label={`Registration ${formatPlate(reg)}`}>
      <span className="plate-ind" aria-hidden>IND</span>
      <span className="plate-text">{formatPlate(reg)}</span>
    </span>
  )
}

/* ------------------------------ Feedback ------------------------------ */

export function Spinner({ label = 'Loading' }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-muted" role="status">
      <Loader2 className="size-5 animate-spin" aria-hidden /> {label}
    </div>
  )
}

export function ErrorBanner({ message, onRetry }) {
  if (!message) return null
  return (
    <div className="flex items-start gap-3 rounded-md border border-stop/30 bg-stop-tint px-4 py-3 text-sm text-stop" role="alert">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <p className="flex-1">{message}</p>
      {onRetry && <button type="button" className="font-semibold underline" onClick={() => onRetry()}>Try again</button>}
    </div>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <p className="font-semibold">{title}</p>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/* ------------------------------ Layout pieces ------------------------------ */

export function PageHeader({ title, description, actions }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-3xl font-semibold leading-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function Panel({ title, actions, children, className = '', bodyClass = 'p-5' }) {
  return (
    <section className={`rounded-lg border border-line bg-white ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
          {title && <h2 className="font-display text-lg font-semibold">{title}</h2>}
          {actions}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-semibold transition-colors ${
            value === t.value ? 'border-hw text-hw' : 'border-transparent text-muted hover:text-asphalt'
          }`}
        >
          {t.label}
          {t.count !== undefined && <span className="ml-1.5 tabular text-muted">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

/* ------------------------------ Modal ------------------------------ */

export function Modal({ open, title, onClose, children, footer, wide = false }) {
  const dialogRef = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  // Runs only when the dialog opens, so typing never moves focus back to the first field.
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && closeRef.current()
    document.addEventListener('keydown', onKey)
    const first = dialogRef.current?.querySelector('input:not([disabled]), select, textarea')
    first?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-[1000] flex items-end justify-center bg-asphalt/50 p-0 sm:items-center sm:p-4"
         onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={title}
           className={`tt-rise flex max-h-[92vh] w-full flex-col rounded-t-xl bg-white sm:rounded-xl ${wide ? 'sm:max-w-3xl' : 'sm:max-w-lg'}`}>
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-display text-xl font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-muted hover:bg-surface" aria-label="Close">
            <X className="size-5" />
          </button>
        </header>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
      </div>
    </div>
  )
}

/* ------------------------------ Toasts ------------------------------ */

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const notify = useCallback((message, tone = 'success') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000)
  }, [])
  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[1100] flex flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`tt-rise pointer-events-auto flex items-center gap-2 rounded-md px-4 py-3 text-sm font-semibold text-white shadow-lg ${t.tone === 'error' ? 'bg-stop' : 'bg-asphalt'}`}>
            {t.tone === 'error' ? <AlertTriangle className="size-4" /> : <CheckCircle2 className="size-4 text-signal" />}
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
