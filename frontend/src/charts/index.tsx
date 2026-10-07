/**
 * Chart kit. Conventions (applied once here so every chart is consistent):
 *  - categorical colours come from --series-1..6 in fixed order, never cycled or reused for status
 *  - one y-axis per chart; recessive grid; 2px lines; rounded bar ends with a surface gap
 *  - every chart has a tooltip; a legend appears whenever there are two or more series
 */
import type { ReactNode } from 'react'
import {
  Area, AreaChart as RAreaChart, Bar, BarChart as RBarChart, CartesianGrid, Cell, Legend, Line,
  LineChart as RLineChart, Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart as RScatterChart, Tooltip,
  XAxis, YAxis, ZAxis,
} from 'recharts'
import { metricText, Trend } from '@/components/data'
import { Card, EmptyState } from '@/components/ui'
import { cn, humanize, num } from '@/lib/format'
import type { Metric } from '@/types'

export const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)']
/** Bed states are statuses, so they wear status colours rather than series colours. */
export const BED_COLORS: Record<string, string> = {
  occupied: 'var(--info)', available: 'var(--ok)', cleaning: 'var(--warn)', maintenance: 'var(--crit)', reserved: 'var(--series-6)',
}

export interface SeriesDef { key: string; label: string; color?: string }
type Row = Record<string, any>

// ----------------------------------------------------------------------------- card
/** Title + headline metric + trend + date range around any chart. */
export function ChartCard({ title, question, metric, range, children, className, height = 260, isEmpty, action }: {
  title: string
  /** The question this chart answers, shown under the title. */
  question?: string
  metric?: Metric
  range?: string
  children: ReactNode
  className?: string
  height?: number
  isEmpty?: boolean
  action?: ReactNode
}) {
  const value = metricText(metric)
  return (
    <Card className={cn('flex flex-col p-4', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          {question && <p className="mt-0.5 text-xs text-subtle">{question}</p>}
        </div>
        {action ?? (range && <span className="shrink-0 text-xs text-subtle">{range}</span>)}
      </div>
      {value && (
        <p className="mt-2 flex items-baseline gap-1.5">
          <span className="text-xl font-semibold tabular">{value}</span>
          <span className="text-xs text-muted">{metric?.unit}</span>
          <Trend value={metric?.trend} lowerIsBetter={metric?.lower_is_better} />
        </p>
      )}
      <div className="mt-3 min-w-0" style={{ height }}>
        {isEmpty ? <EmptyState title="No data for this period" body="Try a longer date range or a different filter." /> : children}
      </div>
    </Card>
  )
}

// ----------------------------------------------------------------------------- shared parts
function TooltipBox({ active, payload, label, unit }: { active?: boolean; payload?: any[]; label?: any; unit?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border bg-surface px-3 py-2 text-xs shadow-lg">
      {label !== undefined && <p className="mb-1 font-medium text-text">{label}</p>}
      {payload.map((p) => (
        <p key={p.dataKey ?? p.name} className="flex items-center gap-2 text-muted">
          <span className="size-2 rounded-sm" style={{ background: p.color ?? p.payload?.fill }} aria-hidden />
          <span>{p.name}</span>
          <span className="ml-auto pl-3 font-medium text-text tabular">{num(p.value, 1)}{unit}</span>
        </p>
      ))}
    </div>
  )
}

const axis = { tickLine: false, axisLine: false, tickMargin: 8, tick: { fontSize: 11, fill: 'var(--axis)' } } as const
const margin = { top: 6, right: 8, bottom: 0, left: -18 }
const legend = (series: SeriesDef[]) => series.length > 1 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ paddingTop: 8, fontSize: 12 }} />
const color = (s: SeriesDef, i: number) => s.color ?? SERIES[i % SERIES.length]

