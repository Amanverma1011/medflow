/** Chat building blocks: message bubble, citation cards and the evidence panel. */
import { motion } from 'framer-motion'
import { BookOpen, Building2, Check, Copy, FileText, RefreshCw, ShieldAlert, Sparkles, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import Markdown from 'react-markdown'
import { Confidence } from '@/components/data'
import { Badge, EmptyState, LoadingSkeleton, type Tone } from '@/components/ui'
import { cn, formatDate, humanize } from '@/lib/format'
import { useGet } from '@/services/queries'
import type { ChatMessage as Message, Source } from '@/types'

const SCOPE = {
  medical: { label: 'Medical Information', icon: BookOpen, tone: 'info' as Tone },
  hospital: { label: 'Hospital Information', icon: Building2, tone: 'brand' as Tone },
}
const STRICT = new Set(['EMERGENCY', 'SELF_HARM', 'HIGH_RISK', 'DIAGNOSIS_REQUEST', 'TREATMENT_REQUEST'])

export function ScopeBadge({ scope }: { scope: string | null | undefined }) {
  const s = SCOPE[scope as keyof typeof SCOPE]
  return s ? <Badge tone={s.tone} icon={s.icon}>{s.label}</Badge> : null
}

// ----------------------------------------------------------------------------- citations
export function CitationCard({ source, active, onSelect }: { source: Source; active?: boolean; onSelect: () => void }) {
  return (
    <button onClick={onSelect} aria-pressed={active}
      className={cn('flex w-full items-start gap-2.5 rounded-lg border p-2.5 text-left transition-colors hover:bg-surface-2', active && 'border-brand bg-brand-soft/50')}>
      <span className="flex size-5 shrink-0 items-center justify-center rounded bg-surface-2 text-[11px] font-semibold tabular">{source.index}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{source.document}</span>
        <span className="block truncate text-xs text-muted">{source.section || 'General'} · Page {source.page}</span>
      </span>
      {!source.cited && <span className="text-[10px] text-subtle" title="Retrieved as context but not quoted in the answer">context</span>}
    </button>
  )
}

/** Right-hand evidence panel: the exact passage behind a citation, plus how it was retrieved. */
export function SourcePanel({ source, sources, onSelect }: { source: Source | null; sources: Source[]; onSelect: (s: Source) => void }) {
  const detail = useGet<{ content: string; section: string; page: number; document: { name: string; kb: string; source_type: string; version: string; uploaded_at: string } }>(
    'rag-source', `/rag/sources/${source?.chunk_id}`, undefined, { enabled: !!source, staleTime: Infinity, placeholderData: undefined })
  if (!sources.length) {
    return <EmptyState icon={FileText} title="Evidence appears here" body="When the assistant answers from the knowledge base, the passages it used are listed here." />
  }
  return (
    <div className="space-y-4">
      <div>
        <p className="mb-2 text-xs font-medium text-muted">Retrieved for this answer</p>
        <div className="space-y-1.5">
          {sources.map((s) => <CitationCard key={s.chunk_id} source={s} active={s.chunk_id === source?.chunk_id} onSelect={() => onSelect(s)} />)}
        </div>
      </div>
      {source && (
        <div className="rounded-lg border">
          <div className="border-b p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <ScopeBadge scope={source.kb} />
              <Badge>v{source.version}</Badge>
            </div>
            <p className="mt-2 text-sm font-semibold">{source.document}</p>
            <p className="text-xs text-muted">{source.section || 'General'} · Page {source.page}</p>
          </div>
          <div className="p-3">
            {detail.isLoading ? <LoadingSkeleton rows={3} />
              : detail.error ? <p className="text-sm text-muted">This source is no longer available.</p>
                : <p className="text-[13px] leading-relaxed whitespace-pre-line text-muted">{detail.data?.content}</p>}
          </div>
          <dl className="grid grid-cols-3 divide-x border-t text-center text-xs">
            {[['Relevance', source.score], ['Semantic', source.semantic], ['Keyword', source.keyword]].map(([label, value]) => (
              <div key={label as string} className="py-2">
                <dt className="text-subtle">{label}</dt>
                <dd className="font-medium tabular">{(value as number).toFixed(2)}</dd>
              </div>
            ))}
          </dl>
          {detail.data && (
            <p className="border-t px-3 py-2 text-[11px] text-subtle">
              {humanize(detail.data.document.source_type)} · added {formatDate(detail.data.document.uploaded_at)}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ----------------------------------------------------------------------------- message
interface MessageProps {
  message: Message
  activeChunk?: number
  onSelectSource: (s: Source) => void
  onFeedback?: (value: number) => void
  onRegenerate?: () => void
  onFollowUp?: (question: string) => void
  onViewSources?: () => void
}

export function ChatMessage({ message: m, activeChunk, onSelectSource, onFeedback, onRegenerate, onFollowUp, onViewSources }: MessageProps) {
  const [copied, setCopied] = useState(false)
  if (m.role === 'user') {
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[15px] whitespace-pre-wrap text-on-brand">{m.content}</p>
      </motion.div>
    )
  }
  const sources = m.sources ?? []
  const cited = sources.filter((s) => s.cited)
  const urgent = m.safety_category === 'EMERGENCY' || m.safety_category === 'SELF_HARM'
  const copy = async () => {
    await navigator.clipboard?.writeText(m.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  // Turn "[2]" into a link the renderer below swaps for a citation chip.
  const text = m.content.replace(/\[(\d+)\]/g, (_, n) => (sources.some((s) => s.index === +n) ? `[${n}](#cite-${n})` : ''))

  return (
    <motion.article initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3" aria-label="Assistant message">
      <span aria-hidden className={cn('mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full', urgent ? 'bg-crit-soft text-crit' : 'bg-brand-soft text-brand')}>
        {urgent ? <ShieldAlert className="size-4" /> : <Sparkles className="size-4" />}
      </span>
      <div className="min-w-0 flex-1">
        {(m.knowledge_scope && m.knowledge_scope !== 'none' || (m.safety_category && STRICT.has(m.safety_category))) && (
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <ScopeBadge scope={m.knowledge_scope} />
            {m.safety_category && STRICT.has(m.safety_category) && (
              <Badge tone={urgent ? 'crit' : 'warn'} icon={ShieldAlert}>{urgent ? 'Urgent' : 'Safety guidance applied'}</Badge>
            )}
          </div>
        )}
        <div className={cn('prose-chat', urgent && 'rounded-xl border border-crit/40 bg-crit-soft/40 p-3.5')}>
          {m.content
            ? <Markdown components={{
                a: ({ href, children }) => {
                  const n = /^#cite-(\d+)$/.exec(href ?? '')?.[1]
                  const source = n ? sources.find((s) => s.index === +n) : undefined
                  if (!source) return <span>{children}</span>
                  return (
                    <button onClick={() => onSelectSource(source)} title={`${source.document} · ${source.section}`}
                      aria-label={`Source ${n}: ${source.document}`}
                      className={cn('mx-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded px-1 align-[1px] text-[11px] font-semibold tabular',
                        source.chunk_id === activeChunk ? 'bg-brand text-on-brand' : 'bg-brand-soft text-brand hover:bg-brand hover:text-on-brand')}>
                      {n}
                    </button>
                  )
                },
              }}>{text}</Markdown>
            : <p className="flex items-center gap-2 text-muted"><span className="flex gap-1" aria-hidden>
                {[0, 1, 2].map((i) => <motion.span key={i} className="size-1.5 rounded-full bg-subtle" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ repeat: Infinity, duration: 1.1, delay: i * 0.18 }} />)}
              </span>AI is thinking…</p>}
          {m.streaming && m.content && <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-brand align-middle" aria-hidden />}
        </div>

        {!m.streaming && cited.length > 0 && (
          <div className="mt-3 border-t pt-3">
            <p className="mb-2 text-xs font-medium text-muted">Sources</p>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {cited.map((s) => <CitationCard key={s.chunk_id} source={s} active={s.chunk_id === activeChunk} onSelect={() => onSelectSource(s)} />)}
            </div>
          </div>
        )}

        {!m.streaming && !m.failed && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1 text-subtle">
            {onFeedback && typeof m.id === 'number' && <>
              <IconButton label="Helpful" active={m.feedback === 1} onClick={() => onFeedback(m.feedback === 1 ? 0 : 1)}><ThumbsUp className="size-3.5" /></IconButton>
              <IconButton label="Not helpful" active={m.feedback === -1} onClick={() => onFeedback(m.feedback === -1 ? 0 : -1)}><ThumbsDown className="size-3.5" /></IconButton>
            </>}
            <IconButton label={copied ? 'Copied' : 'Copy answer'} onClick={copy}>{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}</IconButton>
            {onRegenerate && <IconButton label="Regenerate" onClick={onRegenerate}><RefreshCw className="size-3.5" /></IconButton>}
            {sources.length > 0 && onViewSources && (
              <button onClick={onViewSources} className="ml-1 rounded-md px-2 py-1 text-xs font-medium text-brand hover:bg-brand-soft xl:hidden">View sources ({sources.length})</button>
            )}
            {typeof m.confidence === 'number' && sources.length > 0 && <Confidence value={m.confidence} className="ml-auto" />}
          </div>
        )}

        {!m.streaming && !!m.follow_ups?.length && onFollowUp && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {m.follow_ups.map((q) => (
              <button key={q} onClick={() => onFollowUp(q)} className="rounded-full border px-3 py-1 text-left text-xs text-muted hover:border-brand hover:text-brand">{q}</button>
            ))}
          </div>
        )}
      </div>
    </motion.article>
  )
}

function IconButton({ label, active, onClick, children }: { label: string; active?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} aria-label={label} title={label} aria-pressed={active}
      className={cn('flex size-7 items-center justify-center rounded-md hover:bg-surface-2 hover:text-text', active && 'bg-brand-soft text-brand')}>
      {children}
    </button>
  )
}
