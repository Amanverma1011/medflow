import { Clock, MapPin, Search, Smile, Stethoscope, Users } from 'lucide-react'
import { useState } from 'react'
import { BookingModal } from '@/components/BookingModal'
import { DoctorCard } from '@/components/cards'
import { type Column, DataTable } from '@/components/data'
import { Async, Badge, Card, EmptyState, Input, LoadingSkeleton, PageHeader, Select, Tabs } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { useDebounced } from '@/hooks/useUi'
import { humanize, num } from '@/lib/format'
import { useDepartments, useDoctors, useGet } from '@/services/queries'
import type { Department } from '@/types'

interface StaffRow { id: number; name: string; email: string; staff_type: string; shift: string; department: string | null; is_active: boolean }
const STAFF_COLUMNS: Column<StaffRow>[] = [
  { key: 'name', header: 'Name', cell: (s) => <span className="font-medium">{s.name}</span> },
  { key: 'role', header: 'Role', cell: (s) => humanize(s.staff_type) },
  { key: 'dept', header: 'Department', cell: (s) => s.department ?? '—', hideBelow: 'sm' },
  { key: 'shift', header: 'Shift', cell: (s) => humanize(s.shift), hideBelow: 'md' },
  { key: 'email', header: 'Email', cell: (s) => <span className="text-muted">{s.email}</span>, hideBelow: 'lg' },
]

function Doctors() {
  const { can } = useAuth()
  const [q, setQ] = useState('')
  const [department, setDepartment] = useState('')
  const [tab, setTab] = useState<'doctors' | 'staff'>('doctors')
  const [booking, setBooking] = useState<number | null>(null)
  const departments = useDepartments()
  const doctors = useDoctors({ q: useDebounced(q), department_id: department })
  const staff = useGet<StaffRow[]>('staff', '/staff', undefined, { enabled: tab === 'staff' })
  return (
    <>
      <PageHeader title="Doctors & Staff" subtitle="Availability, specialties and today's load." />
      {can('staff:read') && <Tabs label="Directory" value={tab} onChange={setTab} tabs={[{ id: 'doctors', label: 'Doctors' }, { id: 'staff', label: 'Nurses & reception' }]} />}
      {tab === 'staff' ? (
        <Card><Async query={staff} what="the staff directory">{(rows) => <DataTable caption="Staff" columns={STAFF_COLUMNS} rows={rows} rowKey={(s) => s.id} />}</Async></Card>
      ) : (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_14rem]">
            <div className="relative">
              <Search className="pointer-events-none absolute top-3 left-3 size-4 text-subtle" aria-hidden />
              <Input aria-label="Search doctors" placeholder="Search by name, specialty or department" className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <Select aria-label="Department" value={department} onChange={(e) => setDepartment(e.target.value)}>
              <option value="">All departments</option>{departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </div>
          <Async query={doctors} what="the doctor directory" skeleton={<LoadingSkeleton variant="cards" rows={6} />}
            empty={(d) => !d.length && <Card><EmptyState icon={Stethoscope} title="No doctors match" body="Try a different name or department." /></Card>}>
            {(rows) => (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {rows.map((d) => (
                  <DoctorCard key={d.id} doctor={d} onBook={can('appointments:write') ? () => setBooking(d.id) : undefined}>
                    <p className="mt-3 border-t pt-3 text-xs text-muted"><span className="font-medium text-text tabular">{d.patients_today}</span> patients today · ~{d.avg_consult_minutes} min per consultation</p>
                  </DoctorCard>
                ))}
              </div>
            )}
          </Async>
        </>
      )}
      <BookingModal open={booking !== null} onClose={() => setBooking(null)} doctorId={booking ?? undefined} />
    </>
  )
}

function Departments() {
  const query = useDepartments()
  return (
    <>
      <PageHeader title="Departments" subtitle="Location, staffing and today's activity for each department." />
      <Async query={query} what="departments" skeleton={<LoadingSkeleton variant="cards" rows={8} />}>
        {(rows: Department[]) => (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {rows.map((d) => (
              <Card key={d.id} className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-semibold">{d.name}</h2>
                  <Badge tone={d.waiting >= 6 ? 'warn' : 'neutral'}>{d.waiting} waiting</Badge>
                </div>
                <p className="mt-1 text-sm text-muted">{d.description}</p>
                <p className="mt-3 flex items-start gap-1.5 text-xs text-muted"><MapPin className="mt-px size-3.5 shrink-0" aria-hidden />{d.location}</p>
                <p className="mt-1 flex items-center gap-1.5 text-xs text-muted"><Clock className="size-3.5" aria-hidden />
                  {d.close_hour - d.open_hour >= 24 ? 'Open 24 hours' : `${String(d.open_hour).padStart(2, '0')}:00–${String(d.close_hour).padStart(2, '0')}:00`}</p>
                <dl className="mt-4 grid grid-cols-2 gap-3 border-t pt-3 text-xs">
                  {[[Stethoscope, 'Doctors', d.doctors], [Users, 'Patients today', d.patients_today], [Clock, 'Avg wait (7d)', d.avg_wait_7d !== null ? `${d.avg_wait_7d} min` : '—'],
                    [Smile, 'Satisfaction', d.satisfaction !== null ? `${num(d.satisfaction, 1)} / 5` : '—']].map(([Icon, label, value]: any) => (
                    <div key={label}><dt className="flex items-center gap-1 text-subtle"><Icon className="size-3" aria-hidden />{label}</dt><dd className="mt-0.5 text-sm font-semibold tabular">{value}</dd></div>
                  ))}
                </dl>
              </Card>
            ))}
          </div>
        )}
      </Async>
    </>
  )
}

export default function Directory({ view }: { view: 'doctors' | 'departments' }) {
  return view === 'doctors' ? <Doctors /> : <Departments />
}
