import { useQueryClient } from '@tanstack/react-query'
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, refreshSession, sessionUser, setAccessToken, setSessionLostHandler } from '@/lib/api'
import { syncHospitalClock } from '@/lib/format'
import type { User } from '@/types'

interface Session { access_token: string; user: User }

interface AuthContext {
  user: User | null
  /** True until the first silent refresh has finished. */
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  register: (body: Record<string, unknown>) => Promise<User>
  logout: () => Promise<void>
  adopt: (session: Session) => void
  reload: () => Promise<void>
  can: (...permissions: string[]) => boolean
}

const Ctx = createContext<AuthContext | null>(null)

/**
 * A non-secret hint that this browser has signed in before, so first-time visitors
 * don't trigger a pointless (and noisy) 401 from the silent refresh. The refresh
 * token itself stays in an httpOnly cookie that scripts cannot read.
 */
const HINT = 'medflow-signed-in'
const hadSession = () => {
  try { return localStorage.getItem(HINT) === '1' } catch { return true }
}
const remember = (on: boolean) => {
  try {
    if (on) localStorage.setItem(HINT, '1')
    else localStorage.removeItem(HINT)
  } catch { /* private mode */ }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const queryClient = useQueryClient()

  const adopt = useCallback((session: Session) => {
    setAccessToken(session.access_token)
    setUser(session.user)
    remember(true)
  }, [])

  const clear = useCallback(() => {
    setAccessToken(null)
    setUser(null)
    remember(false)
    queryClient.clear() // never leave one user's data cached for the next
  }, [queryClient])

  useEffect(() => {
    setSessionLostHandler(clear)
    // Restore the session from the httpOnly refresh cookie; the access token only ever lives in memory.
    Promise.all([
      hadSession() ? refreshSession().then((ok) => (ok ? setUser(sessionUser as User) : remember(false))) : null,
      api<{ now: string }>('/clock').then((c) => syncHospitalClock(c.now)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [clear])

  const value = useMemo<AuthContext>(() => ({
    user,
    loading,
    adopt,
    login: async (email, password) => {
      const session = await api<Session>('/auth/login', { method: 'POST', body: { email, password } })
      queryClient.clear()
      adopt(session)
      return session.user
    },
    register: async (body) => {
      const session = await api<Session>('/auth/register', { method: 'POST', body })
      adopt(session)
      return session.user
    },
    logout: async () => {
      await api('/auth/logout', { method: 'POST' }).catch(() => {})
      clear()
    },
    reload: async () => setUser(await api<User>('/auth/me')),
    can: (...permissions) => !!user && permissions.every((p) => user.permissions.includes(p)),
  }), [user, loading, adopt, clear, queryClient])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthContext {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
