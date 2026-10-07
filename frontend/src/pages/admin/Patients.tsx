import { Search, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Avatar } from '@/components/cards'
import { type Column, DataTable, DepartmentBadge, Pagination, StatusBadge } from '@/components/data'
import { Async, Button, Card, Input, Modal, PageHeader, Select } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { useDebounced } from '@/hooks/useUi'
import { formatDate, formatDateTime, hospitalNow, isoDate } from '@/lib/format'
import { post, useAction, useDepartments, useDoctors, useGet } from '@/services/queries'
import type { Paged, PatientRow } from '@/types'

const COLUMNS: Column<PatientRow>[] = [
  { key: 'id', header: 'Patient ID', cell: (p) => <span className="text-muted tabular">{p.mrn}</span>, hideBelow: 'sm' },
  { key: 'name', header: 'Name', cell: (p) => <span className="flex items-center gap-2.5"><Avatar name={p.full_name} className="size-7 text-[10px]" /><span className="font-medium">{p.full_name}</span></span> },
  { key: 'age', header: 'Age', cell: (p) => <span className="tabular">{p.age}</span>, hideBelow: 'md' },
  { key: 'gender', header: 'Gender', cell: (p) => p.gender, hideBelow: 'lg' },
  { key: 'department', header: 'Department', cell: (p) => <DepartmentBadge name={p.department} />, hideBelow: 'md' },
  { key: 'appointment', header: 'Appointment', cell: (p) => (p.appointment_at ? <span className="tabular">{formatDateTime(p.appointment_at)}</span> : <span className="text-subtle">None upcoming</span>), hideBelow: 'lg' },
  { key: 'status', header: 'Status', cell: (p) => <StatusBadge status={p.status} /> },
  { key: 'doctor', header: 'Doctor', cell: (p) => p.doctor ?? <span className="text-subtle">—</span>, hideBelow: 'lg' },
  { key: 'last', header: 'Last Visit', cell: (p) => <span className="text-muted tabular">{formatDate(p.last_visit)}</span>, hideBelow: 'md' },
]

function RegisterModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const departments = useDepartments()
  const [form, setForm] = useState({ full_name: '', date_of_birth: '', gender: 'Female', phone: '', primary_department_id: '' })
  const [error, setError] = useState('')
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const save = useAction(() => post<{ id: number }>('/patients', { ...form, primary_department_id: form.primary_department_id ? Number(form.primary_department_id) : null }), {
    invalidate: ['patients'], success: 'Patient registered', onSuccess: (p) => { onClose(); navigate(`/admin/patients/${p.id}`) },
  })
  const submit = () => {
    if (form.full_name.trim().length < 2 || !form.date_of_birth) return setError('Enter the patient\'s full name and date of birth.')
    setError(''); save.mutate()
  }
  return (
    <Modal open={open} onClose={onClose} title="Register a patient" description="Creates a new patient record."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} loading={save.isPending}>Register</Button></>}>
      <div className="space-y-4">
        {error && <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2 text-sm text-crit">{error}</p>}
        <Input label="Full name" value={form.full_name} onChange={set('full_name')} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="Date of birth" type="date" max={isoDate(hospitalNow())} value={form.date_of_birth} onChange={set('date_of_birth')} />
          <Select label="Gender" value={form.gender} onChange={set('gender')}><option>Female</option><option>Male</option><option>Other</option></Select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Phone" value={form.phone} onChange={set('phone')} />
          <Select label="Department" value={form.primary_department_id} onChange={set('primary_department_id')}>
            <option value="">Not assigned</option>
            {departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
        </div>
      </div>
    </Modal>
  )
}

export default function Patients({ base }: { base: '/admin' | '/doctor' }) {
  const navigate = useNavigate()
  const { can } = useAuth()
  const [filters, setFilters] = useState({ q: '', department_id: '', doctor_id: '', status: '', appointment_date: '' })
  const [page, setPage] = useState(1)
  const [registering, setRegistering] = useState(false)
  const q = useDebounced(filters.q)
  const departments = useDepartments()
  const doctors = useDoctors()
  const query = useGet<Paged<PatientRow>>('patients', '/patients', { ...filters, q, page, size: 20 })
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => { setFilters((f) => ({ ...f, [k]: e.target.value })); setPage(1) }
  const mine = base === '/doctor'

  return (
    <>
      <PageHeader title={mine ? 'My Patients' : 'Patients'}
        subtitle={mine ? 'Patients who have had or are booked for an appointment with you.' : 'Directory of all registered patients. Synthetic records only.'}
        actions={can('patients:write') && <Button variant="primary" icon={UserPlus} onClick={() => setRegistering(true)}>Register patient</Button>} />
      <Card>
        <div className="grid gap-3 border-b p-4 sm:grid-cols-2 lg:grid-cols-5">
          <div className="relative lg:col-span-2">
            <Search className="pointer-events-none absolute top-3 left-3 size-4 text-subtle" aria-hidden />
            <Input aria-label="Search patients" placeholder="Search by name or patient ID" className="pl-9" value={filters.q} onChange={set('q')} maxLength={80} />
          </div>
          <Select aria-label="Department" value={filters.department_id} onChange={set('department_id')}>
            <option value="">All departments</option>{departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
          {!mine && (
            <Select aria-label="Doctor" value={filters.doctor_id} onChange={set('doctor_id')}>
              <option value="">All doctors</option>{doctors.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          )}
          <Select aria-label="Patient status" value={filters.status} onChange={set('status')}>
            <option value="">Any status</option><option value="active">Active</option><option value="admitted">Admitted</option><option value="discharged">Discharged</option>
          </Select>
          <Input aria-label="Appointment date" type="date" value={filters.appointment_date} onChange={set('appointment_date')} className={mine ? '' : 'lg:col-start-5'} />
        </div>
        <Async query={query} what="the patient directory">
          {(data) => (
            <>
              <DataTable caption="Patients" columns={COLUMNS} rows={data.items} rowKey={(p) => p.id} dim={query.isFetching}
                onRowClick={(p) => navigate(`${base}/patients/${p.id}`)}
                empty={{ title: 'No patients match these filters', body: 'Try clearing a filter or searching by patient ID.' }} />
              <Pagination page={data.page} size={data.size} total={data.total} onChange={setPage} />
            </>
          )}
        </Async>
      </Card>
      <RegisterModal open={registering} onClose={() => setRegistering(false)} />
    </>
  )
}
