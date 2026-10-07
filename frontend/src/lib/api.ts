/** HTTP client: bearer access token in memory, httpOnly refresh cookie, one silent refresh on 401. */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: { field: string; message: string }[] | null,
  ) {
    super(message)
  }
}

let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
let onSessionLost: () => void = () => {}

export const setAccessToken = (token: string | null) => { accessToken = token }
export const getAccessToken = () => accessToken
export const setSessionLostHandler = (fn: () => void) => { onSessionLost = fn }

const FALLBACK: Record<number, string> = {
  400: 'That request was not valid.',
  401: 'Please sign in to continue.',
  403: "You don't have permission to do that.",
  404: "We couldn't find what you were looking for.",
  409: 'That conflicts with the current state. Refresh and try again.',
  429: 'Too many requests. Please wait a moment and try again.',
  500: 'Something went wrong on our side. Please try again.',
}

async function toError(res: Response): Promise<ApiError> {
  let body: { error?: { code?: string; message?: string; details?: ApiError['details'] } } = {}
  try { body = await res.json() } catch { /* non-JSON error body */ }
  const fallback = FALLBACK[res.status] ?? FALLBACK[res.status >= 500 ? 500 : 400]
  return new ApiError(res.status, body.error?.code ?? 'error', body.error?.message ?? fallback, body.error?.details)
}

/** Single-flight refresh: concurrent 401s share one call. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
    .then(async (res) => {
      if (!res.ok) return false
      const data = await res.json()
      accessToken = data.access_token
      sessionUser = data.user
      return true
    })
    .catch(() => false)
    .finally(() => { refreshing = null })
  return refreshing
}

/** The user returned by the most recent refresh, read once by the auth provider at start-up. */
export let sessionUser: unknown = null

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  form?: FormData
  params?: Record<string, string | number | boolean | null | undefined>
  signal?: AbortSignal
}

export function buildUrl(path: string, params?: RequestOptions['params']): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value))
  }
  const qs = query.toString()
  return `/api${path}${qs ? `?${qs}` : ''}`
}

export async function rawFetch(path: string, opts: RequestOptions = {}, retry = true): Promise<Response> {
  const headers: Record<string, string> = {}
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(buildUrl(path, opts.params), {
      method: opts.method ?? 'GET',
      headers,
      body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
      credentials: 'include',
      signal: opts.signal,
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(0, 'network', "We couldn't reach the server. Check your connection and try again.")
  }
  if (res.status === 401 && retry && !path.startsWith('/auth/')) {
    if (await refreshSession()) return rawFetch(path, opts, false)
    onSessionLost()
  }
  if (!res.ok) throw await toError(res)
  return res
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await rawFetch(path, opts)
  return res.status === 204 ? (undefined as T) : res.json()
}

/** Download a file response (CSV/PDF exports) using the server-provided filename. */
export async function download(path: string, params?: RequestOptions['params']): Promise<void> {
  const res = await rawFetch(path, { params })
  const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? 'export'
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  URL.revokeObjectURL(url)
}

export interface SseEvent { event: string; data: any }

/** POST + Server-Sent Events, parsed incrementally (EventSource cannot POST or send auth headers). */
export async function* streamSse(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<SseEvent> {
  const res = await rawFetch(path, { method: 'POST', body, signal })
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let split: number
    while ((split = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, split)
      buffer = buffer.slice(split + 2)
      const event = /^event: (.+)$/m.exec(block)?.[1]
      const data = /^data: (.+)$/m.exec(block)?.[1]
      if (event && data) yield { event, data: JSON.parse(data) }
    }
  }
}
