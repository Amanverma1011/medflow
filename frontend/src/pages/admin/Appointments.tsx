import { CalendarPlus, ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { BookingModal } from '@/components/BookingModal'
import { type Column, DataTable, Pagination, StatusBadge } from '@/components/data'
import { Async, Button, Card, ConfirmDialog, PageHeader, Select } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { addDays, cn, formatDay, formatTime, hospitalNow, humanize, isoDate } from '@/lib/format'
import { patch, post, useAction, useDepartments, useDoctors, useGet } from '@/services/queries'
import type { Appointment, AppointmentStatus, Paged } from '@/types'

type View = 'day' | 'week' | 'month'
const STATUSES: AppointmentStatus[] = ['scheduled', 'checked_in', 'waiting', 'in_consultation', 'completed', 'cancelled', 'no_show']
const INVALIDATE = ['appointments', 'calendar', 'queues', 'doctor-dashboard', 'overview']
const monday = (d: Date) => addDays(d, -((d.getDay() + 6) % 7))

interface Pending { kind: 'cancel' | 'no_show'; appointment: Appointment }

export default function Appointments() {
  const { user, can } = useAuth()
  const doctorOnly = user?.roles.length === 1 && user.roles[0] === 'doctor'
  const [view, setView] = useState<View>('day')
  const [date, setDate] = useState(() => hospitalNow())
  const [filters, setFilters] = useState({ department_id: '', doctor_id: '', status: '' })
  const [page, setPage] = useState(1)
  const [booking, setBooking] = useState(false)
  const [rescheduling, setRescheduling] = useState<Appointment | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const departments = useDepartments()
  const doctors = useDoctors()
  const today = isoDate(hospitalNow())

  const range = useMemo(() => {
    if (view === 'day') return { from: date, to: date }
    if (view === 'week') return { from: monday(date), to: addDays(monday(date), 6) }
    return { from: new Date(date.getFullYear(), date.getMonth(), 1), to: new Date(date.getFullYear(), date.getMonth() + 1, 0) }
  }, [view, date])

  const list = useGet<Paged<Appointment>>('appointments', '/appointments',
    { ...filters, date_from: isoDate(range.from), date_to: isoDate(range.to), page: view === 'day' ? page : 1, size: view === 'day' ? 25 : 100 },
    { enabled: view !== 'month' })
  const month = useGet<{ days: { day: string; total: number; completed: number; active: number; missed: number }[] }>('calendar', '/appointments/calendar',
    { month: isoDate(date).slice(0, 7), department_id: filters.department_id, doctor_id: filters.doctor_id }, { enabled: view === 'month' })

  const change = useAction((p: Pending) => patch(`/appointments/${p.appointment.id}`, { status: p.kind === 'cancel' ? 'cancelled' : 'no_show' }),
    { invalidate: INVALIDATE, success: (_, p) => (p.kind === 'cancel' ? 'Appointment cancelled' : 'Marked as no-show'), onSuccess: () => setPending(null) })
  const checkIn = useAction((a: Appointment) => post<{ token: string }>('/queues/check-in', { appointment_id: a.id }),
    { invalidate: INVALIDATE, success: (out) => `Checked in · token ${out.token}` })

  const step = (direction: number) => {
    setPage(1)
    setDate((d) => (view === 'month' ? new Date(d.getFullYear(), d.getMonth() + direction, 1) : addDays(d, direction * (view === 'week' ? 7 : 1))))
  }
  const setFilter = (k: keyof typeof filters) => (e: { target: { value: string } }) => { setFilters((f) => ({ ...f, [k]: e.target.value })); setPage(1) }
  const openDay = (day: Date) => { setDate(day); setView('day'); setPage(1) }
  const title = view === 'day' ? formatDay(date) : view === 'week' ? `${formatDay(range.from)} – ${formatDay(range.to)}`
    : date.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })

  const columns: Column<Appointment>[] = [
    { key: 'time', header: 'Time', cell: (a) => <span className="font-medium tabular">{formatTime(a.scheduled_at)}</span> },
    { key: 'patient', header: 'Patient', cell: (a) => <><span className="font-medium">{a.patient}</span><span className="block text-xs text-subtle">{a.mrn}</span></> },
    { key: 'doctor', header: 'Doctor', cell: (a) => <>{a.doctor}<span className="block text-xs text-subtle">{a.department}</span></>, hideBelow: 'md' },
    { key: 'type', header: 'Type', cell: (a) => humanize(a.appointment_type), hideBelow: 'lg' },
    { key: 'status', header: 'Status', cell: (a) => <span className="flex items-center gap-1.5"><StatusBadge status={a.status} />{a.token && <span className="text-xs text-subtle tabular">{a.token}</span>}</span> },
    { key: 'actions', header: '', className: 'text-right', cell: (a) => a.status === 'scheduled' && (
      <span className="flex justify-end gap-1.5">
        {can('queue:manage') && isoDate(new Date(a.scheduled_at)) === today && <Button size="sm" variant="primary" loading={checkIn.isPending && checkIn.variables?.id === a.id} onClick={() => checkIn.mutate(a)}>Check in</Button>}
        {can('appointments:write') && <>
          <Button size="sm" onClick={() => setRescheduling(a)}>Reschedule</Button>
          <Button size="sm" variant="ghost" onClick={() => setPending({ kind: 'no_show', appointment: a })}>No-show</Button>
          <Button size="sm" variant="ghost" onClick={() => setPending({ kind: 'cancel', appointment: a })}>Cancel</Button>
        </>}
      </span>) },
  ]

  return (
    <>
      <PageHeader title="Appointments" subtitle={doctorOnly ? 'Your schedule.' : 'Scheduling across all departments.'}
        actions={can('appointments:write') && <Button variant="primary" icon={CalendarPlus} onClick={() => setBooking(true)}>New appointment</Button>} />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="flex items-center gap-1">
            <Button size="sm" icon={ChevronLeft} onClick={() => step(-1)} aria-label="Previous" />
            <Button size="sm" onClick={() => { setDate(hospitalNow()); setPage(1) }}>Today</Button>
            <Button size="sm" icon={ChevronRight} onClick={() => step(1)} aria-label="Next" />
          </div>
          <h2 className="text-sm font-semibold tabular" aria-live="polite">{title}</h2>
          <div role="group" aria-label="Calendar view" className="ml-auto flex rounded-lg border p-0.5">
            {(['day', 'week', 'month'] as View[]).map((v) => (
              <button key={v} aria-pressed={view === v} onClick={() => { setView(v); setPage(1) }}
                className={cn('rounded-md px-3 py-1 text-xs font-medium capitalize', view === v ? 'bg-brand text-on-brand' : 'text-muted hover:text-text')}>{v}</button>
            ))}
          </div>
        </div>
        <div className="grid gap-3 border-b p-4 sm:grid-cols-3">
          <Select aria-label="Department" value={filters.department_id} onChange={setFilter('department_id')}>
            <option value="">All departments</option>{departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
          {!doctorOnly && (
            <Select aria-label="Doctor" value={filters.doctor_id} onChange={setFilter('doctor_id')}>
              <option value="">All doctors</option>
              {doctors.data?.filter((d) => !filters.department_id || String(d.department_id) === filters.department_id).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          )}
          {view !== 'month' && (
            <Select aria-label="Status" value={filters.status} onChange={setFilter('status')}>
              <option value="">Any status</option>{STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </Select>
          )}
        </div>

        {view === 'day' && (
          <Async query={list} what="appointments">
            {(data) => (
              <>
                <DataTable caption={`Appointments on ${title}`} columns={columns} rows={data.items} rowKey={(a) => a.id} dim={list.isFetching}
                  empty={{ title: 'No appointments for this day', body: filters.status || filters.doctor_id || filters.department_id ? 'Try clearing a filter.' : 'The schedule is clear.' }} />
                <Pagination page={data.page} size={data.size} total={data.total} onChange={setPage} />
              </>
            )}
          </Async>
        )}

        {view === 'week' && (
          <Async query={list} what="this week's appointments">
            {(data) => (
              <>
                <div className="grid divide-y md:grid-cols-7 md:divide-x md:divide-y-0">
                  {Array.from({ length: 7 }, (_, i) => addDays(range.from, i)).map((day) => {
                    const items = data.items.filter((a) => a.scheduled_at.startsWith(isoDate(day)))
                    return (
                      <div key={isoDate(day)} className="min-h-28 p-2">
                        <button onClick={() => openDay(day)} className={cn('mb-2 w-full rounded-md px-1.5 py-1 text-left text-xs font-medium hover:bg-surface-2', isoDate(day) === today && 'text-brand')}>
                          {formatDay(day)}
                        </button>
                        <ul className="space-y-1">
                          {items.slice(0, 6).map((a) => (
                            <li key={a.id} className="rounded-md bg-surface-2 px-1.5 py-1 text-[11px] leading-tight" title={`${a.patient} · ${a.doctor} · ${humanize(a.status)}`}>
                              <span className="font-medium tabular">{formatTime(a.scheduled_at)}</span> <span className="text-muted">{a.patient}</span>
                            </li>
                          ))}
                        </ul>
                        {items.length > 6 && <button onClick={() => openDay(day)} className="mt-1 text-[11px] font-medium text-brand hover:underline">+{items.length - 6} more</button>}
                        {!items.length && <p className="px-1.5 text-[11px] text-subtle">—</p>}
                      </div>
                    )
                  })}
                </div>
                {data.total > data.items.length && (
                  <p className="border-t px-4 py-2.5 text-xs text-muted">Showing the first {data.items.length} of {data.total} appointments this week. Filter by doctor, or open a day to see everything.</p>
                )}
              </>
            )}
          </Async>
        )}

        {view === 'month' && (
          <Async query={month} what="the month calendar">
            {(data) => {
              const counts = new Map(data.days.map((d) => [d.day, d]))
              const first = new Date(date.getFullYear(), date.getMonth(), 1)
              const cells = Array.from({ length: 42 }, (_, i) => addDays(monday(first), i))
              return (
                <div className="grid grid-cols-7 text-xs">
                  {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => <div key={d} className="border-b px-2 py-2 font-medium text-subtle">{d}</div>)}
                  {cells.map((day) => {
                    const c = counts.get(isoDate(day))
                    const outside = day.getMonth() !== date.getMonth()
                    return (
                      <button key={isoDate(day)} onClick={() => openDay(day)} aria-label={`${formatDay(day)}: ${c?.total ?? 0} appointments`}
                        className={cn('min-h-20 border-r border-b p-2 text-left hover:bg-surface-2 nth-[7n]:border-r-0', outside && 'text-subtle opacity-50')}>
                        <span className={cn('inline-flex size-6 items-center justify-center rounded-full tabular', isoDate(day) === today && 'bg-brand font-semibold text-on-brand')}>{day.getDate()}</span>
                        {c && (
                          <span className="mt-1 block">
                            <span className="block text-sm font-semibold tabular">{c.total}</span>
                            <span className="hidden text-[10px] text-muted sm:block">{c.completed} done · {c.active} open · {c.missed} missed</span>
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              )
            }}
          </Async>
        )}
      </Card>

      <BookingModal open={booking} onClose={() => setBooking(false)} />
      <BookingModal open={!!rescheduling} onClose={() => setRescheduling(null)} reschedule={rescheduling} />
      <ConfirmDialog open={!!pending} onClose={() => setPending(null)} danger loading={change.isPending}
        title={pending?.kind === 'cancel' ? 'Cancel this appointment?' : 'Mark as no-show?'}
        body={pending ? `${pending.appointment.patient} with ${pending.appointment.doctor}, ${formatDay(pending.appointment.scheduled_at)} at ${formatTime(pending.appointment.scheduled_at)}. The patient and doctor will be notified.` : ''}
        confirmLabel={pending?.kind === 'cancel' ? 'Cancel appointment' : 'Mark no-show'} onConfirm={() => pending && change.mutate(pending)} />
    </>
  )
}
