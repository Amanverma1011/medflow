/** Primitive building blocks. Everything else composes these. */
import { AnimatePresence, motion } from 'framer-motion'
import { AlertCircle, Inbox, Loader2, type LucideIcon, X } from 'lucide-react'
import {
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
  type TextareaHTMLAttributes, useEffect, useId, useRef,
} from 'react'
import { ApiError } from '@/lib/api'
import { cn } from '@/lib/format'

// ----------------------------------------------------------------------------- button
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-brand text-on-brand hover:bg-brand-strong',
  secondary: 'border bg-surface text-text hover:bg-surface-2',
  ghost: 'text-muted hover:bg-surface-2 hover:text-text',
  danger: 'bg-crit text-white hover:opacity-90',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'sm' | 'md'
  loading?: boolean
  icon?: LucideIcon
}

export function Button({ variant = 'secondary', size = 'md', loading, icon: Icon, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button {...rest} disabled={disabled || loading} type={rest.type ?? 'button'}
      className={cn('inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors disabled:opacity-50',
        size === 'sm' ? 'h-8 px-2.5 text-[13px]' : 'h-10 px-4 text-sm', VARIANTS[variant], className)}>
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : Icon && <Icon className="size-4" aria-hidden />}
      {children}
    </button>
  )
}

// ----------------------------------------------------------------------------- surfaces
export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={cn('rounded-xl border bg-surface shadow-card', className)}>{children}</div>
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold">{children}</h2>
      {aside}
    </div>
  )
}

// ----------------------------------------------------------------------------- badge
export type Tone = 'neutral' | 'ok' | 'warn' | 'crit' | 'info' | 'brand'
const BADGE: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-muted',
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  crit: 'bg-crit-soft text-crit',
  info: 'bg-info-soft text-info',
  brand: 'bg-brand-soft text-brand',
}

export function Badge({ tone = 'neutral', icon: Icon, children, className }: { tone?: Tone; icon?: LucideIcon; children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium whitespace-nowrap', BADGE[tone], className)}>
      {Icon && <Icon className="size-3" aria-hidden />}
      {children}
    </span>
  )
}

// ----------------------------------------------------------------------------- form fields
const FIELD = 'h-10 w-full rounded-lg border bg-surface px-3 text-sm text-text placeholder:text-subtle disabled:opacity-60'

interface FieldProps { label?: string; error?: string; hint?: string }

function Labelled({ id, label, error, hint, children }: FieldProps & { id: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      {label && <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium text-muted">{label}</label>}
      {children}
      {error ? <p id={`${id}-error`} role="alert" className="mt-1 text-xs text-crit">{error}</p>
        : hint && <p className="mt-1 text-xs text-subtle">{hint}</p>}
    </div>
  )
}

export function Input({ label, error, hint, className, ...rest }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId()
  return (
    <Labelled id={rest.id ?? id} label={label} error={error} hint={hint}>
      <input {...rest} id={rest.id ?? id} aria-invalid={!!error} aria-describedby={error ? `${rest.id ?? id}-error` : undefined}
        className={cn(FIELD, error && 'border-crit', className)} />
    </Labelled>
  )
}

export function Select({ label, error, hint, className, children, ...rest }: FieldProps & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId()
  return (
    <Labelled id={rest.id ?? id} label={label} error={error} hint={hint}>
      <select {...rest} id={rest.id ?? id} aria-invalid={!!error} className={cn(FIELD, 'pr-8', className)}>{children}</select>
    </Labelled>
  )
}

export function Textarea({ label, error, hint, className, ...rest }: FieldProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId()
  return (
    <Labelled id={rest.id ?? id} label={label} error={error} hint={hint}>
      <textarea {...rest} id={rest.id ?? id} aria-invalid={!!error} className={cn(FIELD, 'h-auto min-h-24 py-2', className)} />
    </Labelled>
  )
}

// ----------------------------------------------------------------------------- async states
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('size-5 animate-spin text-subtle', className)} aria-label="Loading" />
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-pulse rounded-lg bg-surface-2', className)} />
}

