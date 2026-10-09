const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
const inrExact = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
const num = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 })

export const money = (v) => (v === null || v === undefined ? '-' : inr.format(v))
export const moneyExact = (v) => (v === null || v === undefined ? '-' : inrExact.format(v))
export const number = (v) => (v === null || v === undefined ? '-' : num.format(v))
export const km = (v) => (v === null || v === undefined ? '-' : `${num.format(v)} km`)

export function dateTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

export function dateOnly(iso) {
  if (!iso) return '-'
  // Plain dates (YYYY-MM-DD) are calendar dates, not instants: avoid timezone shifts.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso)
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

export function timeAgo(iso) {
  if (!iso) return 'never'
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 10) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86400)} d ago`
}

export const monthLabel = (key) => {
  const [y, m] = key.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })
}

/** UK07AB1234 -> UK 07 AB 1234 */
export function formatPlate(reg = '') {
  const standard = reg.match(/^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})$/)
  if (standard) return standard.slice(1).filter(Boolean).join(' ')
  const bharat = reg.match(/^(\d{2})(BH)(\d{4})([A-Z]{1,2})$/)
  if (bharat) return bharat.slice(1).join(' ')
  return reg
}

export const titleCase = (s = '') =>
  s.toLowerCase().replaceAll('_', ' ').replace(/^\w/, (c) => c.toUpperCase())

export const todayISO = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
