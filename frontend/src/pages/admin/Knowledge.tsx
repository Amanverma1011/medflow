import { BookOpen, Eye, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { ScopeBadge } from '@/components/chat/ChatParts'
import { type Column, DataTable, MetricCard, StatusBadge } from '@/components/data'
import { Async, Badge, Button, Card, ConfirmDialog, Input, LoadingSkeleton, Modal, PageHeader, Select } from '@/components/ui'
import { api } from '@/lib/api'
import { formatDate, humanize } from '@/lib/format'
import { del, patch, post, useAction, useGet } from '@/services/queries'

interface Doc {
  id: number; name: string; filename: string; kb: 'medical' | 'hospital'; source_type: string; version: string
  status: string; error: string; chunk_count: number; is_active: boolean; uploaded_at: string; embedding_status: string
}
interface DocDetail extends Doc { chunks: { id: number; index: number; section: string; page: number; content: string }[] }
const PIPELINE = ['Upload', 'Validate', 'Extract text', 'Clean', 'Chunk', 'Metadata', 'Embed', 'Store in pgvector', 'Index']
const ACCEPT = '.pdf,.docx,.txt,.md'
const MAX_MB = 10

function UploadModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [meta, setMeta] = useState({ name: '', kb: 'medical', source_type: 'hospital_guideline', version: '1.0' })
  const [error, setError] = useState('')
  const set = (k: keyof typeof meta) => (e: { target: { value: string } }) => setMeta((m) => ({ ...m, [k]: e.target.value }))
  const upload = useAction(() => {
    const form = new FormData()
    form.append('file', file!)
    Object.entries(meta).forEach(([k, v]) => form.append(k, v))
    return api<Doc>('/rag/documents', { method: 'POST', form })
  }, {
    invalidate: ['documents', 'rag-status'],
    success: (d) => (d.status === 'indexed' ? `Indexed “${d.name}” as ${d.chunk_count} chunks` : `“${d.name}” uploaded, but indexing failed`),
    onSuccess: () => { setFile(null); setMeta((m) => ({ ...m, name: '' })); onClose() },
  })
  const pick = (f: File | undefined) => {
    setError('')
    if (!f) return
    if (!ACCEPT.split(',').some((ext) => f.name.toLowerCase().endsWith(ext))) return setError('Unsupported file type. Use PDF, DOCX, TXT or Markdown.')
    if (f.size > MAX_MB * 1024 * 1024) return setError(`File is larger than ${MAX_MB} MB.`)
    setFile(f)
  }
  return (
    <Modal open={open} onClose={onClose} title="Upload a knowledge document" description="Only upload hospital-approved content. It becomes answerable by the assistant as soon as it is indexed."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" icon={Upload} disabled={!file} loading={upload.isPending} onClick={() => upload.mutate()}>Upload and index</Button></>}>
      <div className="space-y-4">
        {error && <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2 text-sm text-crit">{error}</p>}
        <button type="button" onClick={() => fileRef.current?.click()}
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files[0]) }}
          className="flex w-full flex-col items-center rounded-xl border border-dashed px-4 py-7 text-center hover:border-brand hover:bg-surface-2">
          <Upload className="mb-2 size-5 text-subtle" aria-hidden />
          <span className="text-sm font-medium">{file ? file.name : 'Choose a file or drop it here'}</span>
          <span className="mt-0.5 text-xs text-muted">{file ? `${(file.size / 1024).toFixed(0)} KB` : `PDF, DOCX, TXT or Markdown, up to ${MAX_MB} MB`}</span>
        </button>
        <input ref={fileRef} type="file" accept={ACCEPT} className="sr-only" aria-label="Document file" onChange={(e) => pick(e.target.files?.[0])} />
        <Input label="Display name (optional)" value={meta.name} maxLength={160} onChange={set('name')} placeholder="Defaults to the file name" />
        <div className="grid gap-3 sm:grid-cols-3">
          <Select label="Knowledge base" value={meta.kb} onChange={set('kb')}><option value="medical">Medical information</option><option value="hospital">Hospital information</option></Select>
          <Select label="Source type" value={meta.source_type} onChange={set('source_type')}>
            {['hospital_guideline', 'patient_education', 'hospital_policy', 'hospital_information'].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
          <Input label="Version" value={meta.version} maxLength={16} onChange={set('version')} />
        </div>
      </div>
    </Modal>
  )
}

