/** Patient self-service: documents & prescriptions, feedback, and profile. */
import { LogOut, Star } from 'lucide-react'
import { type FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { AiLabel, Avatar } from '@/components/cards'
import { StatusBadge } from '@/components/data'
import { Async, Button, Card, Input, LoadingSkeleton, PageHeader, Select, Tabs, Textarea } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { cn, formatDate, humanize } from '@/lib/format'
import { type PatientRecord, RecordSections } from '@/pages/admin/PatientProfile'
import { patch, post, useAction, useDepartments, useGet } from '@/services/queries'

// ----------------------------------------------------------------------------- documents
const RECORD_TABS = [{ id: 'documents', label: 'Documents' }, { id: 'prescriptions', label: 'Prescriptions' }, { id: 'visits', label: 'Visit history' }, { id: 'timeline', label: 'Timeline' }] as const

function Documents() {
  const [tab, setTab] = useState<(typeof RECORD_TABS)[number]['id']>('documents')
  const query = useGet<PatientRecord>('my-record', '/patients/me')
  return (
    <>
      <PageHeader title="My Records" subtitle="Your documents, prescriptions and visit history. Only you and your care team can see these." />
      <Tabs label="My records" tabs={[...RECORD_TABS]} value={tab} onChange={setTab} />
      <Card><Async query={query} what="your records" skeleton={<div className="p-4"><LoadingSkeleton rows={4} /></div>}>{(r) => <RecordSections record={r} tab={tab} />}</Async></Card>
    </>
  )
}

// ----------------------------------------------------------------------------- feedback
const DIMENSIONS = [['overall', 'Overall experience'], ['wait_time', 'Waiting time'], ['staff', 'Staff'], ['doctor', 'Doctor'],
  ['cleanliness', 'Cleanliness'], ['communication', 'Communication'], ['appointment_experience', 'Appointment experience']] as const
type Ratings = Record<(typeof DIMENSIONS)[number][0], number>
interface Analysis { sentiment: string; category: string; urgency: string; theme: string }
interface Mine { items: { id: number; overall: number; comment: string; created_at: string; department: string | null }[]; visits: { id: number; started_at: string; doctor: string; department: string }[] }

function Stars({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <fieldset className="flex items-center justify-between gap-3">
      <legend className="float-left text-sm">{label}</legend>
      <div className="flex gap-0.5">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" onClick={() => onChange(n)} aria-label={`${label}: ${n} of 5`} aria-pressed={value === n} className="rounded p-1">
            <Star className={cn('size-6', n <= value ? 'fill-warn text-warn' : 'text-border')} aria-hidden />
          </button>
        ))}
      </div>
    </fieldset>
  )
}

function Feedback() {
  const mine = useGet<Mine>('feedback', '/feedback/mine')
  const departments = useDepartments()
  const [ratings, setRatings] = useState<Ratings>({ overall: 0, wait_time: 0, staff: 0, doctor: 0, cleanliness: 0, communication: 0, appointment_experience: 0 })
  const [nps, setNps] = useState<number | null>(null)
  const [comment, setComment] = useState('')
  const [target, setTarget] = useState('')
  const [error, setError] = useState('')
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const submit = useAction(() => {
    const [kind, id] = target.split(':')
    return post<{ analysis: Analysis }>('/feedback', { ...ratings, nps, comment, [kind === 'visit' ? 'visit_id' : 'department_id']: id ? Number(id) : null })
  }, { invalidate: ['feedback', 'my-record'], success: 'Thank you. Your feedback was sent.', onSuccess: (out) => {
    setAnalysis(out.analysis); setComment(''); setNps(null); setTarget('')
    setRatings({ overall: 0, wait_time: 0, staff: 0, doctor: 0, cleanliness: 0, communication: 0, appointment_experience: 0 })
  } })
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (Object.values(ratings).some((r) => r === 0) || nps === null) return setError('Please give every rating, including how likely you are to recommend us.')
    setError(''); setAnalysis(null); submit.mutate()
  }
  return (
    <>
      <PageHeader title="Feedback" subtitle="Tell us how your visit went. It takes under a minute." />
      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Card className="p-5">
          <form onSubmit={onSubmit} className="space-y-5">
            {error && <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2 text-sm text-crit">{error}</p>}
            <Select label="What is this feedback about?" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">The hospital in general</option>
              {!!mine.data?.visits.length && <optgroup label="A recent visit">{mine.data.visits.map((v) => <option key={v.id} value={`visit:${v.id}`}>{formatDate(v.started_at)} · {v.doctor} ({v.department})</option>)}</optgroup>}
              <optgroup label="A department">{departments.data?.map((d) => <option key={d.id} value={`dept:${d.id}`}>{d.name}</option>)}</optgroup>
            </Select>
            <div className="space-y-2">{DIMENSIONS.map(([key, label]) => <Stars key={key} label={label} value={ratings[key]} onChange={(v) => setRatings((r) => ({ ...r, [key]: v }))} />)}</div>
            <fieldset>
              <legend className="mb-2 text-sm">How likely are you to recommend us to family or friends?</legend>
              <div className="grid grid-cols-11 gap-1">
                {Array.from({ length: 11 }, (_, n) => (
                  <button key={n} type="button" onClick={() => setNps(n)} aria-pressed={nps === n} aria-label={`${n} out of 10`}
                    className={cn('rounded-md border py-2 text-xs font-medium tabular', nps === n ? 'border-brand bg-brand text-on-brand' : 'hover:border-brand')}>{n}</button>
                ))}
              </div>
              <p className="mt-1 flex justify-between text-[11px] text-subtle"><span>Not at all likely</span><span>Extremely likely</span></p>
            </fieldset>
            <Textarea label="Anything you'd like to add? (optional)" value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} placeholder="What went well, and what could we do better?" />
            <Button type="submit" variant="primary" className="w-full" loading={submit.isPending}>Send feedback</Button>
          </form>
        </Card>
        <div className="space-y-4">
          {analysis && (
            <Card className="p-4" aria-live="polite">
              <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">How we filed your feedback</h2><AiLabel title="Classified automatically so it reaches the right team">AI classified</AiLabel></div>
              <dl className="mt-3 grid grid-cols-[6rem_1fr] items-center gap-y-2 text-sm">
                <dt className="text-muted">Sentiment</dt><dd><StatusBadge status={analysis.sentiment} /></dd>
                <dt className="text-muted">Category</dt><dd>{humanize(analysis.category)}</dd>
                <dt className="text-muted">Urgency</dt><dd><StatusBadge status={analysis.urgency} /></dd>
                <dt className="text-muted">Theme</dt><dd>{analysis.theme}</dd>
              </dl>
              <p className="mt-3 text-xs text-subtle">The Patient Experience team reviews feedback every week.</p>
            </Card>
          )}
          <Card className="p-4">
            <h2 className="text-sm font-semibold">Your previous feedback</h2>
            <Async query={mine} what="your feedback" skeleton={<LoadingSkeleton rows={2} />} empty={(d) => !d.items.length && <p className="mt-2 text-sm text-muted">You haven't sent any feedback yet.</p>}>
              {(d) => (
                <ul className="mt-2 divide-y">
                  {d.items.map((f) => (
                    <li key={f.id} className="py-2.5 last:pb-0">
                      <p className="flex items-center gap-1 text-sm font-medium"><Star className="size-3.5 fill-warn text-warn" aria-hidden />{f.overall} / 5<span className="ml-auto text-xs font-normal text-subtle">{formatDate(f.created_at)}</span></p>
                      {f.comment && <p className="mt-0.5 text-sm text-muted">“{f.comment}”</p>}
                    </li>
                  ))}
                </ul>
              )}
            </Async>
          </Card>
        </div>
      </div>
    </>
  )
}

