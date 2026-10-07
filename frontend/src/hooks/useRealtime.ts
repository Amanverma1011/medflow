import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { getAccessToken } from '@/lib/api'

/** Which cached queries each server event makes stale. */
const INVALIDATES: Record<string, string[]> = {
  'queue.updated': ['queues', 'queue-me', 'doctor-dashboard', 'overview', 'operations', 'appointments', 'queue-status'],
  'appointment.updated': ['appointments', 'calendar', 'doctor-dashboard', 'overview', 'operations', 'slots', 'queue-me'],
  'bed.updated': ['beds', 'bed-tasks', 'overview', 'analytics-beds'],
  'notification.new': ['notifications'],
  'insight.updated': ['insights', 'overview'],
  'feedback.new': ['experience', 'feedback'],
}
const MAX_BACKOFF_MS = 30_000

/**
 * One WebSocket per signed-in session. Events carry no data, only "this changed",
 * so the client refetches through the normal authorised API.
 */
export function useRealtime(userId: number | undefined) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!userId || typeof WebSocket === 'undefined') return
    let socket: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout>
    let attempts = 0
    let closed = false

    const connect = () => {
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${scheme}://${location.host}/ws`)
      socket.onopen = () => socket?.send(JSON.stringify({ type: 'auth', token: getAccessToken() }))
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data) as { type: string }
        if (event.type === 'ready') attempts = 0
        for (const key of INVALIDATES[event.type] ?? []) queryClient.invalidateQueries({ queryKey: [key] })
      }
      socket.onclose = () => {
        if (closed) return
        timer = setTimeout(connect, Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempts++))
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [userId, queryClient])
}
