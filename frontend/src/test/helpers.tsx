import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AuthProvider } from '@/hooks/useAuth'
import { ToastProvider } from '@/hooks/useUi'
import { setAccessToken } from '@/lib/api'
import type { User } from '@/types'

type Handler = unknown | (() => unknown)

/** Stub fetch with a route table keyed by "METHOD /api/path". Unknown routes return 404. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(input).split('?')[0]}`
    calls.push({ key, body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined })
    if (!(key in routes)) return fail(404, 'Not found')
    const handler = routes[key]
    const result = typeof handler === 'function' ? (handler as () => unknown)() : handler
    // A Response body can only be read once, so hand each caller its own copy.
    if (result instanceof Response) return result.clone()
    return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return calls
}

export const fail = (status: number, message: string) =>
  new Response(JSON.stringify({ error: { code: 'error', message, details: null } }), { status })

export function makeUser(role: User['roles'][number], permissions: string[] = []): User {
  const home = role === 'patient' ? '/patient/dashboard' : role === 'doctor' ? '/doctor/dashboard' : '/admin/command-center'
  return {
    id: 1, email: `${role}@demo.medflow.ai`, full_name: role === 'patient' ? 'Alex Morgan' : 'Jordan Ellis', roles: [role],
    permissions, patient_id: role === 'patient' ? 1 : null, doctor_id: role === 'doctor' ? 1 : null, home,
  }
}

/** Routes every screen needs. Pass null for a signed-out session. */
export function sessionRoutes(user: User | null): Record<string, Handler> {
  return {
    'POST /api/auth/refresh': user ? { access_token: 'test-token', user } : fail(401, 'Please sign in to continue.'),
    'GET /api/clock': { now: '2026-10-07T10:00:00', timezone: 'UTC', hospital: 'MedFlow General Hospital' },
    'GET /api/notifications': { unread: 0, items: [] },
  }
}

export function renderApp(ui: ReactNode, path = '/') {
  setAccessToken(null)
  localStorage.setItem('medflow-signed-in', '1') // behave like a returning browser so session restore runs
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider><AuthProvider>{ui}</AuthProvider></ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
