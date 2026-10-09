import axios from 'axios'

const TOKEN_KEY = 'tracktech.token'

// The token is kept in localStorage so a page refresh keeps you signed in.
// Trade-off: any script injected into the page could read it. A production system
// would use an httpOnly cookie plus CSRF protection instead.
export const tokenStore = {
  get: () => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set: (token) => {
    try { localStorage.setItem(TOKEN_KEY, token) } catch { /* storage unavailable */ }
  },
  clear: () => {
    try { localStorage.removeItem(TOKEN_KEY) } catch { /* storage unavailable */ }
  },
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const isLogin = error.config?.url?.includes('/auth/login')
    if (error.response?.status === 401 && !isLogin) {
      tokenStore.clear()
      window.dispatchEvent(new Event('tracktech:logout'))
    }
    return Promise.reject(error)
  },
)

/** Turn any API error into one readable sentence for the UI. */
export function errorMessage(error) {
  if (!error) return ''
  if (!error.response) {
    return 'Cannot reach the server. Check that the backend is running on port 8000.'
  }
  const detail = error.response.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: [...], msg: '...'}]
    return detail
      .map((d) => {
        const field = d.loc?.filter((p) => p !== 'body').join(' ')
        const msg = String(d.msg || '').replace(/^Value error, /, '')
        return field ? `${field.replaceAll('_', ' ')}: ${msg}` : msg
      })
      .join('. ')
  }
  return `Request failed (${error.response.status}).`
}

/** Build a query string, repeating keys for arrays (?status=A&status=B). */
export function qs(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v))
    else search.append(key, value)
  })
  const s = search.toString()
  return s ? `?${s}` : ''
}

/** Download a file from an authenticated endpoint. */
export async function downloadFile(path, fallbackName) {
  const response = await api.get(path, { responseType: 'blob' })
  const disposition = response.headers['content-disposition'] || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = match ? match[1] : fallbackName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
