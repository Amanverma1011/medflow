import { AlertTriangle, CalendarDays, CheckCircle2, Clock, Info, PhoneCall, Sparkles, Timer, Users } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { AiLabel } from '@/components/cards'
import { DashboardCard, MetricCard, StatusBadge } from '@/components/data'
import { Async, Badge, Button, EmptyState, LoadingSkeleton, PageHeader } from '@/components/ui'
import { cn, formatTime, greeting, hospitalNow } from '@/lib/format'
import { CompleteModal, QUEUE_KEYS } from '@/pages/admin/Queue'
import { LIVE, post, useAction, useGet } from '@/services/queries'
import type { Appointment, QueueEntry, QueueView } from '@/types'

interface Dashboard {
  doctor: { name: string; department: string; room: string; shift: string }
  queue_id: number
  metrics: { todays_patients: number; pending_consultations: number; avg_consult_minutes: number | null; waiting_patients: number; avg_wait_minutes: number; completed: number }
  current: Appointment | null
  waiting: Appointment[]
  schedule: Appointment[]
  alerts: { severity: 'warning' | 'info'; text: string }[]
  brief: { lines: string[]; label: string }
}

export default function DoctorDashboard() {
  const query = useGet<Dashboard>('doctor-dashboard', '/doctor/dashboard', undefined, { ...LIVE, refetchInterval: 20_000 })
  const queues = useGet<{ queues: QueueView[] }>('queues', '/queues', undefined, LIVE)
  const [completing, setCompleting] = useState<QueueEntry | null>(null)
  const callNext = useAction((queueId: number) => post<{ token: string }>(`/queues/${queueId}/call-next`), { invalidate: QUEUE_KEYS, success: (r) => `Now serving ${r.token}` })
  const queue = queues.data?.queues[0]
  const now = hospitalNow().getTime()

  return (
    <Async query={query} what="your dashboard" skeleton={<><LoadingSkeleton variant="cards" rows={4} /><div className="mt-5"><LoadingSkeleton rows={6} /></div></>}>
      {(d) => (
        <>
          <PageHeader title={`${greeting()}, ${d.doctor.name}`} subtitle={`${d.doctor.department} · Room ${d.doctor.room} · Shift ${d.doctor.shift}`}
            actions={<Link to="/doctor/patients" className="text-sm font-medium text-brand hover:underline">Open my patients</Link>} />

          <section aria-label="Workload summary" className="mb-5 flex gap-3 rounded-xl border bg-brand-soft/50 p-4">
            <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand text-on-brand"><Sparkles className="size-[18px]" /></span>
            <div className="min-w-0">
              <p className="mb-1 flex items-center gap-2 text-sm font-semibold">Today's operational workload <AiLabel title={d.brief.label}>AI summary</AiLabel></p>
              {d.brief.lines.map((line) => <p key={line} className="text-sm">{line}</p>)}
              <p className="mt-1.5 text-[11px] text-subtle">{d.brief.label}</p>
            </div>
          </section>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard label="Today's Patients" icon={Users} value={d.metrics.todays_patients} footer={<span>{d.metrics.completed} completed</span>} />
            <MetricCard label="Pending Consultations" icon={CalendarDays} value={d.metrics.pending_consultations} />
            <MetricCard label="Average Consultation Time" icon={Timer} value={d.metrics.avg_consult_minutes ?? '—'} unit={d.metrics.avg_consult_minutes ? 'min' : undefined} />
            <MetricCard label="Waiting Patients" icon={Clock} value={d.metrics.waiting_patients} tone={d.metrics.avg_wait_minutes >= 30 ? 'warn' : 'neutral'}
              footer={d.metrics.waiting_patients ? <span>avg {d.metrics.avg_wait_minutes} min wait</span> : undefined} />
          </div>

          {d.alerts.length > 0 && (
            <ul className="mt-4 space-y-2" aria-label="Alerts">
              {d.alerts.map((a) => (
                <li key={a.text} className={cn('flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm', a.severity === 'warning' ? 'bg-warn-soft text-warn' : 'bg-info-soft text-info')}>
                  {a.severity === 'warning' ? <AlertTriangle className="size-4 shrink-0" aria-hidden /> : <Info className="size-4 shrink-0" aria-hidden />}{a.text}
                </li>
              ))}
            </ul>
          )}

          <div className="mt-5 grid gap-4 xl:grid-cols-[1fr_1.15fr]">
            <div className="space-y-4">
              <DashboardCard title="Current Consultation">
                {queue?.current ? (
                  <div className="flex flex-wrap items-center gap-4">
                    <div className="rounded-lg bg-brand-soft px-4 py-3 text-center"><p className="text-[11px] text-muted">Token</p><p className="text-2xl font-semibold tabular">{queue.current.token}</p></div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold">{queue.current.patient}</p>
                      <p className="text-sm text-muted">{d.current?.reason || 'Consultation'}{d.current?.started_at ? ` · started ${formatTime(d.current.started_at)}` : ''}</p>
                      <Link to={`/doctor/patients/${queue.current.patient_id}`} className="mt-1 inline-block text-sm font-medium text-brand hover:underline">Open patient record</Link>
                    </div>
                    <Button variant="primary" icon={CheckCircle2} onClick={() => setCompleting(queue.current)}>Complete consultation</Button>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm text-muted">{queue?.waiting.length ? 'No consultation in progress. Call the next patient when you are ready.' : 'No consultation in progress and no one waiting.'}</p>
                    <Button variant="primary" icon={PhoneCall} disabled={!queue?.waiting.length} loading={callNext.isPending} onClick={() => callNext.mutate(d.queue_id)}>Next patient</Button>
                  </div>
                )}
              </DashboardCard>

              <DashboardCard title="Waiting Patients" subtitle={queue ? `${queue.waiting.length} in your queue` : undefined} flush
                action={queue?.current && queue.waiting.length > 0 ? <Badge>Complete the current consultation to call next</Badge> : undefined}>
                {!queue?.waiting.length ? <EmptyState icon={Users} title="No patients waiting" body="Patients appear here as soon as they check in." /> : (
                  <ol className="divide-y">
                    {queue.waiting.map((e, i) => (
                      <li key={e.id} className="flex items-center gap-3 px-4 py-2.5">
                        <span className="w-4 text-xs text-subtle tabular">{i + 1}</span>
                        <span className={cn('w-14 font-semibold tabular', e.priority > 0 && 'text-warn')}>{e.token}</span>
                        <Link to={`/doctor/patients/${e.patient_id}`} className="min-w-0 flex-1 truncate text-sm hover:text-brand hover:underline">{e.patient}</Link>
                        {e.priority > 0 && <Badge tone="warn">Priority</Badge>}
                        <span className={cn('text-xs tabular', e.waited_minutes >= 30 ? 'font-medium text-warn' : 'text-muted')}>{e.waited_minutes} min</span>
                      </li>
                    ))}
                  </ol>
                )}
              </DashboardCard>
            </div>

            <DashboardCard title="Today's Schedule" subtitle={`${d.schedule.length} appointments`} flush
              action={<Link to="/doctor/appointments" className="text-xs font-medium text-brand hover:underline">Full calendar</Link>}>
              {d.schedule.length === 0 ? <EmptyState icon={CalendarDays} title="No appointments today" body="Your schedule is clear." /> : (
                <ol className="max-h-[34rem] divide-y overflow-y-auto">
                  {d.schedule.map((a) => {
                    const past = new Date(a.scheduled_at).getTime() < now && ['completed', 'cancelled', 'no_show'].includes(a.status)
                    return (
                      <li key={a.id} className={cn('flex items-center gap-3 px-4 py-2.5', past && 'opacity-60')}>
                        <span className="w-[4.5rem] shrink-0 text-sm font-medium tabular">{formatTime(a.scheduled_at)}</span>
                        <div className="min-w-0 flex-1">
                          <Link to={`/doctor/patients/${a.patient_id}`} className="block truncate text-sm font-medium hover:text-brand hover:underline">{a.patient}</Link>
                          <p className="truncate text-xs text-muted">{a.reason || 'Consultation'}</p>
                        </div>
                        <StatusBadge status={a.status} />
                      </li>
                    )
                  })}
                </ol>
              )}
            </DashboardCard>
          </div>
          <CompleteModal entry={completing} onClose={() => setCompleting(null)} />
        </>
      )}
    </Async>
  )
}