export default function Knowledge() {
  const [uploading, setUploading] = useState(false)
  const [viewing, setViewing] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<Doc | null>(null)
  const docs = useGet<Doc[]>('documents', '/rag/documents')
  const detail = useGet<DocDetail>('document', `/rag/documents/${viewing}`, undefined, { enabled: viewing !== null, placeholderData: undefined })
  const keys = { invalidate: ['documents', 'rag-status', 'document'] }
  const update = useAction((v: { id: number; body: object }) => patch(`/rag/documents/${v.id}`, v.body), { ...keys, success: 'Document updated' })
  const reindex = useAction((id: number | null) => post<Doc[]>('/rag/ingest', id ? { document_id: id } : {}), {
    ...keys, success: (out) => `Re-indexed ${out.filter((d) => d.status === 'indexed' || d.status === 'archived').length} of ${out.length} document(s)` })
  const remove = useAction((id: number) => del(`/rag/documents/${id}`), { ...keys, success: 'Document deleted', onSuccess: () => setDeleting(null) })

  const columns: Column<Doc>[] = [
    { key: 'name', header: 'Document', cell: (d) => <><span className="font-medium">{d.name}</span><span className="block text-xs text-subtle">{d.filename}</span>{d.error && <span className="mt-0.5 block text-xs text-crit">{d.error}</span>}</> },
    { key: 'kb', header: 'Knowledge base', cell: (d) => <ScopeBadge scope={d.kb} />, hideBelow: 'md' },
    { key: 'version', header: 'Version', cell: (d) => <span className="tabular">v{d.version}</span>, hideBelow: 'lg' },
    { key: 'status', header: 'Status', cell: (d) => <span className="flex flex-wrap items-center gap-1.5"><StatusBadge status={d.status} />{!d.is_active && d.status !== 'archived' && <Badge>Deactivated</Badge>}</span> },
    { key: 'chunks', header: 'Chunks', cell: (d) => <span className="tabular">{d.chunk_count}</span>, hideBelow: 'sm' },
    { key: 'embed', header: 'Embeddings', cell: (d) => <span className="text-muted">{humanize(d.embedding_status)}</span>, hideBelow: 'lg' },
    { key: 'date', header: 'Uploaded', cell: (d) => <span className="text-muted tabular">{formatDate(d.uploaded_at)}</span>, hideBelow: 'lg' },
    { key: 'actions', header: '', className: 'text-right', cell: (d) => (
      <span className="flex justify-end gap-1">
        <Button size="sm" variant="ghost" icon={Eye} aria-label={`View ${d.name}`} title="View chunks" onClick={() => setViewing(d.id)} />
        <Button size="sm" variant="ghost" icon={RefreshCw} aria-label={`Re-index ${d.name}`} title="Re-index" loading={reindex.isPending && reindex.variables === d.id} onClick={() => reindex.mutate(d.id)} />
        {d.status === 'archived'
          ? <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: d.id, body: { archived: false } })}>Restore</Button>
          : <>
            <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: d.id, body: { is_active: !d.is_active } })}>{d.is_active ? 'Deactivate' : 'Activate'}</Button>
            <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: d.id, body: { archived: true } })}>Archive</Button>
          </>}
        <Button size="sm" variant="ghost" icon={Trash2} aria-label={`Delete ${d.name}`} title="Delete" onClick={() => setDeleting(d)} />
      </span>) },
  ]

  return (
    <>
      <PageHeader title="Medical Knowledge Base" subtitle="The approved documents the Medical Assistant is allowed to answer from."
        actions={<><Button icon={RefreshCw} onClick={() => reindex.mutate(null)} loading={reindex.isPending && reindex.variables === null}>Re-index all</Button>
          <Button variant="primary" icon={Upload} onClick={() => setUploading(true)}>Upload document</Button></>} />
      <Async query={docs} what="the knowledge base" skeleton={<LoadingSkeleton rows={6} />}>
        {(rows) => (
          <>
            <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <MetricCard label="Documents" icon={BookOpen} value={rows.length} />
              <MetricCard label="Searchable now" value={rows.filter((d) => d.status === 'indexed' && d.is_active).length} tone="ok" />
              <MetricCard label="Chunks embedded" value={rows.reduce((n, d) => n + d.chunk_count, 0)} />
              <MetricCard label="Failed ingestions" value={rows.filter((d) => d.status === 'failed').length} tone={rows.some((d) => d.status === 'failed') ? 'crit' : 'neutral'} />
            </div>
            <Card className="mb-5 p-4">
              <h2 className="text-xs font-semibold tracking-[0.12em] uppercase">Ingestion pipeline</h2>
              <ol className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-2 text-xs text-muted">
                {PIPELINE.map((step, i) => <li key={step} className="flex items-center gap-1.5"><span className="rounded-md bg-surface-2 px-2 py-1">{step}</span>{i < PIPELINE.length - 1 && <span aria-hidden>→</span>}</li>)}
              </ol>
            </Card>
            <Card><DataTable caption="Knowledge documents" columns={columns} rows={rows} rowKey={(d) => d.id} dim={docs.isFetching}
              empty={{ title: 'No documents yet', body: 'Upload a guide to make it available to the Medical Assistant.' }} /></Card>
          </>
        )}
      </Async>

      <UploadModal open={uploading} onClose={() => setUploading(false)} />
      <Modal open={viewing !== null} onClose={() => setViewing(null)} wide title={detail.data?.name ?? 'Document'}
        description={detail.data ? `${detail.data.chunk_count} chunks · v${detail.data.version} · ${humanize(detail.data.source_type)}` : undefined}>
        <Async query={detail} what="this document">
          {(d) => (
            <ol className="space-y-3">
              {d.chunks.length === 0 && <p className="text-sm text-muted">This document has no indexed chunks.</p>}
              {d.chunks.map((c) => (
                <li key={c.id} className="rounded-lg border p-3">
                  <p className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-subtle"><Badge>Chunk {c.index + 1}</Badge><span className="font-medium text-text">{c.section || 'General'}</span><span>Page {c.page}</span><span className="ml-auto tabular">{c.content.length} chars</span></p>
                  <p className="text-[13px] leading-relaxed whitespace-pre-line text-muted">{c.content}</p>
                </li>
              ))}
            </ol>
          )}
        </Async>
      </Modal>
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} danger confirmLabel="Delete document" loading={remove.isPending}
        title="Delete this document?" body={`“${deleting?.name}” and its ${deleting?.chunk_count ?? 0} chunks and embeddings will be removed. The assistant will stop citing it immediately.`}
        onConfirm={() => deleting && remove.mutate(deleting.id)} />
    </>
  )
}
