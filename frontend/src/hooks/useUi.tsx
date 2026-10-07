/** UI-only state: theme, toasts, debounce. Server state lives in TanStack Query. */
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/format'

// ----------------------------------------------------------------------------- theme
type Theme = 'light' | 'dark'
const THEME_KEY = 'medflow-theme'

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.classList.contains('dark') ? 'dark' : 'light')
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try { localStorage.setItem(THEME_KEY, theme) } catch { /* private mode */ }
  }, [theme])
  return { theme, toggle: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')) }
}

// ----------------------------------------------------------------------------- debounce
export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

// ----------------------------------------------------------------------------- toasts
type Tone = 'success' | 'error' | 'info' | 'warning'
interface Toast { id: number; tone: Tone; title: string; body?: string }
interface ToastApi {
  success: (title: string, body?: string) => void
  info: (title: string, body?: string) => void
  warning: (title: string, body?: string) => void
  /** Shows the API's own message when there is one. */
  error: (err: unknown, fallback?: string) => void
}

const ToastCtx = createContext<ToastApi | null>(null)
const ICONS = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle }
const TONES = { success: 'text-ok', error: 'text-crit', info: 'text-info', warning: 'text-warn' }
let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), [])
  const push = useCallback((tone: Tone, title: string, body?: string) => {
    const id = nextId++
    setToasts((t) => [...t.slice(-3), { id, tone, title, body }])
    setTimeout(() => dismiss(id), tone === 'error' ? 7000 : 4500)
  }, [dismiss])

  const value = useMemo<ToastApi>(() => ({
    success: (title, body) => push('success', title, body),
    info: (title, body) => push('info', title, body),
    warning: (title, body) => push('warning', title, body),
    error: (err, fallback = 'Something went wrong') => {
      if (err instanceof ApiError) push('error', err.message, err.details?.map((d) => d.message).join(' · '))
      else push('error', fallback)
    },
  }), [push])

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-[70] flex flex-col items-center gap-2 px-4 sm:inset-x-auto sm:bottom-6 sm:right-6 sm:items-end">
        <AnimatePresence>
          {toasts.map((t) => {
            const Icon = ICONS[t.tone]
            return (
              <motion.div key={t.id} role={t.tone === 'error' ? 'alert' : 'status'}
                initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.18 }}
                className="pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border bg-surface p-3.5 shadow-lg">
                <Icon className={cn('mt-0.5 size-4.5 shrink-0', TONES[t.tone])} aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{t.title}</p>
                  {t.body && <p className="mt-0.5 text-sm text-muted">{t.body}</p>}
                </div>
                <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="text-subtle hover:text-text">
                  <X className="size-4" />
                </button>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
