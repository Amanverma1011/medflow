/** Server state. Every read goes through useGet; every write through useAction. */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type UseQueryOptions } from '@tanstack/react-query'
import { api, type RequestOptions } from '@/lib/api'
import { useToast } from '@/hooks/useUi'
import type { Department, Doctor } from '@/types'

type Params = RequestOptions['params']

/**
 * GET with caching. The first key segment is the invalidation group used by
 * useAction and by realtime events (see hooks/useRealtime.ts).
 */
export function useGet<T>(group: string, path: string, params?: Params,
  options?: Omit<UseQueryOptions<T>, 'queryKey' | 'queryFn'>) {
  return useQuery<T>({
    queryKey: [group, path, params ?? null],
    queryFn: ({ signal }) => api<T>(path, { params, signal }),
    placeholderData: keepPreviousData, // keep the table on screen while the next page or filter loads
    ...options,
  })
}

interface ActionOptions<TOut, TVars> {
  /** Query groups to refetch on success. */
  invalidate?: string[]
  /** Toast text, or a function of the result. Omit for silent actions. */
  success?: string | ((out: TOut, vars: TVars) => string)
  onSuccess?: (out: TOut, vars: TVars) => void
}

/** Mutation with consistent error toasts and cache invalidation. */
export function useAction<TVars = void, TOut = unknown>(
  fn: (vars: TVars) => Promise<TOut>, { invalidate = [], success, onSuccess }: ActionOptions<TOut, TVars> = {}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  return useMutation<TOut, unknown, TVars>({
    mutationFn: fn,
    onSuccess: (out, vars) => {
      for (const group of invalidate) queryClient.invalidateQueries({ queryKey: [group] })
      if (success) toast.success(typeof success === 'function' ? success(out, vars) : success)
      onSuccess?.(out, vars)
    },
    onError: (err) => toast.error(err),
  })
}

export const post = <T = unknown>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} })
export const patch = <T = unknown>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body })
export const del = (path: string) => api<void>(path, { method: 'DELETE' })

// Reference data that many screens share and that rarely changes.
const STABLE = { staleTime: 5 * 60_000 }
export const useDepartments = () => useGet<Department[]>('departments', '/departments', undefined, STABLE)
export const useDoctors = (params?: Params) => useGet<Doctor[]>('doctors', '/doctors', params, STABLE)

/** Live screens also poll, so they stay fresh if the WebSocket is blocked. */
export const LIVE = { refetchInterval: 30_000 }
