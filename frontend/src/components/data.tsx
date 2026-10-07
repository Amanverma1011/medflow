/** Data display: metric cards, tables, status and department badges, pagination. */
import { ArrowDownRight, ArrowUpRight, ChevronLeft, ChevronRight, type LucideIcon, Minus } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn, humanize, num } from '@/lib/format'
import type { Metric } from '@/types'
import { Badge, Button, Card, EmptyState, type Tone } from './ui'

// ----------------------------------------------------------------------------- trend
export function Trend({ value, lowerIsBetter, suffix = '%' }: { value: number | null | undefined; lowerIsBetter?: boolean; suffix?: string }) {
  if (value === null || value === undefined) return null
  const flat = Math.abs(value) < 0.05
  const good = flat ? null : (value < 0) === !!lowerIsBetter
  const Icon = flat ? Minus : value > 0 ? ArrowUpRight : ArrowDownRight
  return (
    <span className={cn('inline-flex items-center gap-0.5 text-xs font-medium tabular',
      good === null ? 'text-subtle' : good ? 'text-ok' : 'text-crit')}>
      <Icon className="size-3.5" aria-hidden />
      {value > 0 ? '+' : ''}{num(value, 1)}{suffix}
      <span className="sr-only">{good === null ? 'no change' : good ? 'improving' : 'worsening'}</span>
    </span>
  )
}

// ----------------------------------------------------------------------------- metric cards
interface MetricCardProps {
  label: string
  value: ReactNode
  unit?: string
  trend?: number | null
  lowerIsBetter?: boolean
  compare?: string
  icon?: LucideIcon
  tone?: Tone
  footer?: ReactNode
}

/** A single headline number with its trend. */
export function MetricCard({ label, value, unit, trend, lowerIsBetter, compare, icon: Icon, tone = 'neutral', footer }: MetricCardProps) {
  const accent = { neutral: 'text-subtle', ok: 'text-ok', warn: 'text-warn', crit: 'text-crit', info: 'text-info', brand: 'text-brand' }[tone]
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] font-medium text-muted">{label}</p>
        {Icon && <Icon className={cn('size-4', accent)} aria-hidden />}
      </div>
      <p className="mt-2 flex items-baseline gap-1.5">
        <span className={cn('text-2xl font-semibold tabular', tone !== 'neutral' && tone !== 'brand' && accent)}>{value}</span>
        {unit && <span className="text-sm text-muted">{unit}</span>}
      </p>
      <div className="mt-1.5 flex min-h-5 items-center gap-1.5 text-xs text-subtle">
        <Trend value={trend} lowerIsBetter={lowerIsBetter} />
        {compare && trend !== null && trend !== undefined && <span>{compare}</span>}
        {footer}
      </div>
    </Card>
  )
}

/** A titled panel on a dashboard. */
export function DashboardCard({ title, subtitle, action, children, className, flush }: {
  title: string; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean
}) {
  return (
    <Card className={cn('flex flex-col', className)}>
      <div className="flex items-start justify-between gap-3 px-4 pt-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-subtle">{subtitle}</p>}
        </div>
        {action}
      </div>
      <div className={cn('flex-1', flush ? 'pt-3' : 'p-4')}>{children}</div>
    </Card>
  )
}

export function metricText(m?: Metric): string | undefined {
  if (!m || m.value === null || m.value === undefined) return undefined
  return typeof m.value === 'number' ? num(m.value, 1) : m.value
}

// ----------------------------------------------------------------------------- badges
const STATUS_TONE: Record<string, Tone> = {
  scheduled: 'info', checked_in: 'brand', waiting: 'warn', in_consultation: 'brand', completed: 'ok',
  cancelled: 'neutral', no_show: 'crit', called: 'brand', skipped: 'neutral',
  active: 'ok', admitted: 'info', discharged: 'neutral', inactive: 'neutral',
  available: 'ok', occupied: 'info', cleaning: 'warn', maintenance: 'crit', reserved: 'brand',
  indexed: 'ok', processing: 'info', uploaded: 'info', failed: 'crit', archived: 'neutral',
  positive: 'ok', neutral: 'neutral', negative: 'crit',
  low: 'neutral', medium: 'warn', high: 'crit', critical: 'crit',
  open: 'warn', in_review: 'info', resolved: 'ok', success: 'ok', failure: 'crit', denied: 'crit',
}

/** Status is always shown as a word, never by colour alone. */
export function StatusBadge({ status, className }: { status: string | null | undefined; className?: string }) {
  if (!status) return <span className="text-subtle">—</span>
  return <Badge tone={STATUS_TONE[status] ?? 'neutral'} className={className}>{humanize(status)}</Badge>
}

export function DepartmentBadge({ name }: { name: string | null | undefined }) {
  if (!name) return <span className="text-subtle">—</span>
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      <span className="size-1.5 rounded-full bg-brand" aria-hidden />
      {name}
    </span>
  )
}

// ----------------------------------------------------------------------------- table
export interface Column<T> {
  key: string
  header: string
  cell: (row: T) => ReactNode
  className?: string
  /** Hide on small screens to keep the table readable. */
  hideBelow?: 'sm' | 'md' | 'lg'
}

const HIDE = { sm: 'hidden sm:table-cell', md: 'hidden md:table-cell', lg: 'hidden lg:table-cell' }

export function DataTable<T>({ columns, rows, rowKey, onRowClick, empty, caption, dim }: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  onRowClick?: (row: T) => void
  empty?: { title: string; body?: string }
  caption: string
  /** Fade while a refetch is in flight. */
  dim?: boolean
}) {
  if (!rows.length) return <EmptyState title={empty?.title ?? 'Nothing to show'} body={empty?.body} />
  return (
    <div className={cn('overflow-x-auto transition-opacity', dim && 'opacity-60')}>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b text-xs text-subtle">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cn('px-4 py-2.5 font-medium whitespace-nowrap', c.hideBelow && HIDE[c.hideBelow], c.className)}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick && (() => onRowClick(row))}
              onKeyDown={onRowClick && ((e) => { if (e.key === 'Enter') onRowClick(row) })}
              className={cn('border-b last:border-0', onRowClick && 'cursor-pointer hover:bg-surface-2 focus-visible:bg-surface-2')}>
              {columns.map((c) => (
                <td key={c.key} className={cn('px-4 py-3 align-middle', c.hideBelow && HIDE[c.hideBelow], c.className)}>{c.cell(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Pagination({ page, size, total, onChange }: { page: number; size: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  if (total <= size) return null
  return (
    <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-sm text-muted">
      <span className="tabular">{(page - 1) * size + 1}–{Math.min(page * size, total)} of {num(total)}</span>
      <div className="flex items-center gap-1.5">
        <Button size="sm" icon={ChevronLeft} disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Previous page" />
        <span className="px-1 tabular">Page {page} of {pages}</span>
        <Button size="sm" icon={ChevronRight} disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Next page" />
      </div>
    </div>
  )
}

/** Confidence shown as a labelled bar, used wherever the AI estimates something. */
export function Confidence({ value, className }: { value: number; className?: string }) {
  const percent = Math.round(value * 100)
  return (
    <div className={cn('flex items-center gap-2 text-xs text-muted', className)}>
      <span>Confidence</span>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-2" role="meter" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Confidence">
        <div className="h-full rounded-full bg-brand" style={{ width: `${percent}%` }} />
      </div>
      <span className="font-medium text-text tabular">{percent}%</span>
    </div>
  )
}
