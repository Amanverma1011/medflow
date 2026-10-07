import { useState } from 'react'
import { Factors, PredictionCard } from '@/components/cards'
import { type Column, Confidence, DataTable, MetricCard } from '@/components/data'
import { Async, Card, LoadingSkeleton, PageHeader, Select, Tabs } from '@/components/ui'
import { AreaChart, BarChart, ChartCard, DonutChart, LineChart, ScatterChart } from '@/charts'
import { formatDateTime, num } from '@/lib/format'
import { useDepartments, useDoctors, useGet } from '@/services/queries'
import type { ChartBlock, Factor, Metric } from '@/types'
import { ExperienceCharts, type ExperienceData } from './Experience'
import { OperationsCharts, type Operations } from './Overview'

const TABS = [
  { id: 'operations', label: 'Operations' }, { id: 'patients', label: 'Patients' }, { id: 'appointments', label: 'Appointments' },
  { id: 'doctors', label: 'Doctors' }, { id: 'beds', label: 'Beds' }, { id: 'patient-experience', label: 'Patient Experience' },
  { id: 'predictions', label: 'AI Predictions' },
] as const
type TabId = (typeof TABS)[number]['id']
type Blocks = Record<string, ChartBlock> & { range: string }

export interface Predictions {
  label: string
  patient_volume: { next_hour: number; next_day: number; next_week: number; confidence: number; factors: Factor[]; series: Record<string, any>[]; label: string }
  no_show: { base_rate: number | null; upcoming: number; elevated: number; threshold: number; confidence: number; factors: Factor[]; label: string
    appointments: { appointment_id: number; patient?: string; scheduled_at: string; probability: number; factors: Factor[] }[] }
  wait_time: { department: string; value: number; confidence: number; factors: Factor[]; label: string }[]
  bed_occupancy: { ward: string; current: number; value: number; confidence: number; horizon_hours: number; factors: Factor[]; label: string }[]
}

export function PredictionsView({ data: p }: { data: Predictions }) {
  const worstWait = [...p.wait_time].sort((a, b) => b.value - a.value)[0]
  const icu = p.bed_occupancy.find((w) => w.ward === 'ICU') ?? p.bed_occupancy[0]
  const riskColumns: Column<Predictions['no_show']['appointments'][number]>[] = [
    { key: 'when', header: 'Appointment', cell: (a) => <span className="tabular">{formatDateTime(a.scheduled_at)}</span> },
    { key: 'patient', header: 'Patient', cell: (a) => a.patient ?? <span className="text-subtle">Hidden for your role</span> },
    { key: 'p', header: 'No-show risk', cell: (a) => <span className="font-semibold tabular">{Math.round(a.probability * 100)}%</span> },
    { key: 'why', header: 'Main contributing factors', cell: (a) => <span className="text-muted">{a.factors.map((f) => `${f.name}: ${f.detail}`).join(' · ') || 'Baseline risk'}</span>, hideBelow: 'md' },
  ]
  return (
    <div className="space-y-4">
      <p className="rounded-lg border border-dashed px-3 py-2 text-xs text-muted">{p.label}. Models are simple, inspectable statistics fitted to this hospital's recent history.</p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <PredictionCard title="Patient volume · tomorrow" value={num(p.patient_volume.next_day)} unit="patients" confidence={p.patient_volume.confidence} factors={p.patient_volume.factors} label={p.patient_volume.label}
          extra={<p className="mt-2 text-xs text-muted">Next hour <span className="font-medium text-text tabular">{p.patient_volume.next_hour}</span> · Next 7 days <span className="font-medium text-text tabular">{num(p.patient_volume.next_week)}</span></p>} />
        <PredictionCard title="No-show risk · next 48 h" value={p.no_show.elevated} unit={`of ${p.no_show.upcoming} appointments`} confidence={p.no_show.confidence} factors={p.no_show.factors} label={p.no_show.label}
          extra={<p className="mt-2 text-xs text-muted">Baseline rate <span className="font-medium text-text tabular">{p.no_show.base_rate !== null ? `${num(p.no_show.base_rate * 100, 1)}%` : '—'}</span></p>} />
        {worstWait && <PredictionCard title={`Expected waiting time · ${worstWait.department}`} value={worstWait.value} unit="minutes" confidence={worstWait.confidence} factors={worstWait.factors} label={worstWait.label} />}
        {icu && <PredictionCard title={`${icu.ward} occupancy · in ${icu.horizon_hours} h`} value={`${icu.value}%`} confidence={icu.confidence} factors={icu.factors} label={icu.label}
          extra={<p className="mt-2 text-xs text-muted">Currently <span className="font-medium text-text tabular">{icu.current}%</span></p>} />}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard title="Patient Volume Forecast" question="What does the next week look like against the last?" range="Last 7 days and next 7 days">
          <LineChart data={p.patient_volume.series} x="day" series={[{ key: 'actual', label: 'Actual' }, { key: 'predicted', label: 'Predicted' }]} />
        </ChartCard>
        <ChartCard title="Bed Occupancy Forecast" question="Which wards will be tight in six hours?" range="Now vs +6 hours">
          <BarChart data={p.bed_occupancy} x="ward" unit="%" series={[{ key: 'current', label: 'Now' }, { key: 'value', label: 'Predicted' }]} />
        </ChartCard>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <Card>
          <h3 className="px-4 pt-4 text-sm font-semibold">Appointments with elevated no-show risk</h3>
          <p className="px-4 pb-2 text-xs text-subtle">Recommended action: send reminder notifications. Risk ≥ {Math.round(p.no_show.threshold * 100)}%.</p>
          <DataTable caption="Appointments with elevated no-show risk" columns={riskColumns} rows={p.no_show.appointments.slice(0, 10)} rowKey={(a) => a.appointment_id}
            empty={{ title: 'No appointments above the risk threshold' }} />
        </Card>
        <Card className="p-4">
          <h3 className="text-sm font-semibold">Wait-time prediction by department</h3>
          <ul className="mt-3 space-y-3">
            {p.wait_time.map((w) => (
              <li key={w.department}>
                <div className="flex items-baseline justify-between text-sm"><span>{w.department}</span><span className="font-semibold tabular">{w.value} min</span></div>
                <Confidence value={w.confidence} className="mt-1" />
              </li>
            ))}
          </ul>
          {worstWait && <div className="mt-4 border-t pt-3"><Factors factors={worstWait.factors} title={`Why ${worstWait.department} is highest`} /></div>}
        </Card>
      </div>
    </div>
  )
}

