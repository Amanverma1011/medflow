import { ArrowRightLeft, ChevronsUp, PhoneCall, SkipForward, Users } from 'lucide-react'
import { useState } from 'react'
import { MetricCard } from '@/components/data'
import { Async, Badge, Button, Card, EmptyState, LoadingSkeleton, Modal, PageHeader, Select, Textarea, Input } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { cn } from '@/lib/format'
import { LIVE, post, useAction, useDepartments, useDoctors, useGet } from '@/services/queries'
import type { QueueEntry, QueueView } from '@/types'

export const QUEUE_KEYS = ['queues', 'doctor-dashboard', 'appointments', 'overview', 'queue-status']

/** Complete a consultation. Clinicians can attach a note and a prescription; others just close the entry. */
export function CompleteModal({ entry, onClose }: { entry: QueueEntry | null; onClose: () => void }) {
  const { can } = useAuth()
  const clinical = can('clinical:write')
  const [note, setNote] = useState('')
  const [rx, setRx] = useState({ medication: '', dosage: '', frequency: '' })
  const [error, setError] = useState('')
  const filled = Object.values(rx).filter(Boolean).length
  const done = useAction(() => post(`/queues/entries/${entry!.id}/complete`, { note, prescription: filled === 3 ? rx : null }), {
    invalidate: QUEUE_KEYS, success: 'Consultation completed', onSuccess: () => { setNote(''); setRx({ medication: '', dosage: '', frequency: '' }); onClose() },
  })
  const submit = () => {
    if (filled && filled < 3) return setError('Fill in medication, dosage and frequency, or leave all three empty.')
    setError(''); done.mutate()
  }
  return (
    <Modal open={!!entry} onClose={onClose} title="Complete consultation" description={entry ? `${entry.token}${entry.patient ? ` · ${entry.patient}` : ''}` : ''}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} loading={done.isPending}>Complete</Button></>}>
      {clinical ? (
        <div className="space-y-4">
          {error && <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2 text-sm text-crit">{error}</p>}
          <Textarea label="Consultation note (optional)" value={note} maxLength={4000} onChange={(e) => setNote(e.target.value)} hint="Saved to the visit record. Demo environment: do not enter real patient information." />
          <fieldset>
            <legend className="mb-1.5 text-[13px] font-medium text-muted">Prescription (optional)</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              <Input aria-label="Medication" placeholder="Medication" value={rx.medication} onChange={(e) => setRx({ ...rx, medication: e.target.value })} />
              <Input aria-label="Dosage" placeholder="Dosage" value={rx.dosage} onChange={(e) => setRx({ ...rx, dosage: e.target.value })} />
              <Input aria-label="Frequency" placeholder="Frequency" value={rx.frequency} onChange={(e) => setRx({ ...rx, frequency: e.target.value })} />
            </div>
          </fieldset>
        </div>
      ) : <p className="text-sm text-muted">This closes the queue entry and marks the appointment completed.</p>}
    </Modal>
  )
}

