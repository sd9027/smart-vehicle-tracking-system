import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Button, ErrorBanner, Input, Plate } from '../components/ui'
import { errorMessage } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={location.state?.from || '/'} replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email, password)
      navigate(location.state?.from || '/', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-hw p-12 text-white lg:flex">
        <span className="font-display text-2xl font-semibold tracking-wide">TrackTech</span>
        <div className="max-w-md">
          <p className="font-display text-5xl font-semibold leading-[1.05]">Every vehicle, every trip, every rupee.</p>
          <p className="mt-4 text-lg text-white/80">
            Live positions, driver assignments, fuel and service costs for your fleet, in one place.
          </p>
          <div className="mt-10 flex flex-wrap gap-3">
            <Plate reg="UK07CA1021" size="lg" />
            <Plate reg="UK07TB4410" size="lg" />
          </div>
        </div>
        <p className="text-sm text-white/60">Vehicle positions in this project are simulated.</p>
        {/* Road centre-line, the only decoration */}
        <div aria-hidden className="absolute right-16 top-0 h-full w-2 bg-[repeating-linear-gradient(to_bottom,#F0A202_0_40px,transparent_40px_80px)] opacity-70" />
      </section>

      <section className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-5">
          <div>
            <h1 className="font-display text-3xl font-semibold">Sign in</h1>
            <p className="mt-1 text-muted">Use the account your administrator gave you.</p>
          </div>
          <ErrorBanner message={error} />
          <Input label="Email" type="email" autoComplete="username" required value={email}
                 onChange={(e) => setEmail(e.target.value)} />
          <Input label="Password" type="password" autoComplete="current-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
          <Button type="submit" busy={busy} className="w-full">Sign in</Button>
        </form>
      </section>
    </div>
  )
}
