import {
  Activity, BarChart3, BedDouble, BookOpen, Bug, Building2, CalendarDays, ClipboardList, FileBarChart, FileText, Home,
  LayoutDashboard, ListOrdered, LogOut, type LucideIcon, Menu, MessageSquareHeart, Moon, Radar, Search, Settings,
  ShieldCheck, Smile, Sparkles, Stethoscope, Sun, User, Users, X,
} from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { Avatar } from '@/components/cards'
import { CommandPalette, type NavItem, usePaletteShortcut } from '@/components/CommandPalette'
import { NotificationPanel } from '@/components/NotificationPanel'
import { useAuth } from '@/hooks/useAuth'
import { useRealtime } from '@/hooks/useRealtime'
import { useTheme } from '@/hooks/useUi'
import { cn, formatDay, formatTime, hospitalNow, humanize } from '@/lib/format'

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('flex items-center gap-2 font-semibold tracking-tight', className)}>
      <span aria-hidden className="flex size-7 items-center justify-center rounded-lg bg-brand text-on-brand"><Activity className="size-4" strokeWidth={2.5} /></span>
      MedFlow <span className="-ml-1 text-brand">AI</span>
    </span>
  )
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  return (
    <button onClick={toggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      className="flex size-9 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-text">
      {theme === 'dark' ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
    </button>
  )
}

function useClock() {
  const [now, setNow] = useState(hospitalNow)
  useEffect(() => {
    const id = setInterval(() => setNow(hospitalNow()), 30_000)
    return () => clearInterval(id)
  }, [])
  return now
}

function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  if (!user) return null
  return (
    <div className="flex items-center gap-2.5">
      <div className="hidden text-right leading-tight md:block">
        <p className="text-sm font-medium">{user.full_name}</p>
        <p className="text-[11px] text-subtle">{user.roles.map(humanize).join(', ')}</p>
      </div>
      <Avatar name={user.full_name} className="size-8" />
      <button onClick={async () => { await logout(); navigate('/login') }} aria-label="Sign out" title="Sign out"
        className="flex size-9 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-text">
        <LogOut className="size-[18px]" />
      </button>
    </div>
  )
}

function SkipLink() {
  return <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[80] focus:rounded-lg focus:bg-brand focus:px-3 focus:py-2 focus:text-sm focus:text-on-brand">Skip to content</a>
}

// ----------------------------------------------------------------------------- staff
interface StaffNav extends NavItem { permission?: string; section?: string }

const ADMIN_NAV: StaffNav[] = [
  { label: 'Overview', to: '/admin/dashboard', icon: LayoutDashboard, permission: 'analytics:read' },
  { label: 'Command Center', to: '/admin/command-center', icon: Radar, permission: 'analytics:read' },
  { label: 'Patients', to: '/admin/patients', icon: Users, permission: 'patients:read', section: 'Operations' },
  { label: 'Appointments', to: '/admin/appointments', icon: CalendarDays, permission: 'appointments:read' },
  { label: 'Queue', to: '/admin/queue', icon: ListOrdered, permission: 'queue:read' },
  { label: 'Doctors', to: '/admin/doctors', icon: Stethoscope },
  { label: 'Departments', to: '/admin/departments', icon: Building2 },
  { label: 'Beds & Resources', to: '/admin/beds', icon: BedDouble, permission: 'beds:read' },
  { label: 'Patient Experience', to: '/admin/experience', icon: Smile, permission: 'experience:read', section: 'Intelligence' },
  { label: 'Analytics', to: '/admin/analytics', icon: BarChart3, permission: 'analytics:read' },
  { label: 'AI Insights', to: '/admin/ai-insights', icon: Sparkles, permission: 'insights:read' },
  { label: 'Reports', to: '/admin/reports', icon: FileBarChart, permission: 'reports:read' },
  { label: 'Medical Assistant', to: '/admin/assistant', icon: MessageSquareHeart, permission: 'chat:use', section: 'Knowledge' },
  { label: 'Medical Knowledge', to: '/admin/knowledge', icon: BookOpen, permission: 'knowledge:manage' },
  { label: 'RAG Debugger', to: '/admin/rag-debug', icon: Bug, permission: 'rag:debug' },
  { label: 'Audit Logs', to: '/admin/audit', icon: ShieldCheck, permission: 'audit:read', section: 'System' },
  { label: 'Settings', to: '/admin/settings', icon: Settings, permission: 'settings:read' },
]
const DOCTOR_NAV: StaffNav[] = [
  { label: 'Dashboard', to: '/doctor/dashboard', icon: LayoutDashboard },
  { label: 'Appointments', to: '/doctor/appointments', icon: CalendarDays },
  { label: 'My Patients', to: '/doctor/patients', icon: Users },
  { label: 'Beds', to: '/admin/beds', icon: BedDouble, section: 'Hospital' },
  { label: 'Doctors', to: '/admin/doctors', icon: Stethoscope },
  { label: 'Departments', to: '/admin/departments', icon: Building2 },
  { label: 'Medical Assistant', to: '/doctor/assistant', icon: MessageSquareHeart, section: 'Knowledge' },
]

