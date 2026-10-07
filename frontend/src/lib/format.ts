/**
 * The API sends hospital-local wall-clock times with no zone ("2026-10-07T10:30:00").
 * `new Date()` reads those as local time, so formatting them shows the hospital's clock
 * unchanged, wherever the browser is.
 */
let clockOffsetMs = 0

/** Align "now" with the hospital's clock (from GET /api/clock), not the device's. */
export function syncHospitalClock(serverNow: string) {
  clockOffsetMs = new Date(serverNow).getTime() - Date.now()
}

export const hospitalNow = () => new Date(Date.now() + clockOffsetMs)

const pad = (n: number) => String(n).padStart(2, '0')

/** yyyy-mm-dd in wall-clock terms (toISOString would shift to UTC). */
export const isoDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export const isoDateTime = (d: Date) => `${isoDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`
export const addDays = (d: Date, days: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + days)

type DateInput = string | Date | null | undefined
const toDate = (v: DateInput) => (v ? (v instanceof Date ? v : new Date(v)) : null)

const fmt = (options: Intl.DateTimeFormatOptions) => (v: DateInput) => {
  const d = toDate(v)
  return d && !isNaN(d.getTime()) ? new Intl.DateTimeFormat('en-GB', options).format(d) : '—'
}

export const formatTime = (v: DateInput) => {
  const d = toDate(v)
  if (!d || isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(d)
}
export const formatDate = fmt({ day: 'numeric', month: 'short', year: 'numeric' })
export const formatDay = fmt({ weekday: 'short', day: 'numeric', month: 'short' })
export const formatDateTime = (v: DateInput) => (toDate(v) ? `${formatDay(v)}, ${formatTime(v)}` : '—')

export function relativeDay(v: DateInput): string {
  const d = toDate(v)
  if (!d) return '—'
  const diff = Math.round((new Date(isoDate(d)).getTime() - new Date(isoDate(hospitalNow())).getTime()) / 86_400_000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (diff === -1) return 'Yesterday'
  return formatDay(d)
}

export function timeAgo(v: DateInput): string {
  const d = toDate(v)
  if (!d) return '—'
  const minutes = Math.round((hospitalNow().getTime() - d.getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} h ago`
  return formatDate(d)
}

export const greeting = () => {
  const h = hospitalNow().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export const num = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: digits })

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`)

/** "in_consultation" -> "In consultation" */
export const humanize = (s: string | null | undefined) =>
  s ? s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()) : '—'

export const initials = (name: string) =>
  name.replace(/^Dr\.\s*/, '').split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase()

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}
