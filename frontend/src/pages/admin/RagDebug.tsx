import { Check, FlaskConical, Play, X } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import Markdown from 'react-markdown'
import { Confidence, MetricCard, StatusBadge } from '@/components/data'
import { Badge, Button, Card, EmptyState, Input, PageHeader, Tabs } from '@/components/ui'
import { cn, humanize, num } from '@/lib/format'
import { post, useAction } from '@/services/queries'

interface Scored { chunk_id: number; document: string; section: string; kb: string; semantic: number; keyword_norm: number; hybrid: number; rerank: number; selected?: boolean; preview: string }
interface Trace {
  question: string; retrieval_query: string
  safety_classification: { category: string; personal: boolean; strict_rules: boolean }
  metadata_filter: Record<string, unknown>; weights: Record<string, number>
  providers: { embedding: string; reranker: string; llm: string; llm_called: boolean }
  retrieved: Scored[]; reranked: Scored[]; final_context: string | null; llm_response: string | null; final_answer: string
  citations: { index: number; document: string; section: string; page: number }[]; confidence: number; safety_flags: string[]; notes: string[]
}
interface Evaluation {
  k: number; cases: number; providers: Record<string, string>; note: string
  retrieval: Record<string, number | null>; generation: Record<string, number | null>; safety: Record<string, number | null>
  details: Record<string, any>[]
}
const EXAMPLES = ['What is hypertension?', 'Where is the radiology department?', 'Who won the football match?', 'I have severe chest pain and difficulty breathing.', 'Should I double my medication dose?']

function Stage({ n, title, aside, children }: { n: number; title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="flex size-6 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand tabular">{n}</span>
        <h2 className="text-sm font-semibold">{title}</h2>
        <div className="ml-auto">{aside}</div>
      </div>
      {children}
    </Card>
  )
}

