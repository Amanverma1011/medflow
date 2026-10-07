import { cn, humanize } from '@/lib/format'
import type { Bed, BedStatus, Ward } from '@/types'

/** Tile styling per bed state. The legend and each tile's label carry the meaning, not colour alone. */
export const BED_STYLE: Record<BedStatus, string> = {
  occupied: 'bg-info-soft text-info border-info/30',
  available: 'bg-ok-soft text-ok border-ok/30',
  cleaning: 'bg-warn-soft text-warn border-warn/30',
  maintenance: 'bg-crit-soft text-crit border-crit/30',
  reserved: 'bg-brand-soft text-brand border-brand/30',
}
export const BED_STATES = Object.keys(BED_STYLE) as BedStatus[]

export function BedLegend({ counts }: { counts?: Partial<Record<BedStatus, number>> }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted">
      {BED_STATES.map((s) => (
        <li key={s} className="flex items-center gap-1.5">
          <span className={cn('size-3 rounded border', BED_STYLE[s])} aria-hidden />
          {humanize(s)}{counts && <span className="font-medium text-text tabular">{counts[s] ?? 0}</span>}
        </li>
      ))}
    </ul>
  )
}

/** One ward as a grid of bed tiles. `dense` is the read-only command-center variant. */
export function BedGrid({ ward, onSelect, dense }: { ward: Ward; onSelect?: (bed: Bed) => void; dense?: boolean }) {
  return (
    <div className={cn('grid gap-1.5', dense ? 'grid-cols-8 sm:grid-cols-12' : 'grid-cols-4 sm:grid-cols-6 xl:grid-cols-8')}>
      {ward.beds.map((bed) => {
        const label = `Bed ${bed.label}, ${bed.status}${bed.patient ? `, ${bed.patient}` : ''}`
        const tile = cn('rounded-md border text-center font-medium tabular transition-transform', BED_STYLE[bed.status],
          dense ? 'h-6 text-[9px] leading-6' : 'px-1 py-2 text-xs')
        return onSelect ? (
          <button key={bed.id} onClick={() => onSelect(bed)} aria-label={label} title={label} className={cn(tile, 'hover:scale-[1.04]')}>
            {bed.label.split('-')[1]}
            {!dense && <span className="mt-0.5 block truncate text-[10px] font-normal opacity-80">{humanize(bed.status)}</span>}
          </button>
        ) : <div key={bed.id} title={label} aria-label={label} role="img" className={tile}>{bed.label.split('-')[1]}</div>
      })}
    </div>
  )
}