// ----------------------------------------------------------------------------- charts
export function LineChart({ data, x, series, unit }: { data: Row[]; x: string; series: SeriesDef[]; unit?: string }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <RLineChart data={data} margin={margin}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey={x} {...axis} minTickGap={18} />
        <YAxis {...axis} allowDecimals={false} />
        <Tooltip content={<TooltipBox unit={unit} />} cursor={{ stroke: 'var(--axis)', strokeDasharray: '3 3' }} />
        {legend(series)}
        {series.map((s, i) => (
          <Line key={s.key} dataKey={s.key} name={s.label} stroke={color(s, i)} strokeWidth={2} dot={false}
            activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2 }} connectNulls type="monotone" animationDuration={500} />
        ))}
      </RLineChart>
    </ResponsiveContainer>
  )
}

export function AreaChart({ data, x, series, unit, stacked }: { data: Row[]; x: string; series: SeriesDef[]; unit?: string; stacked?: boolean }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <RAreaChart data={data} margin={margin}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey={x} {...axis} minTickGap={18} />
        <YAxis {...axis} allowDecimals={false} />
        <Tooltip content={<TooltipBox unit={unit} />} cursor={{ stroke: 'var(--axis)', strokeDasharray: '3 3' }} />
        {legend(series)}
        {series.map((s, i) => (
          <Area key={s.key} dataKey={s.key} name={s.label} stackId={stacked ? 'a' : undefined} stroke={color(s, i)}
            fill={color(s, i)} fillOpacity={stacked ? 0.55 : 0.12} strokeWidth={2} type="monotone" animationDuration={500} />
        ))}
      </RAreaChart>
    </ResponsiveContainer>
  )
}

export function BarChart({ data, x, series, unit, stacked, horizontal }: {
  data: Row[]; x: string; series: SeriesDef[]; unit?: string; stacked?: boolean; horizontal?: boolean
}) {
  const last = series.length - 1
  return (
    <ResponsiveContainer width="100%" height="100%">
      <RBarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} barCategoryGap="22%" barGap={2}
        margin={horizontal ? { top: 0, right: 12, bottom: 0, left: 8 } : margin}>
        <CartesianGrid vertical={!!horizontal} horizontal={!horizontal} />
        {horizontal
          ? <><XAxis type="number" {...axis} /><YAxis type="category" dataKey={x} {...axis} width={118} interval={0} /></>
          : <>
            {/* Many categories: slant the labels so none collide or get dropped. */}
            <XAxis dataKey={x} {...axis} interval={0} {...(data.length > 5 ? { angle: -32, textAnchor: 'end' as const, height: 58, tickMargin: 4 } : {})}
              tickFormatter={(v) => (String(v).length > 13 ? `${String(v).slice(0, 12)}…` : v)} />
            <YAxis {...axis} allowDecimals={false} />
          </>}
        <Tooltip content={<TooltipBox unit={unit} />} cursor={{ fill: 'var(--surface-2)' }} />
        {legend(series)}
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={color(s, i)} stackId={stacked ? 'a' : undefined} maxBarSize={34}
            stroke="var(--surface)" strokeWidth={stacked ? 2 : 0} animationDuration={500}
            radius={stacked && i !== last ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} />
        ))}
      </RBarChart>
    </ResponsiveContainer>
  )
}