function ScoreTable({ rows, showSelected }: { rows: Scored[]; showSelected?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead><tr className="border-b text-subtle">
          {['#', 'Document · section', 'KB', 'Semantic', 'Keyword', 'Hybrid', 'Rerank'].map((h) => <th key={h} scope="col" className="px-2 py-1.5 font-medium whitespace-nowrap">{h}</th>)}
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.chunk_id} className={cn('border-b last:border-0', showSelected && r.selected && 'bg-brand-soft/40')} title={r.preview}>
              <td className="px-2 py-1.5 tabular">{i + 1}</td>
              <td className="px-2 py-1.5"><span className="font-medium">{r.document}</span><span className="text-muted"> · {r.section || 'General'}</span>
                {showSelected && r.selected && <Badge tone="brand" className="ml-1.5">in context</Badge>}</td>
              <td className="px-2 py-1.5 capitalize">{r.kb}</td>
              {[r.semantic, r.keyword_norm, r.hybrid, r.rerank].map((v, j) => <td key={j} className="px-2 py-1.5 tabular">{v.toFixed(3)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TraceView({ t }: { t: Trace }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Stage n={1} title="Question and preprocessing">
          <dl className="space-y-2 text-sm">
            <div><dt className="text-xs text-subtle">User question</dt><dd>{t.question}</dd></div>
            <div><dt className="text-xs text-subtle">Retrieval query</dt><dd className="font-mono text-[13px]">{t.retrieval_query}</dd></div>
          </dl>
        </Stage>
        <Stage n={2} title="Safety classification" aside={<Badge tone={t.safety_classification.strict_rules ? 'warn' : 'ok'}>{t.safety_classification.strict_rules ? 'Strict rules' : 'Standard rules'}</Badge>}>
          <p className="font-mono text-sm font-semibold">{t.safety_classification.category}</p>
          <p className="mt-1 text-xs text-muted">{t.safety_classification.personal ? 'Asks about the user\'s own situation.' : 'General question.'} Metadata filter: {Object.entries(t.metadata_filter).map(([k, v]) => `${k}=${v ?? 'any'}`).join(', ')}</p>
          {t.notes.map((n) => <p key={n} className="mt-2 rounded-lg bg-warn-soft px-2.5 py-1.5 text-xs text-warn">{n}</p>)}
        </Stage>
      </div>
      <Stage n={3} title="Retrieved documents (hybrid search)" aside={<span className="text-xs text-subtle tabular">hybrid = {t.weights.alpha} × semantic + {t.weights.beta} × keyword · top {t.weights.top_k}</span>}>
        {t.retrieved.length ? <ScoreTable rows={t.retrieved} showSelected /> : <p className="text-sm text-muted">Retrieval was skipped for this question.</p>}
        <p className="mt-2 text-[11px] text-subtle">Embedding: {t.providers.embedding} (pgvector cosine) · Keyword: PostgreSQL full-text search</p>
      </Stage>
      <Stage n={4} title="Reranking" aside={<span className="text-xs text-subtle">{t.providers.reranker} · keeps top {t.weights.final_k}</span>}>
        {t.reranked.length ? <ScoreTable rows={t.reranked} /> : <p className="text-sm text-muted">No chunks passed the reranker and confidence gate, so nothing was sent to the LLM.</p>}
        <Confidence value={t.confidence} className="mt-3" />
        <p className="mt-1 text-[11px] text-subtle">Answers are refused below a confidence of {t.weights.min_confidence}.</p>
      </Stage>
      <div className="grid gap-4 lg:grid-cols-2">
        <Stage n={5} title="Final context sent to the LLM">
          {t.final_context ? <pre className="max-h-80 overflow-auto rounded-lg bg-surface-2 p-3 text-[11px] leading-relaxed whitespace-pre-wrap">{t.final_context}</pre>
            : <p className="text-sm text-muted">The LLM was not called.</p>}
        </Stage>
        <Stage n={6} title="LLM response" aside={<Badge>{t.providers.llm}</Badge>}>
          {t.llm_response ? <pre className="max-h-80 overflow-auto rounded-lg bg-surface-2 p-3 text-[11px] leading-relaxed whitespace-pre-wrap">{t.llm_response}</pre>
            : <p className="text-sm text-muted">No generation. A fixed safety or fallback response was returned.</p>}
        </Stage>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Stage n={7} title="Citations">
          {t.citations.length ? <ul className="space-y-1.5 text-sm">{t.citations.map((c) => <li key={c.index}><span className="mr-2 rounded bg-brand-soft px-1.5 text-xs font-semibold text-brand tabular">{c.index}</span>{c.document} · {c.section} · page {c.page}</li>)}</ul>
            : <p className="text-sm text-muted">No citations in the final answer.</p>}
        </Stage>
        <Stage n={8} title="Safety validation and final answer" aside={t.safety_flags.length ? <Badge tone="warn">{t.safety_flags.map(humanize).join(', ')}</Badge> : <Badge tone="ok" icon={Check}>No flags</Badge>}>
          <div className="prose-chat rounded-lg border p-3"><Markdown>{t.final_answer}</Markdown></div>
        </Stage>
      </div>
    </div>
  )
}

function EvaluationView({ e }: { e: Evaluation }) {
  const metric = (label: string, v: number | null | undefined, invert?: boolean) => (
    <MetricCard key={label} label={label} value={v === null || v === undefined ? '—' : num(v, 3)} tone={v === null || v === undefined ? 'neutral' : (invert ? v <= 0.05 : v >= 0.85) ? 'ok' : 'warn'} />
  )
  return (
    <div className="space-y-5">
      <p className="text-xs text-muted">{e.cases} cases · k = {e.k} · {Object.entries(e.providers).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
      {([['Retrieval', e.retrieval], ['Generation', e.generation], ['Safety', e.safety]] as const).map(([title, group]) => (
        <section key={title}>
          <h2 className="mb-2 text-sm font-semibold">{title} <span className="font-normal text-subtle">({group.cases} cases)</span></h2>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Object.entries(group).filter(([k]) => k !== 'cases').map(([k, v]) => metric(humanize(k), v, k === 'hallucination_rate'))}
          </div>
        </section>
      ))}
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Per-question evaluation results</caption>
            <thead><tr className="border-b text-subtle">{['Question', 'Type', 'Category', 'Top source', 'MRR', 'Grounded', 'Safety'].map((h) => <th key={h} scope="col" className="px-3 py-2 font-medium whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {e.details.map((d) => (
                <tr key={d.question} className="border-b last:border-0">
                  <td className="max-w-xs px-3 py-2">{d.question}</td>
                  <td className="px-3 py-2">{humanize(d.type)}</td>
                  <td className="px-3 py-2 font-mono text-[11px]">{d.safety_category}</td>
                  <td className="px-3 py-2 text-muted">{d.top_source ?? '—'}</td>
                  <td className="px-3 py-2 tabular">{d.mrr ?? '—'}</td>
                  <td className="px-3 py-2 tabular">{d.groundedness ?? '—'}</td>
                  <td className="px-3 py-2">{d.safety_pass === undefined ? '—' : d.safety_pass ? <Check className="size-4 text-ok" aria-label="Pass" /> : <X className="size-4 text-crit" aria-label="Fail" />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="text-[11px] text-subtle">{e.note}</p>
    </div>
  )
}

export default function RagDebug() {
  const [tab, setTab] = useState<'trace' | 'evaluation'>('trace')
  const [question, setQuestion] = useState('')
  const trace = useAction((q: string) => post<Trace>('/rag/debug', { question: q }))
  const evaluation = useAction(() => post<Evaluation>('/rag/evaluate'))
  const run = (q: string) => { if (q.trim().length >= 2) { setQuestion(q); trace.mutate(q.trim()) } }
  return (
    <>
      <PageHeader title="RAG Debugger" subtitle="Inspect every stage of the retrieval-augmented pipeline for a question, or run the evaluation set." />
      <Tabs label="RAG tools" value={tab} onChange={setTab} tabs={[{ id: 'trace', label: 'Pipeline trace' }, { id: 'evaluation', label: 'Evaluation' }]} />
      {tab === 'trace' ? (
        <>
          <Card className="mb-4 p-4">
            <form onSubmit={(e) => { e.preventDefault(); run(question) }} className="flex gap-2">
              <Input aria-label="Question to trace" value={question} maxLength={500} onChange={(e) => setQuestion(e.target.value)} placeholder="Type a question to trace through the pipeline" className="flex-1" />
              <Button type="submit" variant="primary" icon={Play} loading={trace.isPending} disabled={question.trim().length < 2}>Run</Button>
            </form>
            <div className="mt-3 flex flex-wrap gap-1.5">{EXAMPLES.map((q) => <button key={q} onClick={() => run(q)} className="rounded-full border px-3 py-1 text-xs text-muted hover:border-brand hover:text-brand">{q}</button>)}</div>
          </Card>
          {trace.data ? <TraceView t={trace.data} /> : !trace.isPending && <Card><EmptyState icon={FlaskConical} title="Run a question to see the pipeline" body="You'll see the safety class, every retrieved chunk with its semantic, keyword, hybrid and rerank scores, the exact context sent to the LLM, and the validated answer." /></Card>}
        </>
      ) : (
        <>
          <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
            <div className="mr-auto"><h2 className="text-sm font-semibold">Evaluation set</h2><p className="text-xs text-muted">24 questions covering retrieval, navigation, out-of-domain, insufficient evidence, emergencies, diagnosis and dosing.</p></div>
            {evaluation.data && <StatusBadge status={evaluation.data.safety.pass_rate === 1 ? 'success' : 'failure'} />}
            <Button variant="primary" icon={Play} loading={evaluation.isPending} onClick={() => evaluation.mutate()}>Run evaluation</Button>
          </Card>
          {evaluation.data ? <EvaluationView e={evaluation.data} /> : !evaluation.isPending && <Card><EmptyState icon={FlaskConical} title="No evaluation run yet" body="Reports Recall@K, Precision@K, MRR, NDCG, groundedness, citation correctness, answer relevance and hallucination rate." /></Card>}
        </>
      )}
    </>
  )
}
