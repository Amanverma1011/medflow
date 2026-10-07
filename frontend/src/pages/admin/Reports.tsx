import { Download, FileSpreadsheet, FileText } from 'lucide-react'
import { useState } from 'react'
import { Async, Button, Card, EmptyState, Input, LoadingSkeleton, PageHeader, Select } from '@/components/ui'
import { useToast } from '@/hooks/useUi'
import { download } from '@/lib/api'
import { addDays, cn, formatDate, hospitalNow, humanize, isoDate, num } from '@/lib/format'
import { useDepartments, useGet } from '@/services/queries'

interface Report { key: string; title: string; date_from: string; date_to: string; columns: string[]; rows: Record<string, any>[] }
const PREVIEW_ROWS = 25

export default function Reports() {
  const toast = useToast()
  const today = hospitalNow()
  const [kind, setKind] = useState('daily-operations')
  const [filters, setFilters] = useState({ date_from: isoDate(addDays(today, -6)), date_to: isoDate(today), department_id: '' })
  const [exporting, setExporting] = useState<string | null>(null)
  const departments = useDepartments()
  const kinds = useGet<{ key: string; title: string }[]>('report-kinds', '/reports', undefined, { staleTime: Infinity })
  const report = useGet<Report>('report', `/reports/${kind}`, filters)
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => setFilters((f) => ({ ...f, [k]: e.target.value }))

  const exportAs = async (format: 'csv' | 'pdf') => {
    setExporting(format)
    try { await download(`/reports/${kind}`, { ...filters, format }); toast.success(`${format.toUpperCase()} downloaded`) }
    catch (err) { toast.error(err) } finally { setExporting(null) }
  }
  const cell = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'number' ? num(v, 2)
    : /^\d{4}-\d{2}-\d{2}/.test(String(v)) ? formatDate(String(v)) : String(v))

  return (
    <>
      <PageHeader title="Reports" subtitle="Operational reports with date and department filters. Export as CSV or PDF." />
      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <Card className="h-fit p-2">
          <nav aria-label="Report type">
            {kinds.isLoading ? <LoadingSkeleton rows={7} /> : kinds.data?.map((k) => (
              <button key={k.key} onClick={() => setKind(k.key)} aria-current={kind === k.key}
                className={cn('flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm', kind === k.key ? 'bg-brand-soft font-medium text-brand' : 'text-muted hover:bg-surface-2 hover:text-text')}>
                <FileText className="size-4 shrink-0" aria-hidden />{k.title}
              </button>
            ))}
          </nav>
        </Card>
        <Card>
          <div className="flex flex-wrap items-end gap-3 border-b p-4">
            <Input label="From" type="date" value={filters.date_from} max={filters.date_to} onChange={set('date_from')} className="w-40" />
            <Input label="To" type="date" value={filters.date_to} min={filters.date_from} max={isoDate(addDays(today, 7))} onChange={set('date_to')} className="w-40" />
            <Select label="Department" value={filters.department_id} onChange={set('department_id')} className="w-48">
              <option value="">All departments</option>{departments.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
            <div className="ml-auto flex gap-2">
              <Button icon={FileSpreadsheet} onClick={() => exportAs('csv')} loading={exporting === 'csv'} disabled={!report.data?.rows.length}>Export CSV</Button>
              <Button icon={Download} variant="primary" onClick={() => exportAs('pdf')} loading={exporting === 'pdf'} disabled={!report.data?.rows.length}>Export PDF</Button>
            </div>
          </div>
          <Async query={report} what="this report" empty={(r) => !r.rows.length && <EmptyState title="No data for these filters" body="Widen the date range or choose a different department." />}>
            {(r) => (
              <>
                <div className="px-4 pt-4"><h2 className="text-sm font-semibold">{r.title}</h2><p className="text-xs text-subtle">{formatDate(r.date_from)} – {formatDate(r.date_to)} · {r.rows.length} rows</p></div>
                <div className={cn('mt-3 overflow-x-auto transition-opacity', report.isFetching && 'opacity-60')}>
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">{r.title}</caption>
                    <thead><tr className="border-y text-xs text-subtle">{r.columns.map((c) => <th key={c} scope="col" className="px-4 py-2 font-medium whitespace-nowrap">{humanize(c)}</th>)}</tr></thead>
                    <tbody>{r.rows.slice(0, PREVIEW_ROWS).map((row, i) => (
                      <tr key={i} className="border-b last:border-0">{r.columns.map((c) => <td key={c} className="max-w-md px-4 py-2.5 align-top tabular">{cell(row[c])}</td>)}</tr>
                    ))}</tbody>
                  </table>
                </div>
                {r.rows.length > PREVIEW_ROWS && <p className="border-t px-4 py-2.5 text-xs text-muted">Previewing the first {PREVIEW_ROWS} rows. Exports include all {r.rows.length}.</p>}
              </>
            )}
          </Async>
        </Card>
      </div>
    </>
  )
}
