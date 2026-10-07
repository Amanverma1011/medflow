import { BedDouble, ClipboardCheck } from 'lucide-react'
import { useState } from 'react'
import { BedGrid, BedLegend } from '@/components/BedGrid'
import { MetricCard, StatusBadge } from '@/components/data'
import { Async, Badge, Button, Card, EmptyState, Input, LoadingSkeleton, Modal, PageHeader, Tabs } from '@/components/ui'
import { AreaChart, BarChart, ChartCard, LineChart } from '@/charts'
import { useAuth } from '@/hooks/useAuth'
import { useDebounced } from '@/hooks/useUi'
import { cn, formatDateTime, humanize, timeAgo } from '@/lib/format'
import { LIVE, patch, post, useAction, useGet } from '@/services/queries'
import type { Bed, BedStatus, ChartBlock, Paged, PatientRow, Ward } from '@/types'

const KEYS = ['beds', 'bed-tasks', 'overview', 'analytics-beds', 'patients']
interface Task { type: string; bed_id: number; title: string; detail: string; due: string; overdue?: boolean }
type BedAnalytics = Record<'by_ward' | 'occupancy_trend' | 'ward_stats' | 'discharge_processing', ChartBlock>

function BedDialog({ bed, onClose }: { bed: Bed | null; onClose: () => void }) {
  const { can } = useAuth()
  const manage = can('beds:manage')
  const [search, setSearch] = useState('')
  const [patient, setPatient] = useState<PatientRow | null>(null)
  const term = useDebounced(search, 250)
  const canAssign = !!bed && manage && (bed.status === 'available' || bed.status === 'reserved')
  const patients = useGet<Paged<PatientRow>>('patients', '/patients', { q: term, size: 5 }, { enabled: canAssign && term.length >= 2 && !patient })
  const close = () => { setSearch(''); setPatient(null); onClose() }
  const run = useAction((fn: () => Promise<unknown>) => fn(), { invalidate: KEYS, success: 'Bed updated', onSuccess: close })
  if (!bed) return null
  const others = (['available', 'cleaning', 'maintenance', 'reserved'] as BedStatus[]).filter((s) => s !== bed.status)
  return (
    <Modal open onClose={close} title={`Bed ${bed.label}`}>
      <div className="space-y-4">
        <div className="flex items-center gap-2"><StatusBadge status={bed.status} />{bed.patient && <span className="text-sm font-medium">{bed.patient}</span>}</div>
        {bed.status === 'occupied' && (
          <>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div><dt className="text-xs text-subtle">Admitted</dt><dd>{formatDateTime(bed.assigned_at)}</dd></div>
              <div><dt className="text-xs text-subtle">Expected discharge</dt><dd>{formatDateTime(bed.expected_discharge_at)}</dd></div>
            </dl>
            {manage && <Button variant="primary" loading={run.isPending} onClick={() => run.mutate(() => post(`/beds/${bed.id}/release`))}>Discharge and send to cleaning</Button>}
          </>
        )}
        {canAssign && (
          <div>
            <p className="mb-1.5 text-[13px] font-medium text-muted">Admit a patient</p>
            {patient ? (
              <div className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
                <span>{patient.full_name} <span className="text-muted">· {patient.mrn}</span></span>
                <Button size="sm" variant="primary" loading={run.isPending} onClick={() => run.mutate(() => post(`/beds/${bed.id}/assign`, { patient_id: patient.id }))}>Admit</Button>
              </div>
            ) : (
              <>
                <Input aria-label="Search patient" placeholder="Search by name or patient ID" value={search} onChange={(e) => setSearch(e.target.value)} />
                {patients.data && (
                  <ul className="mt-1.5 overflow-hidden rounded-lg border text-sm">
                    {!patients.data.items.length && <li className="px-3 py-2 text-muted">No patients match.</li>}
                    {patients.data.items.map((p) => (
                      <li key={p.id}><button onClick={() => setPatient(p)} disabled={p.status === 'admitted'} className="flex w-full justify-between px-3 py-2 text-left hover:bg-surface-2 disabled:opacity-50">
                        <span>{p.full_name}</span><span className="text-muted">{p.status === 'admitted' ? 'Already admitted' : p.mrn}</span></button></li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
        {manage && bed.status !== 'occupied' && (
          <div>
            <p className="mb-1.5 text-[13px] font-medium text-muted">Change status</p>
            <div className="flex flex-wrap gap-2">
              {others.map((s) => <Button key={s} size="sm" loading={run.isPending} onClick={() => run.mutate(() => patch(`/beds/${bed.id}`, { status: s }))}>Mark {humanize(s).toLowerCase()}</Button>)}
            </div>
          </div>
        )}
        {!manage && <p className="text-sm text-muted">Your role can view beds but not change them.</p>}
      </div>
    </Modal>
  )
}

export default function Beds() {
  const [tab, setTab] = useState<'map' | 'tasks' | 'analytics'>('map')
  const [selected, setSelected] = useState<Bed | null>(null)
  const beds = useGet<{ wards: Ward[]; summary: Record<string, number> }>('beds', '/beds', undefined, LIVE)
  const tasks = useGet<{ tasks: Task[] }>('bed-tasks', '/beds/tasks', undefined, LIVE)
  const analytics = useGet<BedAnalytics>('analytics-beds', '/beds/analytics', undefined, { enabled: tab === 'analytics' })
  const done = useAction((id: number) => patch(`/beds/${id}`, { status: 'available' }), { invalidate: KEYS, success: 'Bed marked available' })

  return (
    <>
      <PageHeader title="Beds & Resources" subtitle="Live ward map, turnaround work and occupancy analytics." />
      <Async query={beds} what="bed status" skeleton={<LoadingSkeleton variant="cards" rows={4} />}>
        {(b) => (
          <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard label="Occupancy rate" icon={BedDouble} value={`${b.summary.occupancy_rate}%`} tone={b.summary.occupancy_rate >= 85 ? 'warn' : 'neutral'} footer={<span>{b.summary.occupied ?? 0} of {b.summary.total} beds</span>} />
            <MetricCard label="Available now" value={b.summary.available ?? 0} tone="ok" />
            <MetricCard label="Being cleaned" value={b.summary.cleaning ?? 0} />
            <MetricCard label="Maintenance / reserved" value={`${b.summary.maintenance ?? 0} / ${b.summary.reserved ?? 0}`} />
          </div>
        )}
      </Async>
      <Tabs label="Beds" value={tab} onChange={setTab} tabs={[{ id: 'map', label: 'Ward map' }, { id: 'tasks', label: `Ward tasks${tasks.data ? ` (${tasks.data.tasks.length})` : ''}` }, { id: 'analytics', label: 'Analytics' }]} />

      {tab === 'map' && (
        <Async query={beds} what="the ward map" skeleton={<LoadingSkeleton rows={6} />}>
          {(b) => (
            <>
              <div className="mb-4"><BedLegend counts={b.summary} /></div>
              <div className="grid gap-4 xl:grid-cols-2">
                {b.wards.map((w) => (
                  <Card key={w.id} className="p-4">
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <div><h2 className="text-sm font-semibold">{w.name}</h2><p className="text-xs text-muted">{w.floor}{w.department ? ` · ${w.department}` : ''}</p></div>
                      <Badge tone={w.occupancy_rate >= 90 ? 'crit' : w.occupancy_rate >= 80 ? 'warn' : 'neutral'}>{w.occupancy_rate}% occupied</Badge>
                    </div>
                    <BedGrid ward={w} onSelect={setSelected} />
                  </Card>
                ))}
              </div>
            </>
          )}
        </Async>
      )}

      {tab === 'tasks' && (
        <Card>
          <Async query={tasks} what="ward tasks" empty={(d) => !d.tasks.length && <EmptyState icon={ClipboardCheck} title="No outstanding ward tasks" body="Bed turnarounds and upcoming discharges appear here." />}>
            {(d) => (
              <ul className="divide-y">
                {d.tasks.map((t) => (
                  <li key={`${t.type}-${t.bed_id}`} className="flex flex-wrap items-center gap-3 px-4 py-3">
                    <Badge tone={t.type === 'discharge' ? 'info' : 'warn'}>{t.type === 'discharge' ? 'Discharge' : 'Turnaround'}</Badge>
                    <div className="min-w-0 flex-1"><p className="text-sm font-medium">{t.title}</p><p className="text-xs text-muted">{t.detail}</p></div>
                    <span className={cn('text-xs tabular', t.overdue ? 'font-medium text-crit' : 'text-muted')}>{t.type === 'discharge' ? `${t.overdue ? 'Overdue · ' : 'Due '}${formatDateTime(t.due)}` : `Started ${timeAgo(new Date(new Date(t.due).getTime() - 3_600_000))}`}</span>
                    {t.type === 'turnaround' && <Button size="sm" loading={done.isPending && done.variables === t.bed_id} onClick={() => done.mutate(t.bed_id)}>Mark ready</Button>}
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </Card>
      )}

      {tab === 'analytics' && (
        <Async query={analytics} what="bed analytics" skeleton={<LoadingSkeleton variant="chart" />}>
          {(a) => (
            <div className="grid gap-4 xl:grid-cols-2">
              <ChartCard title="Occupancy Rate" question="Is the hospital filling up or easing?" {...a.occupancy_trend}><AreaChart data={a.occupancy_trend.data} x="day" unit="%" series={[{ key: 'occupancy', label: 'Occupancy' }]} /></ChartCard>
              <ChartCard title="Average Length of Stay" question="Which wards keep patients longest?" {...a.ward_stats}><BarChart data={a.ward_stats.data} x="ward" horizontal unit=" days" series={[{ key: 'avg_stay_days', label: 'Average stay' }]} /></ChartCard>
              <ChartCard title="Bed Turnover" question="How many patients does each bed serve in 30 days?" range={a.ward_stats.range}><BarChart data={a.ward_stats.data} x="ward" horizontal series={[{ key: 'turnover', label: 'Patients per bed' }]} /></ChartCard>
              <ChartCard title="Department Demand" question="Where are admissions concentrated?" range={a.ward_stats.range}><BarChart data={a.ward_stats.data} x="ward" horizontal series={[{ key: 'admissions', label: 'Admissions' }]} /></ChartCard>
              <ChartCard title="Discharge Processing Time" question="How long from discharge order to bed release?" {...a.discharge_processing} className="xl:col-span-2"><LineChart data={a.discharge_processing.data} x="day" unit=" h" series={[{ key: 'hours', label: 'Hours' }]} /></ChartCard>
            </div>
          )}
        </Async>
      )}
      <BedDialog bed={selected} onClose={() => setSelected(null)} />
    </>
  )
}