/** One doctor's live queue with the staff controls. */
export function QueuePanel({ queue: q }: { queue: QueueView }) {
  const doctors = useDoctors()
  const [completing, setCompleting] = useState<QueueEntry | null>(null)
  const [transferring, setTransferring] = useState<QueueEntry | null>(null)
  const [target, setTarget] = useState('')
  const act = (path: string, success: string, body?: unknown) => () => post(path, body).then(() => success)
  const run = useAction((fn: () => Promise<string>) => fn(), { invalidate: QUEUE_KEYS, success: (message) => message })
  const callNext = () => run.mutate(() => post<{ token: string }>(`/queues/${q.id}/call-next`).then((r) => `Now serving ${r.token}`))

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 border-b p-4">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">{q.doctor}</h3>
          <p className="text-xs text-muted">{q.department} · Room {q.room} · ~{q.avg_consult_minutes} min per patient</p>
        </div>
        <Badge>{q.completed} seen</Badge>
        <Button variant="primary" size="sm" icon={PhoneCall} onClick={callNext} loading={run.isPending} disabled={!!q.current || !q.waiting.length}
          title={q.current ? 'Complete the current consultation first' : undefined}>Call next</Button>
      </div>
      <div className="flex items-center justify-between gap-3 border-b bg-surface-2/60 px-4 py-3">
        <div>
          <p className="text-[11px] font-medium tracking-wide text-subtle uppercase">Currently serving</p>
          {q.current
            ? <p className="mt-0.5 text-sm"><span className="text-lg font-semibold tabular">{q.current.token}</span>{q.current.patient && <span className="text-muted"> · {q.current.patient}</span>}</p>
            : <p className="mt-0.5 text-sm text-muted">No consultation in progress</p>}
        </div>
        {q.current && <Button size="sm" onClick={() => setCompleting(q.current)}>Mark completed</Button>}
      </div>
      {q.waiting.length === 0 ? <EmptyState icon={Users} title="No one waiting" body="Checked-in patients appear here automatically." /> : (
        <ol className="divide-y">
          {q.waiting.map((e, i) => (
            <li key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
              <span className="w-5 text-xs text-subtle tabular">{i + 1}</span>
              <span className={cn('w-16 font-semibold tabular', e.priority > 0 && 'text-warn')}>{e.token}</span>
              <span className="min-w-0 flex-1 truncate text-sm">{e.patient ?? 'Patient'}{e.priority > 0 && <Badge tone="warn" className="ml-2">Priority</Badge>}</span>
              <span className="text-xs text-muted tabular" title="Time waited · estimated time until seen">{e.waited_minutes} min waited · ~{e.estimated_wait_minutes} min</span>
              <span className="flex gap-1">
                <Button size="sm" variant="ghost" icon={ChevronsUp} aria-label={`Prioritise ${e.token}`} title="Prioritise" disabled={e.priority > 0}
                  onClick={() => run.mutate(act(`/queues/entries/${e.id}/prioritize`, `${e.token} moved to the front`))} />
                <Button size="sm" variant="ghost" icon={SkipForward} aria-label={`Skip ${e.token}`} title="Skip (move to back)"
                  onClick={() => run.mutate(act(`/queues/entries/${e.id}/skip`, `${e.token} moved to the back`))} />
                <Button size="sm" variant="ghost" icon={ArrowRightLeft} aria-label={`Transfer ${e.token}`} title="Transfer to another doctor"
                  onClick={() => { setTarget(''); setTransferring(e) }} />
              </span>
            </li>
          ))}
        </ol>
      )}
      <CompleteModal entry={completing} onClose={() => setCompleting(null)} />
      <Modal open={!!transferring} onClose={() => setTransferring(null)} title={`Transfer ${transferring?.token ?? ''}`} description="Move this patient to another doctor's queue."
        footer={<><Button onClick={() => setTransferring(null)}>Cancel</Button>
          <Button variant="primary" disabled={!target} loading={run.isPending}
            onClick={() => run.mutate(act(`/queues/entries/${transferring!.id}/transfer`, 'Patient transferred', { doctor_id: Number(target) }), { onSuccess: () => setTransferring(null) })}>Transfer</Button></>}>
        <Select label="Transfer to" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Select a doctor</option>
          {doctors.data?.filter((d) => d.id !== q.doctor_id && d.is_available).map((d) => <option key={d.id} value={d.id}>{d.name} · {d.department}{d.on_shift ? '' : ' (off shift)'}</option>)}
        </Select>
      </Modal>
    </Card>
  )
}

export default function Queue() {
  const [department, setDepartment] = useState('')
  const departments = useDepartments()
  const query = useGet<{ queues: QueueView[]; waiting_total: number }>('queues', '/queues', { department_id: department }, { ...LIVE, refetchInterval: 15_000 })
  return (
    <>
      <PageHeader title="Queue" subtitle="Today's live queues. Updates arrive in real time."
        actions={<Select aria-label="Department" value={department} onChange={(e) => setDepartment(e.target.value)} className="w-52">
          <option value="">All departments</option>{departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </Select>} />
      <Async query={query} what="the queues" skeleton={<LoadingSkeleton rows={6} />}>
        {(data) => {
          const serving = data.queues.filter((q) => q.current)
          return (
            <>
              <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
                <MetricCard label="Waiting now" value={data.waiting_total} icon={Users} />
                <MetricCard label="In consultation" value={serving.length} />
                <MetricCard label="Active queues" value={data.queues.length} />
                <MetricCard label="Seen today" value={data.queues.reduce((n, q) => n + q.completed, 0)} />
              </div>
              {serving.length > 0 && (
                <Card className="mb-5 p-4">
                  <h2 className="mb-3 text-xs font-semibold tracking-[0.12em] uppercase">Current queue</h2>
                  <ul className="grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2 xl:grid-cols-3">
                    {serving.map((q) => <li key={q.id} className="flex items-center gap-2"><span className="w-14 font-semibold tabular">{q.current!.token}</span><span className="text-subtle">→</span><span className="truncate">{q.doctor}</span><span className="ml-auto text-xs text-subtle">+{q.waiting.length} waiting</span></li>)}
                  </ul>
                </Card>
              )}
              {data.queues.length === 0
                ? <Card><EmptyState icon={Users} title="No active queues" body="A queue opens when the first patient checks in for a doctor today." /></Card>
                : <div className="grid gap-4 xl:grid-cols-2">{data.queues.map((q) => <QueuePanel key={q.id} queue={q} />)}</div>}
            </>
          )
        }}
      </Async>
    </>
  )
}
