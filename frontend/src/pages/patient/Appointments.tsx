import { CalendarPlus, Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { BookingModal } from '@/components/BookingModal'
import { AppointmentCard, DoctorCard } from '@/components/cards'
import { Pagination } from '@/components/data'
import { Async, Button, Card, ConfirmDialog, EmptyState, Input, LoadingSkeleton, PageHeader, Select, Tabs } from '@/components/ui'
import { useDebounced } from '@/hooks/useUi'
import { addDays, formatDay, formatTime, hospitalNow, isoDate } from '@/lib/format'
import { patch, useAction, useDepartments, useDoctors, useGet } from '@/services/queries'
import type { Appointment, Paged } from '@/types'

type Tab = 'upcoming' | 'past' | 'doctors'

export default function PatientAppointments() {
  const [tab, setTab] = useState<Tab>('upcoming')
  const [page, setPage] = useState(1)
  const [booking, setBooking] = useState<{ doctorId?: number } | null>(null)
  const [rescheduling, setRescheduling] = useState<Appointment | null>(null)
  const [cancelling, setCancelling] = useState<Appointment | null>(null)
  const [q, setQ] = useState('')
  const [department, setDepartment] = useState('')
  const today = hospitalNow()
  const todayIso = isoDate(today)
  const params = tab === 'past'
    ? { date_to: isoDate(addDays(today, -1)), newest_first: true, page, size: 10 }
    : { date_from: todayIso, page, size: 10 }
  const list = useGet<Paged<Appointment>>('appointments', '/appointments', params, { enabled: tab !== 'doctors' })
  const departments = useDepartments()
  const doctors = useDoctors({ q: useDebounced(q), department_id: department })
  const cancel = useAction((a: Appointment) => patch(`/appointments/${a.id}`, { status: 'cancelled' }),
    { invalidate: ['appointments', 'queue-me', 'slots'], success: 'Appointment cancelled', onSuccess: () => setCancelling(null) })
  const change = (t: Tab) => { setTab(t); setPage(1) }

  return (
    <>
      <PageHeader title="Appointments" subtitle="Book, reschedule or cancel your visits."
        actions={<Button variant="primary" icon={CalendarPlus} onClick={() => setBooking({})}>Book appointment</Button>} />
      <Tabs label="Appointments" value={tab} onChange={change} tabs={[{ id: 'upcoming', label: 'Upcoming' }, { id: 'past', label: 'Past' }, { id: 'doctors', label: 'Find a doctor' }]} />

      {tab !== 'doctors' ? (
        <Async query={list} what="your appointments" skeleton={<LoadingSkeleton rows={4} />}
          empty={(d) => !d.items.length && <Card><EmptyState title={tab === 'upcoming' ? 'No upcoming appointments' : 'No past appointments'}
            body={tab === 'upcoming' ? 'Your schedule is clear.' : 'Completed and cancelled visits will appear here.'}
            action={tab === 'upcoming' && <Button variant="primary" icon={CalendarPlus} onClick={() => setBooking({})}>Book appointment</Button>} /></Card>}>
          {(d) => (
            <>
              <div className="grid gap-3 md:grid-cols-2">
                {d.items.map((a) => (
                  <AppointmentCard key={a.id} appointment={a} actions={a.status === 'scheduled' ? <>
                    {a.scheduled_at.startsWith(todayIso) && <Link to="/patient/queue" className="inline-flex h-8 items-center rounded-lg bg-brand px-2.5 text-[13px] font-medium text-on-brand hover:bg-brand-strong">Check in</Link>}
                    <Button size="sm" onClick={() => setRescheduling(a)}>Reschedule</Button>
                    <Button size="sm" variant="ghost" onClick={() => setCancelling(a)}>Cancel</Button>
                  </> : ['waiting', 'checked_in', 'in_consultation'].includes(a.status) ? <Link to="/patient/queue" className="text-[13px] font-medium text-brand hover:underline">View queue status</Link> : undefined} />
                ))}
              </div>
              <Card className="mt-3 empty:hidden"><Pagination page={d.page} size={d.size} total={d.total} onChange={setPage} /></Card>
            </>
          )}
        </Async>
      ) : (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_14rem]">
            <div className="relative"><Search className="pointer-events-none absolute top-3 left-3 size-4 text-subtle" aria-hidden />
              <Input aria-label="Search doctors" placeholder="Search by name or specialty" className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} /></div>
            <Select aria-label="Department" value={department} onChange={(e) => setDepartment(e.target.value)}>
              <option value="">All departments</option>{departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </div>
          <Async query={doctors} what="doctors" skeleton={<LoadingSkeleton variant="cards" rows={6} />}
            empty={(d) => !d.length && <Card><EmptyState title="No doctors match your search" body="Try a different name, specialty or department." /></Card>}>
            {(rows) => <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{rows.map((d) => <DoctorCard key={d.id} doctor={d} onBook={() => setBooking({ doctorId: d.id })} />)}</div>}
          </Async>
        </>
      )}

      <BookingModal open={!!booking} onClose={() => setBooking(null)} doctorId={booking?.doctorId} />
      <BookingModal open={!!rescheduling} onClose={() => setRescheduling(null)} reschedule={rescheduling} />
      <ConfirmDialog open={!!cancelling} onClose={() => setCancelling(null)} danger confirmLabel="Cancel appointment" loading={cancel.isPending}
        title="Cancel this appointment?" body={cancelling ? `${cancelling.doctor}, ${formatDay(cancelling.scheduled_at)} at ${formatTime(cancelling.scheduled_at)}. The slot will be released to other patients.` : ''}
        onConfirm={() => cancelling && cancel.mutate(cancelling)} />
    </>
  )
}
