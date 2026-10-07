import { ArrowUp, ChevronDown, Database, RefreshCw, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { useSearchParams } from 'react-router'
import { AIInsightCard, AiLabel } from '@/components/cards'
import { Async, Badge, Button, Card, EmptyState, LoadingSkeleton, PageHeader, Tabs } from '@/components/ui'
import { BarChart, LineChart } from '@/charts'
import { useAuth } from '@/hooks/useAuth'
import { ApiError } from '@/lib/api'
import { humanize, num } from '@/lib/format'
import { post, useAction, useGet } from '@/services/queries'
import type { CopilotResult, Insight } from '@/types'
import { type Predictions, PredictionsView } from './Analytics'

interface Turn { id: number; question: string; result?: CopilotResult; error?: string }

function ResultTable({ rows }: { rows: Record<string, any>[] }) {
  if (!rows.length) return <p className="text-xs text-muted">The query returned no rows.</p>
  const columns = Object.keys(rows[0])
  return (
    <div className="max-h-56 overflow-auto rounded-lg border">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-surface-2"><tr>{columns.map((c) => <th key={c} scope="col" className="px-2.5 py-1.5 font-medium whitespace-nowrap">{humanize(c)}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 50).map((r, i) => <tr key={i} className="border-t">{columns.map((c) => <td key={c} className="px-2.5 py-1.5 whitespace-nowrap tabular">{typeof r[c] === 'number' ? num(r[c], 2) : String(r[c] ?? '—')}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

function CopilotAnswer({ result: r }: { result: CopilotResult }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-3">
      <div className="prose-chat"><Markdown>{r.answer}</Markdown></div>
      {r.chart && r.data.length > 0 && (
        <div className="h-56 rounded-lg border p-3">
          {r.chart.type === 'line' ? <LineChart data={r.data} x={r.chart.x} series={r.chart.series} /> : <BarChart data={r.data.slice(0, 12)} x={r.chart.x} series={r.chart.series} />}
        </div>
      )}
      {r.queries.length > 0 ? (
        <div>
          <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex items-center gap-1.5 text-xs font-medium text-brand hover:underline">
            <Database className="size-3.5" aria-hidden />{open ? 'Hide' : 'Show'} underlying data ({r.queries.length} {r.queries.length === 1 ? 'query' : 'queries'})
            <ChevronDown className={`size-3.5 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
          </button>
          {open && (
            <div className="mt-2 space-y-3">
              {r.queries.map((q) => (
                <div key={q.title} className="space-y-1.5">
                  <p className="text-xs font-medium">{q.title}</p>
                  <pre className="max-h-40 overflow-auto rounded-lg bg-surface-2 p-2.5 text-[11px] leading-relaxed"><code>{q.sql}</code></pre>
                  {Object.keys(q.params).length > 0 && <p className="text-[11px] text-subtle">Parameters: {Object.entries(q.params).map(([k, v]) => `${k} = ${v}`).join(' · ')}</p>}
                  <ResultTable rows={q.rows} />
                </div>
              ))}
              <p className="text-[11px] text-subtle">Validated as a single SELECT and run by a read-only database role with no access to names, contact details or clinical notes.</p>
            </div>
          )}
        </div>
      ) : r.mode === 'forecast_model' && <p className="text-[11px] text-subtle">Source: the patient-volume forecasting model (seasonal average with recent trend), not a SQL query.</p>}
      <p className="text-[11px] text-subtle">{r.note}</p>
    </div>
  )
}

function Copilot() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  const suggestions = useGet<string[]>('copilot-suggestions', '/ai/copilot/suggestions', undefined, { staleTime: Infinity })
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [turns])

  const ask = async (text: string) => {
    const question = text.trim()
    if (question.length < 2 || busy) return
    const id = Date.now()
    setInput(''); setBusy(true)
    setTurns((t) => [...t, { id, question }])
    try {
      const result = await post<CopilotResult>('/ai/copilot', { question })
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, result } : x)))
    } catch (err) {
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, error: err instanceof ApiError ? err.message : "I couldn't answer that. Please try again." } : x)))
    } finally { setBusy(false) }
  }

  return (
    <Card className="flex min-h-[28rem] flex-col">
      <div className="flex items-center gap-3 border-b p-4">
        <span aria-hidden className="flex size-9 items-center justify-center rounded-full bg-brand-soft text-brand"><Sparkles className="size-[18px]" /></span>
        <div><h2 className="text-sm font-semibold">Operations Copilot</h2><p className="text-xs text-muted">Ask about waits, load, staffing, complaints, beds or forecasts. Answers come from live hospital data.</p></div>
      </div>
      <div className="flex-1 space-y-6 p-4">
        {turns.length === 0 ? (
          <div className="py-4">
            <EmptyState icon={Sparkles} title="Ask a question about hospital operations" body="The copilot detects what you're asking, runs a validated read-only query, and explains the result with the data it used." />
            <div className="mx-auto flex max-w-2xl flex-wrap justify-center gap-2">
              {suggestions.data?.map((q) => <button key={q} onClick={() => ask(q)} className="rounded-full border px-3.5 py-1.5 text-sm text-muted hover:border-brand hover:text-brand">{q}</button>)}
            </div>
          </div>
        ) : turns.map((t) => (
          <div key={t.id} className="space-y-3">
            <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2 text-sm text-on-brand">{t.question}</p>
            <div className="max-w-3xl">
              {t.error ? <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2 text-sm text-crit">{t.error}</p>
                : t.result ? <CopilotAnswer result={t.result} /> : <p className="text-sm text-muted">Analysing hospital data…</p>}
            </div>
          </div>
        ))}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(input) }} className="flex gap-2 border-t p-3">
        <label htmlFor="copilot-input" className="sr-only">Ask the Operations Copilot</label>
        <input id="copilot-input" value={input} maxLength={500} onChange={(e) => setInput(e.target.value)} placeholder="e.g. Which department had the highest average waiting time this month?"
          className="h-10 flex-1 rounded-lg border bg-bg px-3 text-sm placeholder:text-subtle" />
        <Button type="submit" variant="primary" icon={ArrowUp} loading={busy} disabled={input.trim().length < 2}>Ask</Button>
      </form>
    </Card>
  )
}

export default function AIInsights() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') ?? 'insights') as 'insights' | 'copilot' | 'predictions'
  const insights = useGet<Insight[]>('insights', '/ai/insights')
  const predictions = useGet<Predictions>('predictions', '/ai/predictions', undefined, { enabled: tab === 'predictions' })
  const refresh = useAction(() => post('/ai/insights/refresh'), { invalidate: ['insights', 'overview', 'notifications'], success: 'Insights recomputed from current data' })
  const dismiss = useAction((id: number) => post(`/ai/insights/${id}/dismiss`), { invalidate: ['insights', 'overview'], success: 'Insight dismissed' })
  const tabs = [{ id: 'insights' as const, label: 'Operational insights' }, ...(can('copilot:use') ? [{ id: 'copilot' as const, label: 'Operations Copilot' }] : []), { id: 'predictions' as const, label: 'Predictions' }]

  return (
    <>
      <PageHeader title="AI Insights" subtitle="Detected patterns, explained predictions, and a copilot for hospital data."
        actions={tab === 'insights' && <Button icon={RefreshCw} onClick={() => refresh.mutate()} loading={refresh.isPending}>Recompute</Button>} />
      <Tabs label="AI" tabs={tabs} value={tab} onChange={(t) => setParams(t === 'insights' ? {} : { tab: t }, { replace: true })} />
      {tab === 'insights' && (
        <>
          <p className="mb-4 flex flex-wrap items-center gap-2 text-sm text-muted">
            <AiLabel /> Insights are recommendations for a person to review. MedFlow never changes staffing, beds or care on its own.
          </p>
          <Async query={insights} what="AI insights" skeleton={<LoadingSkeleton rows={4} />}
            empty={(d) => !d.length && <Card><EmptyState icon={Sparkles} title="No active insights" body="The detectors found nothing unusual in current operations." /></Card>}>
            {(items) => (
              <>
                <div className="mb-3 flex gap-2">{(['critical', 'high', 'medium', 'low'] as const).map((s) => {
                  const n = items.filter((i) => i.severity === s).length
                  return n > 0 && <Badge key={s} tone={s === 'medium' ? 'warn' : s === 'low' ? 'info' : 'crit'}>{n} {s}</Badge>
                })}</div>
                <div className="grid gap-4 xl:grid-cols-2">{items.map((i) => <AIInsightCard key={i.id} insight={i} onDismiss={() => dismiss.mutate(i.id)} />)}</div>
              </>
            )}
          </Async>
        </>
      )}
      {tab === 'copilot' && can('copilot:use') && <Copilot />}
      {tab === 'predictions' && <Async query={predictions} what="predictions" skeleton={<LoadingSkeleton variant="cards" rows={4} />}>{(p) => <PredictionsView data={p} />}</Async>}
    </>
  )
}
