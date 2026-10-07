import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Bell, CheckCheck, CheckCircle2, Info, XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { cn, timeAgo } from '@/lib/format'
import { LIVE, post, useAction, useGet } from '@/services/queries'
import type { Notification } from '@/types'
import { EmptyState, LoadingSkeleton } from './ui'

const ICON = { info: Info, success: CheckCircle2, warning: AlertTriangle, critical: XCircle }
const TONE = { info: 'text-info', success: 'text-ok', warning: 'text-warn', critical: 'text-crit' }

export function NotificationPanel() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const query = useGet<{ unread: number; items: Notification[] }>('notifications', '/notifications', undefined, LIVE)
  const readOne = useAction((id: number) => post(`/notifications/${id}/read`), { invalidate: ['notifications'] })
  const readAll = useAction(() => post('/notifications/read-all'), { invalidate: ['notifications'] })
  const unread = query.data?.unread ?? 0

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close) }
  }, [open])

  const openItem = (n: Notification) => {
    if (!n.is_read) readOne.mutate(n.id)
    setOpen(false)
    if (n.link) navigate(n.link)
  }

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="dialog"
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative flex size-9 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-text">
        <Bell className="size-[18px]" aria-hidden />
        {unread > 0 && (
          <motion.span key={unread} initial={{ scale: 0.6 }} animate={{ scale: 1 }}
            className="absolute top-1 right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-crit px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? '9+' : unread}
          </motion.span>
        )}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div role="dialog" aria-label="Notifications" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.15 }}
            className="fixed inset-x-3 top-16 z-40 overflow-hidden rounded-xl border bg-surface shadow-xl sm:absolute sm:inset-x-auto sm:top-11 sm:right-0 sm:w-96">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <p className="text-sm font-semibold">Notifications</p>
              {unread > 0 && (
                <button onClick={() => readAll.mutate()} className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
                  <CheckCheck className="size-3.5" aria-hidden />Mark all read
                </button>
              )}
            </div>
            <div className="max-h-[60dvh] overflow-y-auto">
              {query.isLoading ? <div className="p-4"><LoadingSkeleton rows={3} /></div>
                : !query.data?.items.length ? <EmptyState icon={Bell} title="You're all caught up" body="New alerts and reminders will appear here." />
                  : (
                    <ul>
                      {query.data.items.map((n) => {
                        const Icon = ICON[n.severity]
                        return (
                          <li key={n.id}>
                            <button onClick={() => openItem(n)} className={cn('flex w-full gap-3 border-b px-4 py-3 text-left last:border-0 hover:bg-surface-2', !n.is_read && 'bg-brand-soft/40')}>
                              <Icon className={cn('mt-0.5 size-4 shrink-0', TONE[n.severity])} aria-hidden />
                              <span className="min-w-0 flex-1">
                                <span className="flex items-center gap-2">
                                  <span className={cn('text-sm', !n.is_read && 'font-semibold')}>{n.title}</span>
                                  {!n.is_read && <span className="size-1.5 rounded-full bg-brand" aria-label="Unread" />}
                                </span>
                                {n.body && <span className="mt-0.5 block text-xs text-muted">{n.body}</span>}
                                <span className="mt-1 block text-[11px] text-subtle">{timeAgo(n.created_at)}</span>
                              </span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