export function StaffLayout() {
  const { user, can } = useAuth()
  const [drawer, setDrawer] = useState(false)
  const [palette, setPalette] = useState(false)
  const location = useLocation()
  const now = useClock()
  useRealtime(user?.id)
  usePaletteShortcut(setPalette)
  useEffect(() => setDrawer(false), [location.pathname])

  const nav = useMemo(() => {
    const doctorOnly = user?.roles.length === 1 && user.roles[0] === 'doctor'
    return (doctorOnly ? DOCTOR_NAV : ADMIN_NAV).filter((item) => !item.permission || can(item.permission))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col">
      <div className="flex h-14 items-center justify-between px-4">
        <Link to={user?.home ?? '/'} aria-label="MedFlow AI home"><Logo /></Link>
        <button className="rounded-md p-1 text-subtle lg:hidden" onClick={() => setDrawer(false)} aria-label="Close menu"><X className="size-5" /></button>
      </div>
      <ul className="flex-1 space-y-0.5 overflow-y-auto px-2.5 pb-4">
        {nav.map((item) => (
          <li key={item.to}>
            {item.section && <p className="px-2.5 pt-4 pb-1.5 text-[11px] font-medium tracking-wide text-subtle uppercase">{item.section}</p>}
            <NavLink to={item.to} className={({ isActive }) => cn('flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors',
              isActive ? 'bg-brand-soft font-medium text-brand' : 'text-muted hover:bg-surface-2 hover:text-text')}>
              <item.icon className="size-[17px] shrink-0" aria-hidden />
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
      <p className="border-t px-4 py-3 text-[11px] leading-snug text-subtle">Synthetic demo data. Not certified for production clinical use.</p>
    </nav>
  )

  return (
    <div className="min-h-dvh lg:pl-60" style={{ '--chrome': '3.5rem' } as React.CSSProperties}>
      <SkipLink />
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r bg-surface lg:block">{sidebar}</aside>
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/45" onClick={() => setDrawer(false)} aria-hidden />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r bg-surface shadow-2xl">{sidebar}</aside>
        </div>
      )}
      <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-surface/90 px-3 backdrop-blur sm:px-5">
        <button className="rounded-lg p-2 text-muted hover:bg-surface-2 lg:hidden" onClick={() => setDrawer(true)} aria-label="Open menu"><Menu className="size-5" /></button>
        <div className="hidden min-w-0 leading-tight md:block">
          <p className="truncate text-sm font-semibold">MedFlow General Hospital</p>
          <p className="text-[11px] text-subtle tabular" title="Hospital local time">{formatDay(now)} · {formatTime(now)}</p>
        </div>
        <button onClick={() => setPalette(true)}
          className="ml-auto flex h-9 w-full max-w-xs items-center gap-2 rounded-lg border bg-bg px-3 text-sm text-subtle hover:border-brand md:ml-6">
          <Search className="size-4" aria-hidden />
          <span className="flex-1 truncate text-left">Search…</span>
          <kbd className="hidden rounded border bg-surface px-1.5 py-0.5 text-[10px] sm:block">Ctrl K</kbd>
        </button>
        <div className="ml-auto flex items-center gap-1">
          {can('copilot:use') && (
            <Link to="/admin/ai-insights?tab=copilot" className="hidden h-9 items-center gap-1.5 rounded-lg bg-brand-soft px-3 text-sm font-medium text-brand hover:opacity-90 sm:flex">
              <Sparkles className="size-4" aria-hidden />Copilot
            </Link>
          )}
          <ThemeToggle />
          <NotificationPanel />
          <span className="mx-1 hidden h-6 w-px bg-border sm:block" aria-hidden />
          <UserMenu />
        </div>
      </header>
      <main id="main" className="p-4 sm:p-6"><Outlet /></main>
      <CommandPalette open={palette} onClose={() => setPalette(false)} pages={nav} />
    </div>
  )
}

// ----------------------------------------------------------------------------- patient
const PATIENT_TABS: { label: string; to: string; icon: LucideIcon }[] = [
  { label: 'Home', to: '/patient/dashboard', icon: Home },
  { label: 'Appointments', to: '/patient/appointments', icon: CalendarDays },
  { label: 'Queue', to: '/patient/queue', icon: ClipboardList },
  { label: 'Assistant', to: '/patient/chat', icon: MessageSquareHeart },
  { label: 'Profile', to: '/patient/profile', icon: User },
]
const PATIENT_MORE: NavItem[] = [
  { label: 'Documents', to: '/patient/documents', icon: FileText },
  { label: 'Feedback', to: '/patient/feedback', icon: Smile },
]

/** Mobile-first: bottom tab bar on phones, top navigation from tablet up. */
export function PatientLayout() {
  const { user } = useAuth()
  const [palette, setPalette] = useState(false)
  useRealtime(user?.id)
  usePaletteShortcut(setPalette)
  return (
    <div className="min-h-dvh pb-16 md:pb-0 [--chrome:7.5rem] md:[--chrome:3.5rem]">
      <SkipLink />
      <header className="sticky top-0 z-20 border-b bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4">
          <Link to="/patient/dashboard" aria-label="MedFlow AI home"><Logo /></Link>
          <nav aria-label="Main" className="ml-4 hidden items-center gap-1 md:flex">
            {[...PATIENT_TABS.slice(0, 4), ...PATIENT_MORE].map((t) => (
              <NavLink key={t.to} to={t.to} className={({ isActive }) => cn('rounded-lg px-3 py-1.5 text-sm',
                isActive ? 'bg-brand-soft font-medium text-brand' : 'text-muted hover:bg-surface-2 hover:text-text')}>{t.label}</NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <button onClick={() => setPalette(true)} aria-label="Search" className="flex size-9 items-center justify-center rounded-lg text-muted hover:bg-surface-2"><Search className="size-[18px]" /></button>
            <ThemeToggle />
            <NotificationPanel />
            <Link to="/patient/profile" className="ml-1 hidden md:block" aria-label="Profile"><Avatar name={user?.full_name ?? '?'} className="size-8" /></Link>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-5xl p-4 sm:p-6"><Outlet /></main>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-5 border-t bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">
        {PATIENT_TABS.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => cn('flex h-16 flex-col items-center justify-center gap-1 text-[11px]',
            isActive ? 'font-medium text-brand' : 'text-subtle')}>
            <t.icon className="size-5" aria-hidden />{t.label}
          </NavLink>
        ))}
      </nav>
      <CommandPalette open={palette} onClose={() => setPalette(false)} pages={[...PATIENT_TABS, ...PATIENT_MORE]} />
    </div>
  )
}

export function PublicShell({ children }: { children: ReactNode }) {
  return <div className="min-h-dvh bg-bg">{children}</div>
}