/** Placeholder shaped like the content it replaces, so layout does not jump. */
export function LoadingSkeleton({ rows = 4, variant = 'list' }: { rows?: number; variant?: 'list' | 'cards' | 'chart' }) {
  if (variant === 'chart') return <Skeleton className="h-64 w-full" />
  if (variant === 'cards') {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6" role="status" aria-label="Loading">
        {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-28" />)}
      </div>
    )
  }
  return (
    <div className="space-y-2.5" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-11" />)}
    </div>
  )
}

export function EmptyState({ icon: Icon = Inbox, title, body, action }: { icon?: LucideIcon; title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <div className="mb-3 flex size-11 items-center justify-center rounded-full bg-surface-2 text-subtle"><Icon className="size-5" aria-hidden /></div>
      <p className="text-sm font-medium">{title}</p>
      {body && <p className="mt-1 max-w-sm text-sm text-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, what = 'this page', onRetry }: { error?: unknown; what?: string; onRetry?: () => void }) {
  const status = error instanceof ApiError ? error.status : 0
  const title = status === 403 ? "You don't have access" : status === 404 ? 'Not found' : 'Something went wrong'
  const body = status === 403 ? `Your role doesn't include ${what}.`
    : error instanceof ApiError && status !== 500 ? error.message : `We couldn't load ${what}.`
  return (
    <div role="alert" className="flex flex-col items-center px-6 py-10 text-center">
      <div className="mb-3 flex size-11 items-center justify-center rounded-full bg-crit-soft text-crit"><AlertCircle className="size-5" aria-hidden /></div>
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 max-w-sm text-sm text-muted">{body}</p>
      {onRetry && status !== 403 && <Button className="mt-4" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

/** Renders loading / error / empty / data for one query in a consistent way. */
export function Async<T>({ query, what, skeleton, empty, children }: {
  query: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown }
  what: string
  skeleton?: ReactNode
  empty?: (data: T) => ReactNode | false
  children: (data: T) => ReactNode
}) {
  if (query.isLoading) return <>{skeleton ?? <LoadingSkeleton />}</>
  if (query.error || query.data === undefined) return <ErrorState error={query.error} what={what} onRetry={() => query.refetch()} />
  return <>{empty?.(query.data) || children(query.data)}</>
}

// ----------------------------------------------------------------------------- modal
export function Modal({ open, onClose, title, description, children, footer, wide }: {
  open: boolean; onClose: () => void; title: string; description?: string; children: ReactNode; footer?: ReactNode; wide?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key !== 'Tab' || !ref.current) return
      // Keep focus inside the dialog.
      const focusable = ref.current.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])')
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      previous?.focus()
    }
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/45" onClick={onClose} aria-hidden />
          <motion.div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 12 }} transition={{ duration: 0.18 }}
            className={cn('relative flex max-h-[92dvh] w-full flex-col rounded-t-2xl border bg-surface shadow-2xl outline-none sm:rounded-2xl', wide ? 'sm:max-w-3xl' : 'sm:max-w-lg')}>
            <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
              <div>
                <h2 id={titleId} className="text-base font-semibold">{title}</h2>
                {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
              </div>
              <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-subtle hover:bg-surface-2 hover:text-text"><X className="size-4.5" /></button>
            </div>
            <div className="overflow-y-auto px-5 py-4">{children}</div>
            {footer && <div className="flex justify-end gap-2 border-t px-5 py-3.5">{footer}</div>}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}

export function ConfirmDialog({ open, onClose, onConfirm, title, body, confirmLabel = 'Confirm', danger, loading }: {
  open: boolean; onClose: () => void; onConfirm: () => void; title: string; body: string; confirmLabel?: string; danger?: boolean; loading?: boolean
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={loading}>{confirmLabel}</Button>
      </>}>
      <p className="text-sm text-muted">{body}</p>
    </Modal>
  )
}

// ----------------------------------------------------------------------------- tabs
export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: string }[]; value: T; onChange: (id: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="mb-5 flex gap-1 overflow-x-auto border-b">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cn('-mb-px border-b-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap transition-colors',
            value === t.id ? 'border-brand text-text' : 'border-transparent text-muted hover:text-text')}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

/** Small "these numbers are synthetic" marker. */
export function DemoTag({ children = 'Synthetic demo data' }: { children?: ReactNode }) {
  return <span className="shrink-0 rounded-full border border-dashed px-2 py-0.5 text-[11px] font-medium whitespace-nowrap text-subtle">{children}</span>
}
