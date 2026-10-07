import { ArrowRight, CalendarPlus, ClipboardList, FileText, MessageSquareHeart, Smile, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { BookingModal } from '@/components/BookingModal'
import { QueueCard } from '@/components/cards'
import { Async, Button, Card, DemoTag, EmptyState, LoadingSkeleton, SectionTitle } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { addDays, formatDate, formatTime, greeting, hospitalNow, isoDate, relativeDay } from '@/lib/format'
import type { PatientRecord } from '@/pages/admin/PatientProfile'
import { LIVE, useGet } from '@/services/queries'
import type { Appointment, Paged, QueueEstimate } from '@/types'

const SUGGESTED = ['What is hypertension?', 'How should I prepare for an MRI?', 'What are the visiting hours?']

export default function PatientHome() {
  const { user } = useAuth()
  const [booking, setBooking] = useState(false)
  const today = hospitalNow()
  const upcoming = useGet<Paged<Appointment>>('appointments', '/appointments', { date_from: isoDate(today), date_to: isoDate(addDays(today, 60)), size: 20 })
  const queue = useGet<{ entry: QueueEstimate | null; can_check_in: { id: number }[] }>('queue-me', '/queues/me', undefined, { ...LIVE, refetchInterval: 20_000 })
  const record = useGet<PatientRecord>('my-record', '/patients/me')
  const next = upcoming.data?.items.find((a) => ['scheduled', 'checked_in', 'waiting', 'in_consultation'].includes(a.status))

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">{greeting()}, {user?.full_name.split(' ')[0]}</h1><p className="mt-1 text-sm text-muted">Here's what's coming up.</p></div>
        <DemoTag />
      </div>

      <section aria-labelledby="next-appointment">
        <SectionTitle><span id="next-appointment">Your next appointment</span></SectionTitle>
        <Async query={upcoming} what="your appointments" skeleton={<LoadingSkeleton rows={2} />}>
          {() => next ? (
            <Card className="p-5">
              <p className="text-lg font-semibold">{next.doctor}</p>
              <p className="text-sm text-muted">{next.department} · Room {next.room}</p>
              <p className="mt-2 text-sm font-medium tabular">{relativeDay(next.scheduled_at)} • {formatTime(next.scheduled_at)}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link to="/patient/appointments" className="inline-flex h-10 items-center rounded-lg bg-brand px-4 text-sm font-medium text-on-brand hover:bg-brand-strong">View Appointment</Link>
                {queue.data?.can_check_in.some((c) => c.id === next.id) && (
                  <Link to="/patient/queue" className="inline-flex h-10 items-center gap-2 rounded-lg border bg-surface px-4 text-sm font-medium hover:bg-surface-2"><ClipboardList className="size-4" aria-hidden />Check in</Link>
                )}
              </div>
            </Card>
          ) : (
            <Card><EmptyState title="No upcoming appointments" body="Book a visit with any of our departments."
              action={<Button variant="primary" icon={CalendarPlus} onClick={() => setBooking(true)}>Book appointment</Button>} /></Card>
          )}
        </Async>
      </section>

      {queue.data?.entry && (
        <section aria-labelledby="queue-status">
          <SectionTitle aside={<Link to="/patient/queue" className="text-xs font-medium text-brand hover:underline">Details</Link>}><span id="queue-status">Queue Status</span></SectionTitle>
          <QueueCard estimate={queue.data.entry} compact />
        </section>
      )}

      <section aria-labelledby="assistant">
        <Card className="p-5">
          <div className="flex items-center gap-3">
            <span aria-hidden className="flex size-10 items-center justify-center rounded-full bg-brand-soft text-brand"><Sparkles className="size-5" /></span>
            <div><h2 id="assistant" className="font-semibold">Medical Assistant</h2><p className="text-sm text-muted">How can I help you today?</p></div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {SUGGESTED.map((q) => <Link key={q} to="/patient/chat" state={{ ask: q }} className="rounded-full border px-3.5 py-1.5 text-sm text-muted hover:border-brand hover:text-brand">{q}</Link>)}
            <Link to="/patient/chat" className="inline-flex items-center gap-1 rounded-full bg-brand px-3.5 py-1.5 text-sm font-medium text-on-brand hover:bg-brand-strong"><MessageSquareHeart className="size-4" aria-hidden />Open assistant</Link>
          </div>
          <p className="mt-3 text-[11px] text-subtle">General medical information only. Not a substitute for professional medical advice, diagnosis, or treatment.</p>
        </Card>
      </section>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="p-4 md:col-span-2">
          <SectionTitle aside={<Link to="/patient/documents" className="text-xs font-medium text-brand hover:underline">All records</Link>}>Recent Visits</SectionTitle>
          <Async query={record} what="your visits" skeleton={<LoadingSkeleton rows={3} />} empty={(r) => !r.visits.length && <p className="py-4 text-sm text-muted">No visits yet.</p>}>
            {(r) => (
              <ul className="divide-y">
                {r.visits.slice(0, 3).map((v) => (
                  <li key={v.id} className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
                    <div className="min-w-0"><p className="truncate text-sm font-medium">{v.summary || 'Consultation'}</p><p className="text-xs text-muted">{v.doctor} · {v.department}</p></div>
                    <span className="shrink-0 text-xs text-subtle tabular">{formatDate(v.started_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </Card>
        <div className="grid gap-4">
          {[{ to: '/patient/documents', icon: FileText, title: 'Documents', body: record.data ? `${record.data.documents.length} documents · ${record.data.prescriptions.length} prescriptions` : 'Prescriptions and reports' },
            { to: '/patient/feedback', icon: Smile, title: 'Feedback', body: 'Tell us about your visit' }].map((l) => (
            <Link key={l.to} to={l.to} className="group flex items-center gap-3 rounded-xl border bg-surface p-4 shadow-card hover:border-brand">
              <l.icon className="size-5 text-brand" aria-hidden />
              <span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{l.title}</span><span className="block truncate text-xs text-muted">{l.body}</span></span>
              <ArrowRight className="size-4 text-subtle group-hover:text-brand" aria-hidden />
            </Link>
          ))}
        </div>
      </div>
      <BookingModal open={booking} onClose={() => setBooking(false)} />
    </div>
  )
}