export function DonutChart({ data, colors }: { data: { name: string; value: number }[]; colors?: Record<string, string> }) {
  const total = data.reduce((sum, d) => sum + d.value, 0)
  return (
    <div className="flex h-full items-center gap-4">
      <div className="h-full min-w-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip content={<TooltipBox />} />
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="92%" paddingAngle={2}
              stroke="var(--surface)" strokeWidth={2} animationDuration={500}>
              {data.map((d, i) => <Cell key={d.name} fill={colors?.[d.name] ?? SERIES[i % SERIES.length]} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="w-40 shrink-0 space-y-1.5 text-xs">
        {data.map((d, i) => (
          <li key={d.name} className="flex items-center gap-2">
            <span className="size-2 rounded-sm" style={{ background: colors?.[d.name] ?? SERIES[i % SERIES.length] }} aria-hidden />
            <span className="truncate text-muted">{humanize(d.name)}</span>
            <span className="ml-auto font-medium tabular">{total ? Math.round((d.value / total) * 100) : 0}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ScatterChart({ data, x, y, xLabel, yLabel, name }: { data: Row[]; x: string; y: string; xLabel: string; yLabel: string; name: string }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <RScatterChart margin={{ top: 6, right: 12, bottom: 16, left: -6 }}>
        <CartesianGrid />
        <XAxis type="number" dataKey={x} name={xLabel} {...axis} label={{ value: xLabel, position: 'insideBottom', offset: -10, fontSize: 11, fill: 'var(--axis)' }} />
        <YAxis type="number" dataKey={y} name={yLabel} {...axis} label={{ value: yLabel, angle: -90, position: 'insideLeft', offset: 18, fontSize: 11, fill: 'var(--axis)' }} />
        <ZAxis range={[70, 70]} />
        <Tooltip cursor={{ strokeDasharray: '3 3' }} content={({ active, payload }) => {
          const p = payload?.[0]?.payload
          if (!active || !p) return null
          return (
            <div className="rounded-lg border bg-surface px-3 py-2 text-xs shadow-lg">
              <p className="font-medium">{p[name]}</p>
              <p className="text-muted">{xLabel}: <span className="font-medium text-text">{num(p[x], 1)}</span></p>
              <p className="text-muted">{yLabel}: <span className="font-medium text-text">{num(p[y], 1)}</span></p>
            </div>
          )
        }} />
        <Scatter data={data} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
      </RScatterChart>
    </ResponsiveContainer>
  )
}

// ----------------------------------------------------------------------------- heatmap
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const HEAT = ['var(--heat-0)', 'var(--heat-1)', 'var(--heat-2)', 'var(--heat-3)', 'var(--heat-4)', 'var(--heat-5)']

/** Weekday x hour grid. Magnitude uses one hue, light to dark; each cell has a text tooltip. */
export function Heatmap({ data, unit = 'patients / hour' }: { data: { weekday: number; hour: number; value: number }[]; unit?: string }) {
  const max = Math.max(1, ...data.map((d) => d.value))
  const hours = [...new Set(data.map((d) => d.hour))].sort((a, b) => a - b)
  const cell = new Map(data.map((d) => [`${d.weekday}-${d.hour}`, d.value]))
  return (
    <div className="flex h-full flex-col">
      <div className="grid flex-1 gap-[2px]" style={{ gridTemplateColumns: `2.25rem repeat(${hours.length}, minmax(0, 1fr))` }} role="img"
        aria-label={`Average ${unit} by weekday and hour. Busiest value ${num(max, 1)}.`}>
        {DAYS.map((day, d) => (
          <div key={day} className="contents">
            <span className="self-center text-[11px] text-subtle">{day}</span>
            {hours.map((h) => {
              const v = cell.get(`${d + 1}-${h}`) ?? 0
              return <div key={h} title={`${day} ${String(h).padStart(2, '0')}:00 · ${num(v, 1)} ${unit}`}
                className="min-h-4 rounded-[3px]" style={{ background: HEAT[v === 0 ? 0 : Math.min(5, 1 + Math.floor((v / max) * 4.999))] }} />
            })}
          </div>
        ))}
        <span />
        {hours.map((h) => <span key={h} className="pt-1 text-center text-[10px] text-subtle">{h % 3 === 0 ? h : ''}</span>)}
      </div>
      <div className="mt-2 flex items-center justify-end gap-1.5 text-[11px] text-subtle">
        <span>Fewer</span>
        {HEAT.map((c) => <span key={c} className="size-3 rounded-[3px]" style={{ background: c }} />)}
        <span>More ({num(max, 1)})</span>
      </div>
    </div>
  )
}
