import { useState } from 'react'
import { AiLabel } from '@/components/cards'
import { DashboardCard, MetricCard, Pagination, StatusBadge, Trend } from '@/components/data'
import { Async, Card, EmptyState, LoadingSkeleton, PageHeader, Select } from '@/components/ui'
import { BarChart, ChartCard, DonutChart, LineChart } from '@/charts'
import { formatDate, humanize, num } from '@/lib/format'
import { useDepartments, useGet } from '@/services/queries'
import type { ChartBlock, Metric, Paged } from '@/types'

export interface ExperienceData {
  range: string
  responses: number
  dimensions: ChartBlock & { metric: Metric }
  nps: { promoters: number; passives: number; detractors: number; total: number; score: number | null; trend: number | null; range: string }
  sentiment: ChartBlock<{ name: string; value: number; percent: number }>
  categories: ChartBlock
  weekly: ChartBlock
  themes: { theme: string; category: string; mentions: number; high_urgency: number }[]
  complaints: ChartBlock & { metric: Metric }
}
interface FeedbackRow { id: number; overall: number; comment: string; sentiment: string; category: string; urgency: string; theme: string; created_at: string; department: string | null }

const SENTIMENT_COLORS = { positive: 'var(--ok)', neutral: 'var(--axis)', negative: 'var(--crit)' }
const CATEGORIES = ['waiting_time', 'staff_behavior', 'doctor_communication', 'billing', 'cleanliness', 'appointment', 'facilities', 'pharmacy', 'emergency_care']

/** NPS as one proportional bar: detractors, passives, promoters. */
function NpsBar({ nps }: { nps: ExperienceData['nps'] }) {
  const parts = [['Detractors (0–6)', nps.detractors, 'bg-crit'], ['Passives (7–8)', nps.passives, 'bg-subtle'], ['Promoters (9–10)', nps.promoters, 'bg-ok']] as const
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between"><h3 className="text-sm font-semibold">Net Promoter Score</h3><span className="text-xs text-subtle">{nps.range}</span></div>
      <p className="mt-2 flex items-baseline gap-2"><span className="text-3xl font-semibold tabular">{nps.score ?? '—'}</span><Trend value={nps.trend} suffix=" pts" /></p>
      <div className="mt-4 flex h-3 gap-[2px] overflow-hidden rounded-full" role="img" aria-label={`${nps.promoters} promoters, ${nps.passives} passives, ${nps.detractors} detractors`}>
        {parts.map(([label, n, color]) => n > 0 && <div key={label} className={color} style={{ width: `${(n / nps.total) * 100}%` }} title={`${label}: ${n}`} />)}
      </div>
      <ul className="mt-3 grid grid-cols-3 gap-2 text-xs">
        {parts.map(([label, n, color]) => (
          <li key={label}><span className="flex items-center gap-1.5 text-muted"><span className={`size-2 rounded-sm ${color}`} aria-hidden />{label}</span>
            <span className="mt-0.5 block text-sm font-semibold tabular">{nps.total ? Math.round((n / nps.total) * 100) : 0}%</span></li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] text-subtle">NPS = % promoters − % detractors, from {nps.total} responses.</p>
    </Card>
  )
}

export function ExperienceCharts({ data: e }: { data: ExperienceData }) {
  if (!e.responses) return <Card><EmptyState title="No feedback in this period" body="Try a longer date range or a different department." /></Card>
  const share = (name: string) => e.sentiment.data.find((s) => s.name === name)?.percent ?? 0
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="Satisfaction" value={num(e.dimensions.metric.value as number, 2)} unit="/ 5" trend={e.dimensions.metric.trend} compare="vs previous period" />
        <MetricCard label="Responses" value={e.responses} />
        <MetricCard label="Negative sentiment" value={`${share('negative')}%`} tone={share('negative') >= 25 ? 'warn' : 'neutral'} />
        <MetricCard label="Complaint Volume" value={num(e.complaints.metric.value as number)} trend={e.complaints.metric.trend} lowerIsBetter compare="vs previous period" />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <ChartCard title="Ratings by Dimension" question="Which parts of the visit do patients rate lowest?" range={e.dimensions.range} className="xl:col-span-2">
          <BarChart data={e.dimensions.data} x="dimension" unit=" / 5" series={[{ key: 'score', label: 'This period' }, { key: 'previous', label: 'Previous period' }]} />
        </ChartCard>
        <NpsBar nps={e.nps} />
        <ChartCard title="Feedback Sentiment" question="How do patients feel overall?" range={e.sentiment.range} action={<AiLabel title="Sentiment is assigned by the feedback classifier">AI sentiment</AiLabel>}>
          <DonutChart data={e.sentiment.data} colors={SENTIMENT_COLORS} />
        </ChartCard>
        <ChartCard title="Feedback by Category" question="What are patients talking about?" range={e.categories.range} className="xl:col-span-2">
          <BarChart data={e.categories.data.map((c) => ({ ...c, category: humanize(c.category), other: c.total - c.negative }))} x="category" stacked horizontal
            series={[{ key: 'negative', label: 'Negative', color: 'var(--crit)' }, { key: 'other', label: 'Neutral or positive', color: 'var(--series-1)' }]} />
        </ChartCard>
        <ChartCard title="Satisfaction Trend" question="Is satisfaction improving week to week?" range={e.weekly.range} className="xl:col-span-2">
          <LineChart data={e.weekly.data} x="week" unit=" / 5" series={[{ key: 'satisfaction', label: 'Satisfaction' }]} />
        </ChartCard>
        <DashboardCard title="Recurring Issues" subtitle="Themes detected in negative feedback" action={<AiLabel>AI themes</AiLabel>} flush>
          {e.themes.length === 0 ? <p className="p-4 text-sm text-muted">No recurring negative themes in this period.</p> : (
            <ul className="divide-y">
              {e.themes.map((t) => (
                <li key={t.theme} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="min-w-0 flex-1"><p className="truncate text-sm">{t.theme}</p><p className="text-xs text-subtle">{humanize(t.category)}{t.high_urgency ? ` · ${t.high_urgency} high urgency` : ''}</p></div>
                  <span className="text-sm font-semibold tabular">{t.mentions}</span>
                </li>
              ))}
            </ul>
          )}
        </DashboardCard>
      </div>
    </div>
  )
}

