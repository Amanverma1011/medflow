import { Activity, BedDouble, CalendarCheck, Clock, Siren, Smile, Users } from 'lucide-react'
import { Link } from 'react-router'
import { AIInsightCard } from '@/components/cards'
import { MetricCard } from '@/components/data'
import { Async, DemoTag, LoadingSkeleton, PageHeader, SectionTitle, type Tone } from '@/components/ui'
import { BarChart, BED_COLORS, ChartCard, Heatmap, LineChart } from '@/charts'
import { num } from '@/lib/format'
import { LIVE, useGet } from '@/services/queries'
import type { ChartBlock, Insight, Metric } from '@/types'

export interface OverviewData {
  generated_at: string
  patients_today: Metric & { compare: string }
  avg_wait_minutes: Metric & { compare: string }
  bed_occupancy: { occupancy_rate: number; total: number; occupied?: number; available?: number; cleaning?: number; maintenance?: number; reserved?: number }
  emergency_load: { level: string; vs_baseline_pct: number; today: number; baseline: number; waiting: number }
  appointment_completion: Metric & { compare: string }
  patient_satisfaction: Metric & { compare: string }
  doctors_available: { on_shift: number; total: number }
  waiting_now: number
  critical_alerts: number
}
export type Operations = Record<'patient_flow' | 'department_load' | 'hourly_volume' | 'wait_distribution' | 'bed_occupancy' | 'doctor_utilization', ChartBlock> & { range: string }

export const LOAD_TONE: Record<string, Tone> = { High: 'crit', Elevated: 'warn', Normal: 'ok', Low: 'info' }

/** The six headline cards. Every value comes from GET /api/analytics/overview. */
export function HeadlineCards({ data: o }: { data: OverviewData }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      <MetricCard label="Today's Patients" icon={Users} value={num(o.patients_today.value as number)} trend={o.patients_today.trend} compare={o.patients_today.compare} />
      <MetricCard label="Average Wait Time" icon={Clock} value={num(o.avg_wait_minutes.value as number)} unit="min" trend={o.avg_wait_minutes.trend} lowerIsBetter compare={o.avg_wait_minutes.compare} />
      <MetricCard label="Bed Occupancy" icon={BedDouble} value={`${num(o.bed_occupancy.occupancy_rate)}%`}
        tone={o.bed_occupancy.occupancy_rate >= 90 ? 'crit' : o.bed_occupancy.occupancy_rate >= 80 ? 'warn' : 'neutral'}
        footer={<span>{o.bed_occupancy.occupied ?? 0} of {o.bed_occupancy.total} beds</span>} />
      <MetricCard label="Emergency Load" icon={Siren} value={o.emergency_load.level} tone={LOAD_TONE[o.emergency_load.level]}
        footer={<span>{o.emergency_load.vs_baseline_pct > 0 ? '+' : ''}{num(o.emergency_load.vs_baseline_pct)}% vs 7-day average</span>} />
      <MetricCard label="Appointment Completion" icon={CalendarCheck} value={`${num(o.appointment_completion.value as number, 1)}%`} trend={o.appointment_completion.trend} compare={o.appointment_completion.compare} />
      <MetricCard label="Patient Satisfaction" icon={Smile} value={num(o.patient_satisfaction.value as number, 1)} unit="/ 5" trend={o.patient_satisfaction.trend} compare={o.patient_satisfaction.compare} />
    </div>
  )
}

export const FLOW_SERIES = [
  { key: 'check_in', label: 'Check-in' }, { key: 'waiting', label: 'Waiting' },
  { key: 'consultation', label: 'Consultation' }, { key: 'discharge', label: 'Discharge' },
]
export const BED_SERIES = ['occupied', 'available', 'cleaning', 'maintenance', 'reserved'].map((k) => ({ key: k, label: k[0].toUpperCase() + k.slice(1), color: BED_COLORS[k] }))

export function OperationsCharts({ data: ops }: { data: Operations }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ChartCard title="Patient Flow" question="How are patients moving through the hospital today?" {...ops.patient_flow} isEmpty={!ops.patient_flow.data.length}>
        <LineChart data={ops.patient_flow.data} x="hour" series={FLOW_SERIES} />
      </ChartCard>
      <ChartCard title="Department Load" question="Which departments carry the most patients today?" {...ops.department_load}>
        <BarChart data={ops.department_load.data} x="name" stacked series={[
          { key: 'completed', label: 'Completed' }, { key: 'in_consultation', label: 'In consultation' },
          { key: 'waiting', label: 'Waiting' }, { key: 'scheduled', label: 'Still to come' }]} />
      </ChartCard>
      <ChartCard title="Hourly Patient Volume" question="When is the hospital busiest across the week?" range={ops.hourly_volume.range} isEmpty={!ops.hourly_volume.data.length}>
        <Heatmap data={ops.hourly_volume.data as any} />
      </ChartCard>
      <ChartCard title="Waiting Time Distribution" question="How long do patients wait before being seen?" {...ops.wait_distribution}>
        <BarChart data={ops.wait_distribution.data} x="range" series={[{ key: 'patients', label: 'Patients' }]} />
      </ChartCard>
      <ChartCard title="Bed Occupancy" question="Where is bed capacity tied up right now?" {...ops.bed_occupancy}>
        <BarChart data={ops.bed_occupancy.data} x="name" stacked horizontal series={BED_SERIES} />
      </ChartCard>
      <ChartCard title="Doctor Utilization" question="How is scheduled clinic time being used?" {...ops.doctor_utilization} isEmpty={!ops.doctor_utilization.data.length}>
        <BarChart data={ops.doctor_utilization.data.slice(0, 8)} x="doctor" horizontal stacked unit=" h" series={[
          { key: 'consultation_hours', label: 'Consultation' }, { key: 'idle_hours', label: 'Idle' }, { key: 'overtime_hours', label: 'Overtime' }]} />
      </ChartCard>
    </div>
  )
}

export default function Overview() {
  const overview = useGet<OverviewData>('overview', '/analytics/overview', undefined, LIVE)
  const ops = useGet<Operations>('operations', '/analytics/operations', { days: 14 }, LIVE)
  const insights = useGet<Insight[]>('insights', '/ai/insights')
  return (
    <>
      <PageHeader title="Overview" subtitle="Hospital-wide operations at a glance." actions={<DemoTag />} />
      <Async query={overview} what="today's metrics" skeleton={<LoadingSkeleton variant="cards" rows={6} />}>{(o) => <HeadlineCards data={o} />}</Async>

      <section className="mt-6" aria-label="AI operations insights">
        <SectionTitle aside={<Link to="/admin/ai-insights" className="text-xs font-medium text-brand hover:underline">View all</Link>}>
          <span className="flex items-center gap-1.5"><Activity className="size-4 text-brand" aria-hidden />AI Operations Insights</span>
        </SectionTitle>
        <Async query={insights} what="AI insights" skeleton={<LoadingSkeleton rows={2} />}
          empty={(d) => !d.length && <p className="rounded-xl border bg-surface p-6 text-center text-sm text-muted">No active insights. Operations look normal.</p>}>
          {(items) => <div className="grid gap-4 xl:grid-cols-2">{items.slice(0, 2).map((i) => <AIInsightCard key={i.id} insight={i} compact />)}</div>}
        </Async>
      </section>

      <div className="mt-6"><Async query={ops} what="operations charts" skeleton={<LoadingSkeleton variant="chart" />}>{(o) => <OperationsCharts data={o} />}</Async></div>
    </>
  )
}
