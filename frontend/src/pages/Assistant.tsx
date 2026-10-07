/** Medical Assistant: conversation history · chat · evidence panel. */
import { useQueryClient } from '@tanstack/react-query'
import { ArrowUp, History, MessageSquarePlus, Phone, ShieldCheck, Sparkles, Square, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { ChatMessage, SourcePanel } from '@/components/chat/ChatParts'
import { Badge, Button, ConfirmDialog, EmptyState, LoadingSkeleton, Modal } from '@/components/ui'
import { useToast } from '@/hooks/useUi'
import { api, ApiError, streamSse } from '@/lib/api'
import { cn, timeAgo } from '@/lib/format'
import { del, post, useAction, useGet } from '@/services/queries'
import type { ChatMessage as Message, Source } from '@/types'

interface Status { llm_demo: boolean; embedding_demo: boolean; documents: number; suggestions: string[]; disclaimer: string; emergency_notice: string }
interface Conversation { id: number; title: string; updated_at: string }

export default function Assistant() {
  const [messages, setMessages] = useState<Message[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Source | null>(null)
  const [panelSources, setPanelSources] = useState<Source[]>([])
  const [mobilePanel, setMobilePanel] = useState<'history' | 'sources' | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Conversation | null>(null)
  const abort = useRef<AbortController | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()

  const status = useGet<Status>('rag-status', '/rag/status', undefined, { staleTime: 60_000 })
  const history = useGet<Conversation[]>('conversations', '/rag/conversations')
  const remove = useAction((id: number) => del(`/rag/conversations/${id}`), {
    invalidate: ['conversations'], success: 'Conversation deleted',
    onSuccess: (_, id) => { if (id === conversationId) reset() },
  })

  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' }) }, [messages])
  useEffect(() => () => abort.current?.abort(), [])

  // Deep link from global search: /chat?source=<chunk id> opens that passage in the evidence panel.
  useEffect(() => {
    const chunk = Number(params.get('source'))
    if (!chunk) return
    api<{ chunk_id: number; section: string; page: number; document: { id: number; name: string; kb: 'medical' | 'hospital'; version: string } }>(`/rag/sources/${chunk}`)
      .then((s) => {
        const source: Source = { index: 1, chunk_id: s.chunk_id, document_id: s.document.id, document: s.document.name, section: s.section,
          page: s.page, kb: s.document.kb, version: s.document.version, score: 0, semantic: 0, keyword: 0, snippet: '', cited: true }
        setPanelSources([source]); setSelected(source); setMobilePanel('sources')
      }).catch(() => {})
    setParams({}, { replace: true })
  }, [params, setParams])

  const reset = useCallback(() => {
    abort.current?.abort()
    setMessages([]); setConversationId(null); setSelected(null); setPanelSources([]); setBusy(false)
  }, [])

  const showSources = (sources: Source[], pick?: Source) => {
    setPanelSources(sources)
    setSelected(pick ?? sources.find((s) => s.cited) ?? sources[0] ?? null)
  }

  const openConversation = async (c: Conversation) => {
    setMobilePanel(null)
    try {
      const data = await api<{ messages: Message[] }>(`/rag/conversations/${c.id}`)
      abort.current?.abort()
      setConversationId(c.id); setMessages(data.messages); setBusy(false)
      const last = [...data.messages].reverse().find((m) => m.role === 'assistant')
      showSources(last?.sources ?? [])
    } catch (err) { toast.error(err) }
  }

  const send = useCallback(async (text: string) => {
    const question = text.trim()
    if (!question || busy) return
    setInput(''); setBusy(true)
    const pending = `pending-${Date.now()}`
    setMessages((m) => [...m, { id: `${pending}-q`, role: 'user', content: question },
      { id: pending, role: 'assistant', content: '', streaming: true }])
    const update = (patch: Partial<Message> | ((m: Message) => Partial<Message>)) =>
      setMessages((all) => all.map((m) => (m.id === pending ? { ...m, ...(typeof patch === 'function' ? patch(m) : patch) } : m)))
    abort.current = new AbortController()
    try {
      for await (const { event, data } of streamSse('/rag/chat/stream', { message: question, conversation_id: conversationId }, abort.current.signal)) {
        if (event === 'meta') {
          setConversationId(data.conversation_id)
          update({ safety_category: data.safety_category, knowledge_scope: data.knowledge_scope })
        } else if (event === 'token') {
          update((m) => ({ content: m.content + data.t }))
        } else if (event === 'done') {
          // The final event carries the safety-validated answer, which replaces what was streamed.
          update({ id: data.message_id, content: data.answer, sources: data.sources, confidence: data.confidence,
            safety_category: data.safety_category, knowledge_scope: data.knowledge_scope, follow_ups: data.follow_ups, streaming: false })
          showSources(data.sources)
          queryClient.invalidateQueries({ queryKey: ['conversations'] })
        } else if (event === 'error') {
          throw new ApiError(502, 'ai_unavailable', data.message)
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') update((m) => ({ streaming: false, content: m.content || 'Stopped.' }))
      else update({ streaming: false, failed: true, content: err instanceof ApiError ? err.message : "Something went wrong and I couldn't answer. Please try again." })
    } finally {
      setBusy(false)
    }
  }, [busy, conversationId, queryClient])

  // A suggestion chip on the patient home screen hands a question over via navigation state.
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => {
    const ask = (location.state as { ask?: string } | null)?.ask
    if (!ask) return
    navigate(location.pathname, { replace: true, state: null })
    send(ask)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state])

  const sendFeedback = (id: number, value: number) => {
    setMessages((all) => all.map((m) => (m.id === id ? { ...m, feedback: value } : m)))
    post(`/rag/messages/${id}/feedback`, { value }).catch((err) => toast.error(err))
  }
  const regenerate = (index: number) => {
    const question = messages.slice(0, index).reverse().find((m) => m.role === 'user')?.content
    if (question) send(question)
  }

  const historyList = (
    <div className="flex h-full flex-col">
      <div className="p-3">
        <Button variant="primary" icon={MessageSquarePlus} className="w-full" onClick={() => { reset(); setMobilePanel(null) }}>New conversation</Button>
      </div>
      <p className="px-4 pb-1.5 text-[11px] font-medium text-subtle uppercase">History</p>
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {history.isLoading ? <div className="p-2"><LoadingSkeleton rows={4} /></div>
          : !history.data?.length ? <p className="px-2 py-6 text-center text-sm text-muted">No conversations yet.</p>
            : history.data.map((c) => (
              <div key={c.id} className={cn('group flex items-center rounded-lg hover:bg-surface-2', c.id === conversationId && 'bg-surface-2')}>
                <button onClick={() => openConversation(c)} className="min-w-0 flex-1 px-2.5 py-2 text-left">
                  <span className="block truncate text-sm">{c.title}</span>
                  <span className="block text-[11px] text-subtle">{timeAgo(c.updated_at)}</span>
                </button>
                <button onClick={() => setConfirmDelete(c)} aria-label={`Delete conversation: ${c.title}`}
                  className="mr-1 rounded-md p-1.5 text-subtle opacity-0 group-hover:opacity-100 hover:text-crit focus-visible:opacity-100">
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))}
      </div>
    </div>
  )
  const evidence = <SourcePanel source={selected} sources={panelSources} onSelect={setSelected} />

  return (
    <div className="-m-4 flex h-[calc(100dvh-var(--chrome))] sm:-m-6">
      <aside className="hidden w-64 shrink-0 border-r bg-surface lg:block" aria-label="Conversation history">{historyList}</aside>

      <section className="flex min-w-0 flex-1 flex-col" aria-label="Chat">
        <header className="flex items-center gap-3 border-b bg-surface px-4 py-3">
          <span aria-hidden className="flex size-9 items-center justify-center rounded-full bg-brand-soft text-brand"><Sparkles className="size-[18px]" /></span>
          <div className="min-w-0 flex-1">
            <h1 className="text-[15px] font-semibold">Medical Assistant</h1>
            <p className="truncate text-xs text-muted">Evidence-grounded · Hospital Knowledge{status.data ? ` · ${status.data.documents} approved documents` : ''}</p>
          </div>
          {status.data?.llm_demo && (
            <Badge tone="warn"><span title="No LLM key is configured. Answers are composed only from sentences in the retrieved passages; retrieval, reranking, citations and safety checks are fully live.">Demo mode · extractive answers</span></Badge>
          )}
          <Button size="sm" variant="ghost" icon={History} className="lg:hidden" onClick={() => setMobilePanel('history')} aria-label="Conversation history" />
          {messages.length > 0 && <Button size="sm" variant="ghost" onClick={reset}>Clear</Button>}
        </header>

        <div ref={scroller} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
            {messages.length === 0 ? (
              <div className="pt-6 sm:pt-12">
                <EmptyState icon={Sparkles} title="Ask the Medical Assistant" body="Get evidence-grounded information from approved hospital resources." />
                <div className="mx-auto flex max-w-xl flex-wrap justify-center gap-2">
                  {(status.data?.suggestions ?? []).map((q) => (
                    <button key={q} onClick={() => send(q)} className="rounded-full border bg-surface px-3.5 py-1.5 text-sm text-muted hover:border-brand hover:text-brand">{q}</button>
                  ))}
                </div>
              </div>
            ) : messages.map((m, i) => (
              <ChatMessage key={m.id} message={m} activeChunk={selected?.chunk_id}
                onSelectSource={(s) => { showSources(m.sources ?? [], s); setMobilePanel('sources') }}
                onViewSources={() => { showSources(m.sources ?? []); setMobilePanel('sources') }}
                onFeedback={typeof m.id === 'number' ? (v) => sendFeedback(m.id as number, v) : undefined}
                onRegenerate={!busy && i === messages.length - 1 ? () => regenerate(i) : undefined}
                onFollowUp={!busy && i === messages.length - 1 ? send : undefined} />
            ))}
          </div>
        </div>

        <div className="border-t bg-surface px-4 pt-3 pb-3">
          <form className="mx-auto max-w-3xl" onSubmit={(e) => { e.preventDefault(); send(input) }}>
            <div className="flex items-end gap-2 rounded-2xl border bg-bg p-2 focus-within:border-brand">
              <label htmlFor="chat-input" className="sr-only">Ask a healthcare or hospital question</label>
              <textarea id="chat-input" rows={1} value={input} maxLength={1000} placeholder="Ask about a condition, a test, or hospital services…"
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
                className="max-h-36 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-subtle" />
              {busy
                ? <Button size="sm" icon={Square} onClick={() => abort.current?.abort()} aria-label="Stop generating" className="size-9 rounded-full p-0" />
                : <Button size="sm" variant="primary" type="submit" icon={ArrowUp} disabled={!input.trim()} aria-label="Send" className="size-9 rounded-full p-0" />}
            </div>
            <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-snug text-subtle">
              <ShieldCheck className="mt-px size-3.5 shrink-0" aria-hidden />
              <span>{status.data?.disclaimer ?? 'This AI assistant provides general medical information and is not a substitute for professional medical advice, diagnosis, or treatment.'}</span>
            </p>
            <p className="mt-1 flex items-start gap-1.5 text-[11px] leading-snug text-subtle">
              <Phone className="mt-px size-3.5 shrink-0" aria-hidden />
              <span>{status.data?.emergency_notice ?? 'If you believe you are experiencing a medical emergency, contact your local emergency service or seek immediate medical attention.'}</span>
            </p>
          </form>
        </div>
      </section>

      <aside className="hidden w-80 shrink-0 overflow-y-auto border-l bg-surface p-4 xl:block" aria-label="Evidence">
        <h2 className="mb-3 text-sm font-semibold">Evidence</h2>
        {evidence}
      </aside>

      <Modal open={mobilePanel === 'history'} onClose={() => setMobilePanel(null)} title="Conversations"><div className="-mx-5 -my-4 h-[60dvh]">{historyList}</div></Modal>
      <div className="xl:hidden">
        <Modal open={mobilePanel === 'sources'} onClose={() => setMobilePanel(null)} title="Evidence" description="The passages this answer was built from.">{evidence}</Modal>
      </div>
      <ConfirmDialog open={!!confirmDelete} onClose={() => setConfirmDelete(null)} danger confirmLabel="Delete" title="Delete this conversation?"
        body="The messages will be permanently removed." loading={remove.isPending}
        onConfirm={() => confirmDelete && remove.mutate(confirmDelete.id, { onSettled: () => setConfirmDelete(null) })} />
    </div>
  )
}