function FeedbackList({ department }: { department: string }) {
  const [filters, setFilters] = useState({ sentiment: '', category: '' })
  const [page, setPage] = useState(1)
  const query = useGet<Paged<FeedbackRow>>('feedback', '/feedback', { ...filters, department_id: department, page, size: 8 })
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => { setFilters((f) => ({ ...f, [k]: e.target.value })); setPage(1) }
  return (
    <Card className="mt-4">
      <div className="flex flex-wrap items-center gap-3 border-b p-4">
        <div className="mr-auto"><h2 className="text-sm font-semibold">Patient Feedback</h2><p className="text-xs text-subtle">Each entry is classified automatically for sentiment, category, urgency and theme.</p></div>
        <Select aria-label="Sentiment" value={filters.sentiment} onChange={set('sentiment')} className="w-36"><option value="">Any sentiment</option><option value="positive">Positive</option><option value="neutral">Neutral</option><option value="negative">Negative</option></Select>
        <Select aria-label="Category" value={filters.category} onChange={set('category')} className="w-48"><option value="">Any category</option>{CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}</Select>
      </div>
      <Async query={query} what="patient feedback" empty={(d) => !d.items.length && <EmptyState title="No feedback matches these filters" />}>
        {(d) => (
          <>
            <ul className="divide-y">
              {d.items.map((f) => (
                <li key={f.id} className="grid gap-3 px-4 py-3.5 md:grid-cols-[1fr_17rem]">
                  <div>
                    <p className="text-sm">“{f.comment || 'No comment'}”</p>
                    <p className="mt-1 text-xs text-subtle">{f.overall} / 5 · {f.department ?? 'Hospital'} · {formatDate(f.created_at)}</p>
                  </div>
                  <dl className="grid grid-cols-[5.5rem_1fr] items-center gap-y-1 text-xs">
                    <dt className="text-subtle">Sentiment</dt><dd><StatusBadge status={f.sentiment} /></dd>
                    <dt className="text-subtle">Category</dt><dd>{humanize(f.category)}</dd>
                    <dt className="text-subtle">Urgency</dt><dd><StatusBadge status={f.urgency} /></dd>
                    <dt className="text-subtle">Detected theme</dt><dd>{f.theme}</dd>
                  </dl>
                </li>
              ))}
            </ul>
            <Pagination page={d.page} size={d.size} total={d.total} onChange={setPage} />
          </>
        )}
      </Async>
    </Card>
  )
}

export default function Experience() {
  const [days, setDays] = useState('30')
  const [department, setDepartment] = useState('')
  const departments = useDepartments()
  const query = useGet<ExperienceData>('experience', '/analytics/patient-experience', { days, department_id: department })
  return (
    <>
      <PageHeader title="Patient Experience" subtitle="Satisfaction, NPS and what patients are telling us."
        actions={<>
          <Select aria-label="Date range" value={days} onChange={(e) => setDays(e.target.value)} className="w-36"><option value="7">Last 7 days</option><option value="14">Last 14 days</option><option value="30">Last 30 days</option><option value="45">Last 45 days</option></Select>
          <Select aria-label="Department" value={department} onChange={(e) => setDepartment(e.target.value)} className="w-44"><option value="">All departments</option>{departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select>
        </>} />
      <Async query={query} what="patient experience" skeleton={<LoadingSkeleton variant="chart" />}>{(e) => <ExperienceCharts data={e} />}</Async>
      <FeedbackList department={department} />
    </>
  )
}
