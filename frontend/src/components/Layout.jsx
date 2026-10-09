import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import {
  BarChart3, Database, Fuel, KeyRound, LayoutDashboard, LogOut, Map, Menu, Route, Truck, UserCog, Users, X,
} from 'lucide-react'
import { useAuth } from '../lib/auth'
import { titleCase } from '../lib/format'
import ChangePasswordModal from './ChangePasswordModal'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/tracking', label: 'Live tracking', icon: Map },
  { to: '/vehicles', label: 'Vehicles', icon: Truck },
  { to: '/drivers', label: 'Drivers', icon: Users },
  { to: '/trips', label: 'Trips', icon: Route },
  { to: '/expenses', label: 'Fuel and maintenance', icon: Fuel },
  { to: '/reports', label: 'Reports', icon: BarChart3 },
  { to: '/transactions', label: 'Transaction lab', icon: Database },
  { to: '/users', label: 'Users', icon: UserCog, role: 'ADMIN' },
]

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-5 py-5">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="6" fill="#fff" fillOpacity="0.12" />
        <path d="M8 24 L14 8 h4 l6 16" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinejoin="round" />
        <path d="M16 11v3M16 17v3" stroke="#F0A202" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      <span className="font-display text-2xl font-semibold tracking-wide text-white">TrackTech</span>
    </div>
  )
}

export default function Layout() {
  const { user, logout, can } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)

  const nav = (
    <nav className="flex flex-1 flex-col gap-0.5 px-3" aria-label="Main">
      {NAV.filter((item) => !item.role || can(item.role)).map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={() => setMenuOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-md px-3 py-2 font-medium transition-colors ${
              isActive ? 'bg-white text-hw' : 'text-white/80 hover:bg-white/10 hover:text-white'
            }`}
        >
          <Icon className="size-[18px]" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  )

  const account = (
    <div className="border-t border-white/15 px-5 py-4 text-white">
      <p className="truncate font-semibold">{user?.name}</p>
      <p className="truncate text-sm text-white/70">{user?.email}</p>
      <p className="mt-1 inline-block rounded-sm bg-white/15 px-1.5 py-0.5 text-xs font-semibold">{titleCase(user?.role)}</p>
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={() => setPasswordOpen(true)} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-white/80 hover:bg-white/10">
          <KeyRound className="size-4" aria-hidden /> Password
        </button>
        <button type="button" onClick={logout} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-white/80 hover:bg-white/10">
          <LogOut className="size-4" aria-hidden /> Sign out
        </button>
      </div>
    </div>
  )

  return (
    <div className="flex h-full">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col bg-hw lg:flex">
        <Brand />
        {nav}
        {account}
      </aside>

      {/* Mobile drawer */}
      {menuOpen && (
        <div className="fixed inset-0 z-[1001] flex lg:hidden">
          <aside className="flex w-72 flex-col bg-hw">
            <div className="flex items-center justify-between pr-3">
              <Brand />
              <button type="button" aria-label="Close menu" onClick={() => setMenuOpen(false)} className="rounded p-1 text-white"><X className="size-6" /></button>
            </div>
            {nav}
            {account}
          </aside>
          <button type="button" aria-label="Close menu" className="flex-1 bg-asphalt/50" onClick={() => setMenuOpen(false)} />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-white px-4 py-3 lg:hidden">
          <button type="button" aria-label="Open menu" onClick={() => setMenuOpen(true)} className="rounded p-1"><Menu className="size-6" /></button>
          <span className="font-display text-xl font-semibold text-hw">TrackTech</span>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <Outlet />
          </div>
        </main>
      </div>

      <ChangePasswordModal open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </div>
  )
}