function Headline({ label, metric }: { label: string; metric: Metric }) {
  return <MetricCard label={label} value={typeof metric.value === 'number' ? num(metric.value, 1) : (metric.value ?? '—')} unit={metric.unit} trend={metric.trend} lowerIsBetter={metric.lower_is_better} compare="vs previous period" />
}

export default function Analytics() {
  const [tab, setTab] = useState<TabId>('operations')
  const [filters, setFilters] = useState({ days: '14', department_id: '', doctor_id: '' })
  const departments = useDepartments()
  const doctors = useDoctors()
  const isPredictions = tab === 'predictions'
  const query = useGet<any>('analytics', isPredictions ? '/ai/predictions' : `/analytics/${tab}`, isPredictions || tab === 'beds' ? undefined : filters)
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => setFilters((f) => ({ ...f, [k]: e.target.value }))
  const filterable = !isPredictions && tab !== 'beds'

  return (
    <>
      <PageHeader title="Analytics" subtitle="Every chart is computed from live records for the selected period."
        actions={filterable && (
          <>
            <Select aria-label="Date range" value={filters.days} onChange={set('days')} className="w-36">
              <option value="7">Last 7 days</option><option value="14">Last 14 days</option><option value="30">Last 30 days</option><option value="45">Last 45 days</option>
            </Select>
            <Select aria-label="Department" value={filters.department_id} onChange={set('department_id')} className="w-44">
              <option value="">All departments</option>{departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
            {tab !== 'patient-experience' && tab !== 'patients' && (
              <Select aria-label="Doctor" value={filters.doctor_id} onChange={set('doctor_id')} className="w-44">
                <option value="">All doctors</option>
                {doctors.data?.filter((d) => !filters.department_id || String(d.department_id) === filters.department_id).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
            )}
          </>
        )} />
      <Tabs label="Analytics" tabs={[...TABS]} value={tab} onChange={setTab} />
      <Async query={query} what="analytics" skeleton={<div className="grid gap-4 xl:grid-cols-2"><LoadingSkeleton variant="chart" /><LoadingSkeleton variant="chart" /></div>}>
        {(d) => {
          // keepPreviousData can briefly hand us the previous tab's payload; wait for the right shape.
          const ready = { operations: 'patient_flow', patients: 'registrations', appointments: 'status_breakdown', doctors: 'utilization', beds: 'occupancy_trend', 'patient-experience': 'dimensions', predictions: 'patient_volume' }[tab]
          if (!(ready in d)) return <LoadingSkeleton variant="chart" />
          if (tab === 'operations') return <OperationsCharts data={d as Operations} />
          if (tab === 'predictions') return <PredictionsView data={d as Predictions} />
          if (tab === 'patient-experience') return <ExperienceCharts data={d as ExperienceData} />
          const b = d as Blocks
          if (tab === 'patients') return (
            <div className="grid gap-4 xl:grid-cols-2">
              <div className="xl:col-span-2 sm:max-w-xs"><Headline label="Unique patients seen" metric={(d as any).unique_patients_seen} /></div>
              <ChartCard title="New Registrations" question="Is the patient base growing?" {...b.registrations}><BarChart data={b.registrations.data} x="week" series={[{ key: 'patients', label: 'New patients' }]} /></ChartCard>
              <ChartCard title="Age Profile" question="Which age groups does the hospital serve?" {...b.age_bands}><BarChart data={b.age_bands.data} x="band" series={[{ key: 'patients', label: 'Patients' }]} /></ChartCard>
              <ChartCard title="Visit Types" question="What mix of visits is being completed?" {...b.visit_types} isEmpty={!b.visit_types.data.length}><DonutChart data={b.visit_types.data as any} /></ChartCard>
              <ChartCard title="Patient Status" question="How many patients are currently admitted?" {...b.status}><DonutChart data={b.status.data as any} /></ChartCard>
            </div>
          )
          if (tab === 'appointments') return (
            <div className="grid gap-4 xl:grid-cols-2">
              <ChartCard title="Daily Outcomes" question="How many appointments complete, and how many are lost?" {...b.daily_outcomes} className="xl:col-span-2" isEmpty={!b.daily_outcomes.data.length}>
                <AreaChart data={b.daily_outcomes.data} x="day" stacked series={[{ key: 'completed', label: 'Completed' }, { key: 'no_show', label: 'No-show' }, { key: 'cancelled', label: 'Cancelled' }]} />
              </ChartCard>
              <ChartCard title="Status Breakdown" question="Where do appointments end up?" {...b.status_breakdown} isEmpty={!b.status_breakdown.data.length}><DonutChart data={b.status_breakdown.data as any} /></ChartCard>
              <ChartCard title="No-Show Rate by Lead Time" question="Do appointments booked further ahead get missed more?" {...b.no_show_by_lead_time} isEmpty={!b.no_show_by_lead_time.data.length}>
                <BarChart data={b.no_show_by_lead_time.data} x="lead_time" unit="%" series={[{ key: 'no_show_rate', label: 'No-show rate' }]} />
              </ChartCard>
            </div>
          )
          if (tab === 'doctors') return (
            <div className="grid gap-4 xl:grid-cols-2">
              <ChartCard title="Doctor Utilization" question="How much scheduled time is spent consulting?" {...b.utilization} height={360} isEmpty={!b.utilization.data.length}>
                <BarChart data={b.utilization.data.slice(0, 12)} x="doctor" horizontal stacked unit=" h" series={[{ key: 'consultation_hours', label: 'Consultation' }, { key: 'idle_hours', label: 'Idle' }, { key: 'overtime_hours', label: 'Overtime' }]} />
              </ChartCard>
              <ChartCard title="Consultation Pace vs Volume" question="Do busier doctors consult faster?" {...b.pace_vs_volume} height={360} isEmpty={!b.pace_vs_volume.data.length}>
                <ScatterChart data={b.pace_vs_volume.data} x="patients" y="avg_consult_minutes" xLabel="Patients seen" yLabel="Avg consult (min)" name="doctor" />
              </ChartCard>
            </div>
          )
          return (
            <div className="grid gap-4 xl:grid-cols-2">
              <ChartCard title="Occupancy Rate" question="Is the hospital filling up or easing?" {...b.occupancy_trend}><AreaChart data={b.occupancy_trend.data} x="day" unit="%" series={[{ key: 'occupancy', label: 'Occupancy' }]} /></ChartCard>
              <ChartCard title="Average Length of Stay" question="Which wards keep patients longest?" {...b.ward_stats}><BarChart data={b.ward_stats.data} x="ward" horizontal unit=" days" series={[{ key: 'avg_stay_days', label: 'Average stay' }]} /></ChartCard>
              <ChartCard title="Discharge Processing Time" question="How long from discharge order to bed release?" {...b.discharge_processing} className="xl:col-span-2"><LineChart data={b.discharge_processing.data} x="day" unit=" h" series={[{ key: 'hours', label: 'Hours' }]} /></ChartCard>
            </div>
          )
        }}
      </Async>
    </>
  )
}
