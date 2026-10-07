import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useDebounced } from '@/hooks/useUi'
import { addDays, cn, formatTime, hospitalNow, isoDate } from '@/lib/format'
import { patch, post, useAction, useDepartments, useDoctors, useGet } from '@/services/queries'
import type { Appointment, Paged, PatientRow } from '@/types'
import { Button, Input, LoadingSkeleton, Modal, Select } from './ui'

interface Props {
  open: boolean
  onClose: () => void
  /** Pre-select a doctor (e.g. from a doctor card). */
  doctorId?: number
  /** Pass an existing appointment to reschedule it instead of creating one. */
  reschedule?: Appointment | null
}

/** Book or reschedule. Staff choose the patient; patients always book for themselves. */
export function BookingModal({ open, onClose, doctorId, reschedule }: Props) {
  const { can } = useAuth()
  const staff = can('appointments:write')
  const today = isoDate(hospitalNow())
  const [department, setDepartment] = useState('')
  const [doctor, setDoctor] = useState('')
  const [day, setDay] = useState(today)
  const [slot, setSlot] = useState('')
  const [reason, setReason] = useState('')
  const [type, setType] = useState('new')
  const [patientQuery, setPatientQuery] = useState('')
  const [patient, setPatient] = useState<PatientRow | null>(null)
  const [error, setError] = useState('')

  const departments = useDepartments()
  const doctors = useDoctors()
  const patientTerm = useDebounced(patientQuery, 250)
  const patients = useGet<Paged<PatientRow>>('patients', '/patients', { q: patientTerm, size: 6 },
    { enabled: open && staff && !reschedule && patientTerm.length >= 2 && !patient })
  const slots = useGet<{ slots: { time: string; available: boolean }[] }>('slots', `/doctors/${doctor}/slots`, { day },
    { enabled: open && !!doctor && !!day, placeholderData: undefined })

  useEffect(() => {
    if (!open) return
    const preset = reschedule?.doctor_id ?? doctorId
    setDoctor(preset ? String(preset) : ''); setDepartment(''); setSlot(''); setReason(''); setType('new')
    setDay(today); setPatient(null); setPatientQuery(''); setError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, doctorId, reschedule])
  useEffect(() => setSlot(''), [doctor, day])

  const choices = useMemo(() => (doctors.data ?? []).filter((d) => d.is_available && (!department || String(d.department_id) === department)),
    [doctors.data, department])

  const save = useAction(() => (reschedule
    ? patch(`/appointments/${reschedule.id}`, { scheduled_at: slot })
    : post('/appointments', { doctor_id: Number(doctor), scheduled_at: slot, appointment_type: type, reason, patient_id: staff ? patient?.id : undefined })),
  { invalidate: ['appointments', 'calendar', 'slots', 'doctor-dashboard', 'queue-me'], success: reschedule ? 'Appointment rescheduled' : 'Appointment booked', onSuccess: onClose })

  const submit = () => {
    if (staff && !reschedule && !patient) return setError('Choose the patient this appointment is for.')
    if (!doctor) return setError('Choose a doctor.')
    if (!slot) return setError('Choose an available time.')
    setError('')
    save.mutate()
  }

  return (
    <Modal open={open} onClose={onClose} title={reschedule ? 'Reschedule appointment' : 'Book an appointment'}
      description={reschedule ? `${reschedule.doctor} · ${reschedule.department}` : 'Choose a doctor and an available time.'}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} loading={save.isPending}>{reschedule ? 'Confirm new time' : 'Confirm booking'}</Button></>}>
      <div className="space-y-4">
        {error && <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2 text-sm text-crit">{error}</p>}

        {staff && !reschedule && (patient ? (
          <div className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
            <span><span className="font-medium">{patient.full_name}</span><span className="text-muted"> · {patient.mrn}</span></span>
            <button onClick={() => setPatient(null)} className="text-xs font-medium text-brand hover:underline">Change</button>
          </div>
        ) : (
          <div>
            <Input label="Patient" placeholder="Search by name or patient ID" value={patientQuery} onChange={(e) => setPatientQuery(e.target.value)} />
            {patients.data && (
              <ul className="mt-1.5 overflow-hidden rounded-lg border text-sm">
                {patients.data.items.length === 0 && <li className="px-3 py-2 text-muted">No patients match.</li>}
                {patients.data.items.map((p) => (
                  <li key={p.id}><button onClick={() => setPatient(p)} className="flex w-full justify-between px-3 py-2 text-left hover:bg-surface-2">
                    <span>{p.full_name}</span><span className="text-muted">{p.mrn} · {p.age} y</span></button></li>
                ))}
              </ul>
            )}
          </div>
        ))}

        {!reschedule && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Select label="Department" value={department} onChange={(e) => { setDepartment(e.target.value); setDoctor('') }}>
              <option value="">All departments</option>
              {departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
            <Select label="Doctor" value={doctor} onChange={(e) => setDoctor(e.target.value)}>
              <option value="">Select a doctor</option>
              {choices.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.specialty}</option>)}
            </Select>
          </div>
        )}

        <Input label="Date" type="date" value={day} min={today} max={isoDate(addDays(hospitalNow(), 60))} onChange={(e) => setDay(e.target.value)} />

        <fieldset>
          <legend className="mb-1.5 text-[13px] font-medium text-muted">Available times</legend>
          {!doctor ? <p className="text-sm text-subtle">Select a doctor to see availability.</p>
            : slots.isLoading ? <LoadingSkeleton rows={2} />
              : slots.error ? <p className="text-sm text-crit">Couldn't load availability for that date.</p>
                : !slots.data?.slots.some((s) => s.available) ? <p className="text-sm text-muted">No free slots on this day. Try another date.</p>
                  : (
                    <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-5">
                      {slots.data.slots.map((s) => (
                        <button key={s.time} type="button" disabled={!s.available} aria-pressed={slot === s.time} onClick={() => setSlot(s.time)}
                          className={cn('rounded-lg border py-2 text-xs font-medium tabular transition-colors',
                            slot === s.time ? 'border-brand bg-brand text-on-brand' : s.available ? 'hover:border-brand hover:text-brand' : 'border-transparent bg-surface-2 text-subtle line-through')}>
                          {formatTime(s.time)}
                        </button>
                      ))}
                    </div>
                  )}
        </fieldset>

        {!reschedule && (
          <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
            <Select label="Visit type" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="new">New visit</option><option value="follow_up">Follow-up</option><option value="procedure">Procedure</option>
            </Select>
            <Input label="Reason (optional)" value={reason} maxLength={255} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Blood pressure review" />
          </div>
        )}
      </div>
    </Modal>
  )
}
