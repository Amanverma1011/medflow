import { BookOpen, Building2, CalendarDays, FileText, type LucideIcon, Search, Stethoscope, User } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { useAuth } from '@/hooks/useAuth'
import { useDebounced } from '@/hooks/useUi'
import { cn } from '@/lib/format'
import { useGet } from '@/services/queries'
import { Spinner } from './ui'

interface Result { type: string; id: number; title: string; subtitle: string }
export interface NavItem { label: string; to: string; icon: LucideIcon }

const ICONS: Record<string, LucideIcon> = {
  patient: User, doctor: Stethoscope, department: Building2, appointment: CalendarDays, document: FileText, knowledge: BookOpen,
}
const LABELS: Record<string, string> = {
  patient: 'Patients', doctor: 'Doctors', department: 'Departments', appointment: 'Appointments',
  document: 'Documents', knowledge: 'Knowledge base', page: 'Go to',
}

/** Ctrl/Cmd + K search across everything the signed-in role is allowed to see. */
export function CommandPalette({ open, onClose, pages }: { open: boolean; onClose: () => void; pages: NavItem[] }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { user } = useAuth()
  const term = useDebounced(query.trim(), 200)
  const search = useGet<{ results: Result[] }>('search', '/search', { q: term }, { enabled: open && term.length >= 2 })
  const base = user?.roles.includes('patient') ? '/patient' : user?.roles.length === 1 && user.roles[0] === 'doctor' ? '/doctor' : '/admin'

  const linkFor = (r: Result): string => {
    if (base === '/patient') return r.type === 'knowledge' ? `/patient/chat?source=${r.id}` : '/patient/appointments'
    switch (r.type) {
      case 'patient': return `${base}/patients/${r.id}`
      case 'doctor': return '/admin/doctors'
      case 'department': return '/admin/departments'
      case 'appointment': return `${base}/appointments`
      case 'document': return '/admin/knowledge'
      default: return `${base === '/doctor' ? '/doctor' : '/admin'}/assistant?source=${r.id}`
    }
  }

  const items = useMemo(() => {
    const matches = pages.filter((p) => !term || p.label.toLowerCase().includes(term.toLowerCase()))
      .map((p) => ({ type: 'page', key: p.to, title: p.label, subtitle: '', icon: p.icon, to: p.to }))
    const found = term.length >= 2 ? (search.data?.results ?? []).map((r) => ({
      type: r.type, key: `${r.type}-${r.id}`, title: r.title, subtitle: r.subtitle, icon: ICONS[r.type] ?? Search, to: linkFor(r),
    })) : []
    return [...found, ...matches.slice(0, term ? 6 : 8)]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.data, term, pages])

  useEffect(() => { if (open) { setQuery(''); setActive(0); setTimeout(() => inputRef.current?.focus(), 10) } }, [open])
  useEffect(() => setActive(0), [term])

  if (!open) return null
  const go = (to: string) => { onClose(); navigate(to) }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    if (e.key === 'Enter' && items[active]) go(items[active].to)
  }

  let lastType = ''
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center p-3 pt-[12vh]" onKeyDown={onKey}>
      <div className="absolute inset-0 bg-black/45" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" aria-label="Search" className="relative w-full max-w-xl overflow-hidden rounded-2xl border bg-surface shadow-2xl">
        <div className="flex items-center gap-3 border-b px-4">
          <Search className="size-4 text-subtle" aria-hidden />
          <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)} maxLength={80}
            placeholder="Search patients, doctors, appointments, knowledge…" aria-label="Search"
            role="combobox" aria-expanded="true" aria-controls="palette-results" aria-activedescendant={items[active] ? `palette-${active}` : undefined}
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle" />
          {search.isFetching ? <Spinner className="size-4" /> : <kbd className="rounded border px-1.5 py-0.5 text-[10px] text-subtle">Esc</kbd>}
        </div>
        <ul id="palette-results" role="listbox" className="max-h-[52dvh] overflow-y-auto p-1.5">
          {items.length === 0 && (
            <li className="px-3 py-8 text-center text-sm text-muted">{term.length < 2 ? 'Type at least two characters to search.' : `No results for “${term}”.`}</li>
          )}
          {items.map((item, i) => {
            const heading = item.type !== lastType
            lastType = item.type
            return (
              <li key={item.key} role="presentation">
                {heading && <p className="px-3 pt-2.5 pb-1 text-[11px] font-medium text-subtle uppercase">{LABELS[item.type] ?? item.type}</p>}
                <button id={`palette-${i}`} role="option" aria-selected={i === active} onClick={() => go(item.to)} onMouseEnter={() => setActive(i)}
                  className={cn('flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left', i === active && 'bg-surface-2')}>
                  <item.icon className="size-4 shrink-0 text-subtle" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{item.title}</span>
                    {item.subtitle && <span className="block truncate text-xs text-muted">{item.subtitle}</span>}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}

/** Opens the palette on Ctrl/Cmd + K from anywhere. */
export function usePaletteShortcut(setOpen: (fn: (open: boolean) => boolean) => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setOpen((o) => !o) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setOpen])
}
