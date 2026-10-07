/** Domain cards: insights, predictions, queue tokens, appointments, doctors, patients. */
import { AlertTriangle, CalendarClock, Clock, Lightbulb, MapPin, Sparkles, Star, Stethoscope, User, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn, formatTime, humanize, initials, relativeDay } from '@/lib/format'
import type { Appointment, Doctor, Factor, Insight, PatientRow, QueueEstimate } from '@/types'
import { Confidence, StatusBadge } from './data'
import { Badge, Button, Card, type Tone } from './ui'

export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span aria-hidden className={cn('flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand', className)}>
      {initials(name)}
    </span>
  )
}

/** Marks content as machine-generated, with a tooltip saying what kind. */
export function AiLabel({ children = 'AI recommendation', title }: { children?: ReactNode; title?: string }) {
  return <Badge tone="brand" icon={Sparkles}><span title={title}>{children}</span></Badge>
}

// ----------------------------------------------------------------------------- explainability
/** "Main contributing factors" list shown beside every prediction. */
export function Factors({ factors, title = 'Main contributing factors' }: { factors: Factor[]; title?: string }) {
  if (!factors.length) return null
  return (
    <div>
      <p className="mb-1.5 text-xs font-medium text-muted">{title}</p>
      <ul className="space-y-1 text-sm">
        {factors.map((f) => (
          <li key={f.name + f.detail} className="flex gap-2">
            <span className="mt-2 size-1 shrink-0 rounded-full bg-subtle" aria-hidden />
            <span><span className="font-medium">{f.name}</span><span className="text-muted">: {f.detail}</span></span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function PredictionCard({ title, value, unit, confidence, factors, label, extra }: {
  title: string; value: ReactNode; unit?: string; confidence: number; factors: Factor[]; label: string; extra?: ReactNode
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[13px] font-medium text-muted">{title}</p>
        <AiLabel title={label}>Prediction</AiLabel>
      </div>
      <p className="mt-2 flex items-baseline gap-1.5">
        <span className="text-2xl font-semibold tabular">{value}</span>
        {unit && <span className="text-sm text-muted">{unit}</span>}
      </p>
      <Confidence value={confidence} className="mt-2" />
      {extra}
      <div className="mt-3 border-t pt-3"><Factors factors={factors} /></div>
      <p className="mt-3 text-[11px] text-subtle">{label}</p>
    </Card>
  )
}

// ----------------------------------------------------------------------------- insight
const SEVERITY: Record<Insight['severity'], { tone: Tone; bar: string }> = {
  critical: { tone: 'crit', bar: 'bg-crit' }, high: { tone: 'crit', bar: 'bg-crit' },
  medium: { tone: 'warn', bar: 'bg-warn' }, low: { tone: 'info', bar: 'bg-info' },
}

export function AIInsightCard({ insight, onDismiss, compact }: { insight: Insight; onDismiss?: () => void; compact?: boolean }) {
  const s = SEVERITY[insight.severity]
  return (
    <Card className="relative overflow-hidden">
      <span className={cn('absolute inset-y-0 left-0 w-1', s.bar)} aria-hidden />
      <div className="p-4 pl-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={s.tone} icon={AlertTriangle}>{humanize(insight.severity)}</Badge>
          <AiLabel title={insight.label} />
          {onDismiss && (
            <button onClick={onDismiss} aria-label={`Dismiss insight: ${insight.title}`} className="ml-auto rounded-md p-1 text-subtle hover:bg-surface-2 hover:text-text">
              <X className="size-4" />
            </button>
          )}
        </div>
        <h3 className="mt-2.5 text-sm font-semibold">{insight.title}</h3>
        <p className="mt-1 text-sm text-muted">{insight.description}</p>
        {insight.impact && (
          <p className="mt-2.5 text-sm"><span className="text-muted">Expected impact: </span><span className="font-medium">{insight.impact}</span></p>
        )}
        <div className="mt-3 flex gap-2.5 rounded-lg bg-surface-2 p-3 text-sm">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
          <p><span className="font-medium">Suggested action: </span>{insight.recommendation}</p>
        </div>
        {!compact && insight.evidence.length > 0 && (
          <dl className="mt-3 grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
            {insight.evidence.map((e) => (
              <div key={e.label} className="flex justify-between gap-3 border-b border-dashed pb-1.5">
                <dt className="text-muted">{e.label}</dt>
                <dd className="text-right font-medium tabular">{e.value}</dd>
              </div>
            ))}
          </dl>
        )}
        <Confidence value={insight.confidence} className="mt-3" />
      </div>
    </Card>
  )
}

// ----------------------------------------------------------------------------- queue
export function QueueCard({ estimate, compact }: { estimate: QueueEstimate; compact?: boolean }) {
  const turn = estimate.status === 'in_consultation'
  return (
    <Card className="overflow-hidden">
      <div className={cn('px-5 py-5 text-center', turn ? 'bg-ok-soft' : 'bg-brand-soft')}>
        <p className="text-xs font-medium tracking-wide text-muted uppercase">Your queue number</p>
        <p className="mt-1 text-5xl font-semibold tracking-tight tabular" aria-live="polite">{estimate.token}</p>
        {turn
          ? <p className="mt-2 text-sm font-medium text-ok">It's your turn. Please go to room {estimate.room}.</p>
          : estimate.doctor && <p className="mt-2 text-sm text-muted">{estimate.doctor} · Room {estimate.room}</p>}
      </div>
      {!turn && (
        <dl className="grid grid-cols-3 divide-x text-center">
          {[['Currently serving', estimate.currently_serving ?? '—'], ['Patients ahead', estimate.patients_ahead],
            ['Estimated wait', `${estimate.estimated_wait_minutes} min`]].map(([label, value]) => (
            <div key={label as string} className="px-2 py-3.5">
              <dt className="text-[11px] text-subtle">{label}</dt>
              <dd className="mt-0.5 text-lg font-semibold tabular">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {!turn && !compact && (
        <div className="space-y-3 border-t p-4">
          <Confidence value={estimate.confidence} />
          <Factors factors={estimate.factors} title="How this estimate was made" />
          <p className="text-[11px] text-subtle">{estimate.label}. Urgent cases may be seen first.</p>
        </div>
      )}
    </Card>
  )
}

// ----------------------------------------------------------------------------- appointment
export function AppointmentCard({ appointment: a, perspective = 'patient', actions }: {
  appointment: Appointment; perspective?: 'patient' | 'staff'; actions?: ReactNode
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <div className="flex w-14 shrink-0 flex-col items-center rounded-lg bg-surface-2 py-2">
          <span className="text-[11px] font-medium text-subtle">{relativeDay(a.scheduled_at).split(',')[0].slice(0, 9)}</span>
          <span className="text-sm font-semibold tabular">{formatTime(a.scheduled_at)}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-semibold">{perspective === 'patient' ? a.doctor : a.patient}</p>
            <StatusBadge status={a.status} />
            {a.token && <Badge>{a.token}</Badge>}
          </div>
          <p className="mt-0.5 text-sm text-muted">
            {perspective === 'patient' ? `${a.department} · Room ${a.room}` : `${a.doctor} · ${a.department}`}
          </p>
          {a.reason && <p className="mt-1 truncate text-xs text-subtle">{a.reason}</p>}
        </div>
      </div>
      {actions && <div className="mt-3 flex flex-wrap justify-end gap-2 border-t pt-3">{actions}</div>}
    </Card>
  )
}

// ----------------------------------------------------------------------------- doctor
export function DoctorCard({ doctor: d, onBook, children }: { doctor: Doctor; onBook?: () => void; children?: ReactNode }) {
  return (
    <Card className="flex flex-col p-4">
      <div className="flex items-start gap-3">
        <Avatar name={d.name} className="size-11 text-sm" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{d.name}</p>
          <p className="truncate text-sm text-muted">{d.specialty}</p>
        </div>
        <Badge tone={d.on_shift ? 'ok' : 'neutral'}>{d.on_shift ? 'On shift' : d.is_available ? 'Off shift' : 'Unavailable'}</Badge>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-y-1.5 text-xs text-muted">
        <div className="flex items-center gap-1.5"><Stethoscope className="size-3.5" aria-hidden /><dd>{d.department}</dd></div>
        <div className="flex items-center gap-1.5"><MapPin className="size-3.5" aria-hidden /><dd>Room {d.room}</dd></div>
        <div className="flex items-center gap-1.5"><Clock className="size-3.5" aria-hidden />
          <dd className="tabular">{String(d.shift_start).padStart(2, '0')}:00–{String(d.shift_end).padStart(2, '0')}:00</dd></div>
        <div className="flex items-center gap-1.5"><Star className="size-3.5" aria-hidden />
          <dd>{d.rating ? `${d.rating.toFixed(1)} / 5 (${d.reviews})` : 'No ratings yet'}</dd></div>
      </dl>
      {children}
      {onBook && <Button variant="primary" size="sm" className="mt-3.5" icon={CalendarClock} onClick={onBook} disabled={!d.is_available}>Book appointment</Button>}
    </Card>
  )
}

// ----------------------------------------------------------------------------- patient
export function PatientCard({ patient: p, onOpen }: { patient: PatientRow; onOpen?: () => void }) {
  return (
    <Card className="p-4">
      <button onClick={onOpen} className="flex w-full items-center gap-3 text-left">
        <Avatar name={p.full_name} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{p.full_name}</p>
          <p className="text-xs text-muted">{p.mrn} · {p.age} y · {p.gender}</p>
        </div>
        <StatusBadge status={p.status} />
      </button>
      <p className="mt-2.5 flex items-center gap-1.5 text-xs text-muted"><User className="size-3.5" aria-hidden />{p.department ?? 'No department'}{p.doctor ? ` · ${p.doctor}` : ''}</p>
    </Card>
  )
}
