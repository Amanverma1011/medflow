import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AIInsightCard, QueueCard } from '@/components/cards'
import { DataTable, MetricCard, Pagination, StatusBadge } from '@/components/data'
import { ConfirmDialog, EmptyState, ErrorState, Input } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { humanize, isoDate, isoDateTime } from '@/lib/format'
import type { Insight, QueueEstimate } from '@/types'

describe('formatting', () => {
  it('humanises enum values and keeps wall-clock dates', () => {
    expect(humanize('in_consultation')).toBe('In consultation')
    const d = new Date(2026, 9, 7, 23, 30)
    expect(isoDate(d)).toBe('2026-10-07') // not shifted to UTC
    expect(isoDateTime(d)).toBe('2026-10-07T23:30:00')
  })
})

describe('MetricCard', () => {
  it('marks a falling wait time as an improvement', () => {
    render(<MetricCard label="Average Wait Time" value="24" unit="min" trend={-12} lowerIsBetter compare="vs yesterday" />)
    expect(screen.getByText('24')).toBeInTheDocument()
    expect(screen.getByText(/-12%/)).toBeInTheDocument()
    expect(screen.getByText('improving')).toBeInTheDocument()
  })

  it('marks a rising wait time as worsening, and hides the comparison when there is no baseline', () => {
    const { rerender } = render(<MetricCard label="Wait" value="30" trend={8} lowerIsBetter compare="vs yesterday" />)
    expect(screen.getByText('worsening')).toBeInTheDocument()
    rerender(<MetricCard label="Wait" value="30" trend={null} compare="vs yesterday" />)
    expect(screen.queryByText('vs yesterday')).not.toBeInTheDocument()
  })
})

describe('StatusBadge', () => {
  it('always shows status as text, never colour alone', () => {
    render(<><StatusBadge status="no_show" /><StatusBadge status="in_consultation" /></>)
    expect(screen.getByText('No show')).toBeInTheDocument()
    expect(screen.getByText('In consultation')).toBeInTheDocument()
  })
})

describe('DataTable', () => {
  const columns = [{ key: 'name', header: 'Name', cell: (r: { id: number; name: string }) => r.name }]

  it('renders rows and supports keyboard activation', async () => {
    const onRowClick = vi.fn()
    render(<DataTable caption="People" columns={columns} rows={[{ id: 1, name: 'Alex Morgan' }]} rowKey={(r) => r.id} onRowClick={onRowClick} />)
    expect(screen.getByRole('table', { name: 'People' })).toBeInTheDocument()
    screen.getByText('Alex Morgan').closest('tr')!.focus()
    await userEvent.keyboard('{Enter}')
    expect(onRowClick).toHaveBeenCalledWith({ id: 1, name: 'Alex Morgan' })
  })

  it('shows an empty state instead of an empty table', () => {
    render(<DataTable caption="People" columns={columns} rows={[]} rowKey={(r) => r.id} empty={{ title: 'No patients match these filters' }} />)
    expect(screen.getByText('No patients match these filters')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})

describe('Pagination', () => {
  it('pages forward and disables at the ends', async () => {
    const onChange = vi.fn()
    render(<Pagination page={1} size={20} total={45} onChange={onChange} />)
    expect(screen.getByText('1–20 of 45')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(onChange).toHaveBeenCalledWith(2)
  })

  it('renders nothing when everything fits on one page', () => {
    const { container } = render(<Pagination page={1} size={20} total={5} onChange={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('async states', () => {
  it('explains a permission error and offers no pointless retry', () => {
    render(<ErrorState error={new ApiError(403, 'forbidden', 'x')} what="analytics" onRetry={() => {}} />)
    expect(screen.getByText("You don't have access")).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('offers a retry for server errors without leaking the raw message', async () => {
    const onRetry = vi.fn()
    render(<ErrorState error={new ApiError(500, 'internal_error', 'stack trace')} what="today's appointments" onRetry={onRetry} />)
    expect(screen.getByText("We couldn't load today's appointments.")).toBeInTheDocument()
    expect(screen.queryByText('stack trace')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalled()
  })

  it('renders an empty state', () => {
    render(<EmptyState title="No appointments today" body="Your schedule is clear." />)
    expect(screen.getByText('Your schedule is clear.')).toBeInTheDocument()
  })
})

describe('forms and dialogs', () => {
  it('associates the label and error with the input', () => {
    render(<Input label="Email" error="Enter a valid email address" />)
    const input = screen.getByLabelText('Email')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Enter a valid email address')
  })

  it('confirm dialog is modal, confirms on click and closes on Escape', async () => {
    const onClose = vi.fn()
    const onConfirm = vi.fn()
    render(<ConfirmDialog open title="Cancel this appointment?" body="The slot will be released." confirmLabel="Cancel appointment" onClose={onClose} onConfirm={onConfirm} />)
    const dialog = screen.getByRole('dialog', { name: 'Cancel this appointment?' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel appointment' }))
    expect(onConfirm).toHaveBeenCalled()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})

describe('AI cards', () => {
  const insight: Insight = {
    id: 1, key: 'icu_capacity', title: 'ICU bed bottleneck', severity: 'high', category: 'bed_occupancy', confidence: 0.87,
    description: 'ICU occupancy is at 88%.', impact: 'Limited capacity', recommendation: 'Review step-down candidates.',
    evidence: [{ label: 'Current occupancy', value: '14 of 16 beds' }], created_at: '2026-10-07T10:00:00',
    label: 'AI recommendation for human review.',
  }

  it('labels insights as recommendations, with confidence and evidence', async () => {
    const onDismiss = vi.fn()
    render(<AIInsightCard insight={insight} onDismiss={onDismiss} />)
    expect(screen.getByText('AI recommendation')).toBeInTheDocument()
    expect(screen.getByText(/Suggested action/)).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Confidence' })).toHaveAttribute('aria-valuenow', '87')
    expect(screen.getByText('14 of 16 beds')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Dismiss insight/ }))
    expect(onDismiss).toHaveBeenCalled()
  })

  const estimate: QueueEstimate = {
    token: 'A-047', status: 'waiting', patients_ahead: 6, currently_serving: 'A-041', estimated_wait_minutes: 32, confidence: 0.66,
    factors: [{ name: 'Queue length', detail: '6 patients ahead of you' }], label: 'AI-generated estimate, not a guaranteed time',
    doctor: 'Dr. Priya Sharma', room: 'A101',
  }

  it('shows the queue token, position and an explained estimate', () => {
    render(<QueueCard estimate={estimate} />)
    expect(screen.getByText('A-047')).toBeInTheDocument()
    expect(screen.getByText('A-041')).toBeInTheDocument()
    expect(screen.getByText('32 min')).toBeInTheDocument()
    expect(screen.getByText(/6 patients ahead of you/)).toBeInTheDocument()
    expect(screen.getByText(/not a guaranteed time/)).toBeInTheDocument()
  })

  it('switches to a clear call to action when it is the turn of the patient', () => {
    render(<QueueCard estimate={{ ...estimate, status: 'in_consultation' }} />)
    expect(screen.getByText(/your turn/)).toBeInTheDocument()
    expect(screen.queryByText('Estimated wait')).not.toBeInTheDocument()
  })
})
