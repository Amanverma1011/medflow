import { ArrowLeft, CalendarDays, FileText, Lock, MessageSquare, Pill, Stethoscope } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { Avatar } from '@/components/cards'
import { StatusBadge } from '@/components/data'
import { Async, Badge, Card, EmptyState, LoadingSkeleton, Tabs } from '@/components/ui'
import { formatDate, formatDateTime, humanize } from '@/lib/format'
import { useGet } from '@/services/queries'

export interface PatientRecord {
  patient: Record<string, any>
  appointments: Record<string, any>[]
  visits: Record<string, any>[]
  prescriptions: Record<string, any>[]
  documents: Record<string, any>[]
  feedback: Record<string, any>[]
  timeline: { at: string; type: string; title: string; detail: string }[]
  clinical_access: boolean
}

const TABS = [
  { id: 'overview', label: 'Basic Information' }, { id: 'appointments', label: 'Appointment History' },
  { id: 'visits', label: 'Visit History' }, { id: 'documents', label: 'Documents' },
  { id: 'prescriptions', label: 'Prescriptions' }, { id: 'feedback', label: 'Feedback' }, { id: 'timeline', label: 'Timeline' },
] as const
type TabId = (typeof TABS)[number]['id']
const TIMELINE_ICON: Record<string, typeof CalendarDays> = { appointment: CalendarDays, visit: Stethoscope, prescription: Pill, document: FileText, feedback: MessageSquare }

function Row({ title, meta, aside, children }: { title: React.ReactNode; meta?: React.ReactNode; aside?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <li className="flex items-start justify-between gap-4 px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">{title}</p>
        {meta && <p className="text-xs text-muted">{meta}</p>}
        {children}
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </li>
  )
}

function Restricted() {
  return <EmptyState icon={Lock} title="Clinical content is restricted" body="Your role can see scheduling and demographics, but not prescriptions, documents or consultation notes." />
}

/** The tabbed record body, shared with the patient's own "My records" page. */
export function RecordSections({ record: r, tab }: { record: PatientRecord; tab: TabId }) {
  const list = (items: unknown[], empty: string, render: () => React.ReactNode) =>
    items.length ? <ul className="divide-y">{render()}</ul> : <EmptyState title={empty} />
  switch (tab) {
    case 'appointments':
      return list(r.appointments, 'No appointments yet', () => r.appointments.map((a) => (
        <Row key={a.id} title={`${a.doctor} · ${a.department}`} meta={`${formatDateTime(a.scheduled_at)} · ${humanize(a.appointment_type)}${a.reason ? ` · ${a.reason}` : ''}`} aside={<StatusBadge status={a.status} />} />)))
    case 'visits':
      return list(r.visits, 'No visits recorded', () => r.visits.map((v) => (
        <Row key={v.id} title={v.summary || 'Consultation'} meta={`${formatDateTime(v.started_at)} · ${v.doctor} · ${v.department}`}>
          {v.notes && <p className="mt-1.5 rounded-lg bg-surface-2 p-2.5 text-xs whitespace-pre-line text-muted">{v.notes}</p>}
        </Row>)))
    case 'documents':
      if (!r.clinical_access) return <Restricted />
      return list(r.documents, 'No documents', () => r.documents.map((d) => (
        <Row key={d.id} title={d.title} meta={`${humanize(d.doc_type)} · ${formatDate(d.issued_at)}`}><p className="mt-1 text-xs text-muted">{d.summary}</p></Row>)))
    case 'prescriptions':
      if (!r.clinical_access) return <Restricted />
      return list(r.prescriptions, 'No prescriptions', () => r.prescriptions.map((p) => (
        <Row key={p.id} title={`${p.medication} · ${p.dosage}`} meta={`${p.frequency} · ${p.duration_days} days · ${p.doctor}`} aside={<span className="text-xs text-subtle tabular">{formatDate(p.issued_at)}</span>}>
          {p.instructions && <p className="mt-1 text-xs text-muted">{p.instructions}</p>}
        </Row>)))
    case 'feedback':
      return list(r.feedback, 'No feedback submitted', () => r.feedback.map((f) => (
        <Row key={f.id} title={`${f.overall} / 5 overall`} meta={`${formatDate(f.created_at)} · ${humanize(f.category)}`} aside={<StatusBadge status={f.sentiment} />}>
          {f.comment && <p className="mt-1 text-sm text-muted">“{f.comment}”</p>}
        </Row>)))
    case 'timeline':
      return r.timeline.length ? (
        <ol className="space-y-0 p-4">
          {r.timeline.map((e, i) => {
            const Icon = TIMELINE_ICON[e.type] ?? CalendarDays
            return (
              <li key={i} className="relative flex gap-3 pb-5 last:pb-0">
                {i < r.timeline.length - 1 && <span className="absolute top-7 left-[13px] h-full w-px bg-border" aria-hidden />}
                <span className="z-10 flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-2 text-subtle"><Icon className="size-3.5" aria-hidden /></span>
                <div><p className="text-sm font-medium">{e.title}</p><p className="text-xs text-muted">{e.detail} · {formatDateTime(e.at)}</p></div>
              </li>
            )
          })}
        </ol>
      ) : <EmptyState title="No activity yet" />
    default: {
      const p = r.patient
      const fields: [string, React.ReactNode][] = [
        ['Patient ID', p.mrn], ['Date of birth', `${formatDate(p.date_of_birth)} (${p.age} years)`], ['Gender', p.gender],
        ['Phone', p.phone || '—'], ['Email', p.email || '—'], ['Address', p.address || '—'], ['Department', p.department ?? '—'],
        ['Blood group', p.blood_group || '—'], ['Allergies', p.allergies || '—'], ['Long-term conditions', p.chronic_conditions || '—'],
        ['Emergency contact', p.emergency_contact || '—'], ['Insurance', p.insurance_provider || '—'], ['Registered', formatDate(p.created_at)],
      ]
      return (
        <dl className="grid gap-x-8 gap-y-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
          {fields.map(([label, value]) => <div key={label}><dt className="text-xs text-subtle">{label}</dt><dd className="mt-0.5 text-sm">{value}</dd></div>)}
        </dl>
      )
    }
  }
}

export default function PatientProfile() {
  const { id } = useParams()
  const [tab, setTab] = useState<TabId>('overview')
  const query = useGet<PatientRecord>('patient', `/patients/${id}`, undefined, { placeholderData: undefined })
  return (
    <>
      <Link to=".." relative="path" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-text"><ArrowLeft className="size-4" aria-hidden />Back to patients</Link>
      <Async query={query} what="this patient record" skeleton={<LoadingSkeleton rows={6} />}>
        {(r) => (
          <>
            <div className="mb-5 flex flex-wrap items-center gap-4">
              <Avatar name={r.patient.full_name} className="size-14 text-lg" />
              <div className="min-w-0">
                <h1 className="text-xl font-semibold">{r.patient.full_name}</h1>
                <p className="text-sm text-muted">{r.patient.mrn} · {r.patient.age} years · {r.patient.gender}</p>
              </div>
              <StatusBadge status={r.patient.status} />
              {!r.clinical_access && <Badge icon={Lock}>Demographics only</Badge>}
              <Badge className="ml-auto">Synthetic record</Badge>
            </div>
            <Tabs label="Patient record" tabs={[...TABS]} value={tab} onChange={setTab} />
            <Card><RecordSections record={r} tab={tab} /></Card>
          </>
        )}
      </Async>
    </>
  )
}