// ----------------------------------------------------------------------------- profile
function Profile() {
  const { user, reload, logout } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ full_name: '', phone: '', address: '', emergency_contact: '', allergies: '' })
  const [error, setError] = useState('')
  useEffect(() => { reload() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const p = user?.profile
  useEffect(() => {
    if (user) setForm({ full_name: user.full_name, phone: p?.phone ?? '', address: p?.address ?? '', emergency_contact: p?.emergency_contact ?? '', allergies: p?.allergies ?? '' })
  }, [user?.id, p?.mrn]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = useAction(() => patch('/auth/me', form), { success: 'Profile updated', onSuccess: () => { reload() } })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (form.full_name.trim().length < 2) return setError('Enter your full name.')
    setError(''); save.mutate()
  }
  if (!user) return null
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Profile" subtitle="Keep your contact details up to date." />
      <Card className="mb-4 flex flex-wrap items-center gap-4 p-5">
        <Avatar name={user.full_name} className="size-14 text-lg" />
        <div className="min-w-0 flex-1"><p className="text-lg font-semibold">{user.full_name}</p><p className="truncate text-sm text-muted">{user.email}</p></div>
        <Button icon={LogOut} onClick={async () => { await logout(); navigate('/login') }}>Sign out</Button>
      </Card>
      {p && (
        <Card className="mb-4 p-5">
          <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            {[['Patient ID', p.mrn], ['Date of birth', formatDate(p.date_of_birth)], ['Blood group', p.blood_group || '—'], ['Insurance', p.insurance_provider || '—']].map(([label, value]) => (
              <div key={label}><dt className="text-xs text-subtle">{label}</dt><dd className="mt-0.5 font-medium">{value}</dd></div>
            ))}
          </dl>
        </Card>
      )}
      <Card className="p-5">
        <form onSubmit={onSubmit} className="space-y-4">
          {error && <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2 text-sm text-crit">{error}</p>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Full name" autoComplete="name" value={form.full_name} onChange={set('full_name')} />
            <Input label="Phone" type="tel" autoComplete="tel" value={form.phone} onChange={set('phone')} maxLength={32} />
          </div>
          <Input label="Address" autoComplete="street-address" value={form.address} onChange={set('address')} maxLength={255} />
          <Input label="Emergency contact" value={form.emergency_contact} onChange={set('emergency_contact')} maxLength={160} hint="Name and phone number" />
          <Input label="Allergies" value={form.allergies} onChange={set('allergies')} maxLength={255} />
          <div className="flex justify-end"><Button type="submit" variant="primary" loading={save.isPending}>Save changes</Button></div>
        </form>
      </Card>
    </div>
  )
}

export default function PatientRecords({ view }: { view: 'documents' | 'feedback' | 'profile' }) {
  return view === 'documents' ? <Documents /> : view === 'feedback' ? <Feedback /> : <Profile />
}
