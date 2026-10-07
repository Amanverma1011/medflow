import { CalendarPlus, ClipboardList, Radio } from 'lucide-react'
import { Link } from 'react-router'
import { QueueCard } from '@/components/cards'
import { Async, Badge, Button, Card, EmptyState, LoadingSkeleton, PageHeader } from '@/components/ui'
import { formatTime } from '@/lib/format'
import { LIVE, post, useAction, useGet } from '@/services/queries'
import type { QueueEstimate } from '@/types'

interface MyQueue {
  entry: QueueEstimate | null
  can_check_in: { id: number; scheduled_at: string; doctor: string; department: string; room: string }[]
}

export default function PatientQueue() {
  // Realtime events refresh this instantly; the short poll is a fallback if the socket is blocked.
  const query = useGet<MyQueue>('queue-me', '/queues/me', undefined, { ...LIVE, refetchInterval: 15_000 })
  const checkIn = useAction((id: number) => post<QueueEstimate>('/queues/check-in', { appointment_id: id }),
    { invalidate: ['queue-me', 'appointments', 'notifications'], success: (e) => `Checked in. Your token is ${e.token}` })

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader title="Digital Queue" subtitle="Check in when you arrive and follow your place in line." actions={<Badge tone="ok" icon={Radio}>Live</Badge>} />
      <Async query={query} what="your queue status" skeleton={<LoadingSkeleton rows={5} />}>
        {(q) => (
          <div className="space-y-4">
            {q.entry && <QueueCard estimate={q.entry} />}
            {q.can_check_in.map((a) => (
              <Card key={a.id} className="p-5">
                <p className="text-xs font-medium tracking-wide text-brand uppercase">Ready to check in</p>
                <p className="mt-1.5 text-lg font-semibold">{a.doctor}</p>
                <p className="text-sm text-muted">{a.department} · Room {a.room} · Today at {formatTime(a.scheduled_at)}</p>
                <Button variant="primary" className="mt-4 w-full" icon={ClipboardList} loading={checkIn.isPending && checkIn.variables === a.id} onClick={() => checkIn.mutate(a.id)}>
                  I've arrived. Check me in
                </Button>
                <p className="mt-2 text-center text-xs text-subtle">You'll get a queue number and a live wait estimate.</p>
              </Card>
            ))}
            {!q.entry && !q.can_check_in.length && (
              <Card><EmptyState icon={ClipboardList} title="You're not in a queue" body="Check-in opens on the day of your appointment. Book a visit to get started."
                action={<Link to="/patient/appointments" className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand px-4 text-sm font-medium text-on-brand hover:bg-brand-strong"><CalendarPlus className="size-4" aria-hidden />Go to appointments</Link>} /></Card>
            )}
          </div>
        )}
      </Async>
    </div>
  )
}
