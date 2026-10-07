import { motion } from 'framer-motion'
import { ArrowRight, Radio } from 'lucide-react'
import { Link } from 'react-router'
import { BedGrid, BedLegend } from '@/components/BedGrid'
import { AIInsightCard } from '@/components/cards'
import { DashboardCard } from '@/components/data'
import { Async, Badge, DemoTag, LoadingSkeleton, PageHeader } from '@/components/ui'
import { BarChart, ChartCard, LineChart } from '@/charts'
import { cn, formatTime, num } from '@/lib/format'
import { LIVE, useGet } from '@/services/queries'
import type { Insight, Ward } from '@/types'
import { FLOW_SERIES, LOAD_TONE, type Operations, type OverviewData } from './Overview'

interface QueueStatus {
  departments: { department: string; value: number; confidence: number; factors: { name: string; detail: string }[] }[]
  longest_waits: { token: string; department: string; doctor: string; waited_minutes: number }[]
}
interface Experience { dimensions: { metric: { value: number; trend: number | null } }; nps: { score: number | null }; sentiment: { data: { name: string; percent: number }[] }; responses: number }

const TONE_TEXT = { crit: 'text-crit', warn: 'text-warn', ok: 'text-ok', info: 'text-info', neutral: '', brand: '' }

function StatusStrip({ o }: { o: OverviewData }) {
  const tone = LOAD_TONE[o.emergency_load.level] ?? 'neutral'
  const cells: [string, React.ReactNode, string?][] = [
    ['Patients Today', num(o.patients_today.value as number)],
    ['Emergency Load', o.emergency_load.level.toUpperCase(), TONE_TEXT[tone]],
    ['Bed Occupancy', `${num(o.bed_occupancy.occupancy_rate)}%`, o.bed_occupancy.occupancy_rate >= 85 ? 'text-warn' : ''],
    ['Avg Wait', `${num(o.avg_wait_minutes.value as number)} min`],
    ['Doctors Available', `${o.doctors_available.on_shift}`],
    ['Critical Alerts', `${o.critical_alerts}`, o.critical_alerts ? 'text-crit' : ''],
  ]
  return (
    <section aria-label="Live hospital status" className="overflow-hidden rounded-xl border bg-surface shadow-card">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <motion.span className="size-2 rounded-full bg-ok" animate={{ opacity: [1, 0.35, 1] }} transition={{ repeat: Infinity, duration: 2 }} aria-hidden />
        <h2 className="text-xs font-semibold tracking-[0.12em] uppercase">Live Hospital Status</h2>
        <span className="ml-auto text-xs text-subtle tabular">Updated {formatTime(o.generated_at)}</span>
      </div>
      <dl className="grid grid-cols-2 divide-x divide-y sm:grid-cols-3 xl:grid-cols-6 xl:divide-y-0">
        {cells.map(([label, value, color]) => (
          <div key={label} className="px-4 py-4">
            <dt className="text-xs text-muted">{label}</dt>
            <dd className={cn('mt-1 text-2xl font-semibold tabular', color)}>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

export default function CommandCenter() {
  const overview = useGet<OverviewData>('overview', '/analytics/overview', undefined, LIVE)
  const ops = useGet<Operations>('operations', '/analytics/operations', { days: 14 }, LIVE)
  const beds = useGet<{ wards: Ward[]; summary: Record<string, number> }>('beds', '/beds', undefined, LIVE)
  const insights = useGet<Insight[]>('insights', '/ai/insights', undefined, LIVE)
  const queue = useGet<QueueStatus>('queue-status', '/analytics/queue-status', undefined, LIVE)
  const experience = useGet<Experience>('experience', '/analytics/patient-experience', { days: 30 })

  return (
    <>
      <PageHeader title="Command Center" subtitle="Live operational picture of MedFlow General Hospital."
        actions={<><Badge tone="ok" icon={Radio}>Live</Badge><DemoTag /></>} />
      <Async query={overview} what="live hospital status" skeleton={<LoadingSkeleton variant="chart" />}>{(o) => <StatusStrip o={o} />}</Async>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Async query={ops} what="patient flow" skeleton={<LoadingSkeleton variant="chart" />}>
            {(o) => (
              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Live Patient Flow" {...o.patient_flow} height={230} isEmpty={!o.patient_flow.data.length}>
                  <LineChart data={o.patient_flow.data} x="hour" series={FLOW_SERIES} />
                </ChartCard>
                <ChartCard title="Department Load" {...o.department_load} height={230}>
                  <BarChart data={o.department_load.data} x="name" stacked series={[
                    { key: 'completed', label: 'Completed' }, { key: 'in_consultation', label: 'In consultation' },
                    { key: 'waiting', label: 'Waiting' }, { key: 'scheduled', label: 'Still to come' }]} />
                </ChartCard>
              </div>
            )}
          </Async>

          <DashboardCard title="Bed Map" subtitle="Every bed, by ward" action={<Link to="/admin/beds" className="flex items-center gap-1 text-xs font-medium text-brand hover:underline">Manage beds<ArrowRight className="size-3" /></Link>}>
            <Async query={beds} what="the bed map" skeleton={<LoadingSkeleton rows={5} />}>
              {(b) => (
                <>
                  <BedLegend counts={b.summary} />
                  <div className="mt-4 grid gap-x-6 gap-y-4 md:grid-cols-2">
                    {b.wards.map((w) => (
                      <div key={w.id}>
                        <p className="mb-1.5 flex justify-between text-xs"><span className="font-medium">{w.name}</span>
                          <span className={cn('tabular', w.occupancy_rate >= 85 ? 'font-medium text-warn' : 'text-subtle')}>{w.occupancy_rate}%</span></p>
                        <BedGrid ward={w} dense />
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Async>
          </DashboardCard>
        </div>

        <div className="space-y-4">
          <DashboardCard title="AI Alerts" subtitle="Recommendations for human review" action={<Link to="/admin/ai-insights" className="text-xs font-medium text-brand hover:underline">Details</Link>} flush>
            <Async query={insights} what="AI alerts" skeleton={<div className="p-4"><LoadingSkeleton rows={3} /></div>}
              empty={(d) => !d.length && <p className="p-6 text-center text-sm text-muted">No active alerts.</p>}>
              {(items) => <div className="space-y-3 px-4 pb-4">{items.slice(0, 3).map((i) => <AIInsightCard key={i.id} insight={i} compact />)}</div>}
            </Async>
          </DashboardCard>

          <DashboardCard title="Queue Status" subtitle="Predicted wait for a new arrival" flush>
            <Async query={queue} what="queue status" skeleton={<div className="p-4"><LoadingSkeleton rows={4} /></div>}>
              {(q) => (
                <ul className="divide-y text-sm">
                  {q.departments.map((d) => (
                    <li key={d.department} className="flex items-center gap-3 px-4 py-2.5" title={d.factors.map((f) => `${f.name}: ${f.detail}`).join('\n')}>
                      <span className="min-w-0 flex-1 truncate">{d.department}</span>
                      <span className="text-xs text-subtle">{d.factors[0]?.detail}</span>
                      <span className={cn('w-16 text-right font-semibold tabular', d.value >= 35 ? 'text-crit' : d.value >= 25 ? 'text-warn' : '')}>{d.value} min</span>
                    </li>
                  ))}
                </ul>
              )}
            </Async>
          </DashboardCard>

          <DashboardCard title="Patient Satisfaction" subtitle="Last 30 days">
            <Async query={experience} what="patient satisfaction" skeleton={<LoadingSkeleton rows={2} />}>
              {(e) => (
                <div className="flex items-end gap-6">
                  <div><p className="text-3xl font-semibold tabular">{num(e.dimensions.metric.value, 1)}<span className="text-base font-normal text-muted"> / 5</span></p>
                    <p className="text-xs text-subtle">{e.responses} responses</p></div>
                  <div><p className="text-xl font-semibold tabular">{e.nps.score ?? '—'}</p><p className="text-xs text-subtle">NPS</p></div>
                  <ul className="ml-auto space-y-0.5 text-xs text-muted">
                    {e.sentiment.data.map((s) => <li key={s.name} className="flex justify-between gap-4 capitalize">{s.name}<span className="font-medium text-text tabular">{s.percent}%</span></li>)}
                  </ul>
                </div>
              )}
            </Async>
          </DashboardCard>
        </div>
      </div>
    </>
  )
}
