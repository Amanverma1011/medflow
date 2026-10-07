/** Audit log and Settings (system configuration, users & roles, demo data). */
import { DatabaseZap, Search, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { type Column, DataTable, Pagination, StatusBadge } from '@/components/data'
import { Async, Badge, Button, Card, ConfirmDialog, Input, LoadingSkeleton, Modal, PageHeader, Select, Tabs } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { useDebounced } from '@/hooks/useUi'
import { formatDateTime, humanize, num } from '@/lib/format'
import { patch, post, useAction, useGet } from '@/services/queries'
import type { Paged, Role, User } from '@/types'

// ----------------------------------------------------------------------------- audit
interface AuditRow { id: number; user: string; action: string; resource_type: string; resource_id: string; result: string; ip: string; device: string; detail: string; created_at: string }
const AUDIT_COLUMNS: Column<AuditRow>[] = [
  { key: 'time', header: 'Timestamp', cell: (a) => <span className="whitespace-nowrap text-muted tabular">{formatDateTime(a.created_at)}</span> },
  { key: 'user', header: 'User', cell: (a) => a.user },
  { key: 'action', header: 'Action', cell: (a) => <span className="font-mono text-xs">{a.action}</span> },
  { key: 'resource', header: 'Resource', cell: (a) => (a.resource_type ? `${humanize(a.resource_type)}${a.resource_id ? ` #${a.resource_id}` : ''}` : '—'), hideBelow: 'md' },
  { key: 'detail', header: 'Detail', cell: (a) => <span className="text-muted">{a.detail || '—'}</span>, hideBelow: 'lg' },
  { key: 'ip', header: 'IP / device', cell: (a) => <span className="text-xs text-subtle" title={a.device}>{a.ip || '—'} · {a.device.split(' ')[0] || 'unknown'}</span>, hideBelow: 'lg' },
  { key: 'result', header: 'Result', cell: (a) => <StatusBadge status={a.result} /> },
]

function Audit() {
  const [filters, setFilters] = useState({ q: '', action: '', result: '' })
  const [page, setPage] = useState(1)
  const q = useDebounced(filters.q)
  const query = useGet<Paged<AuditRow>>('audit', '/audit-logs', { ...filters, q, page, size: 25 })
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => { setFilters((f) => ({ ...f, [k]: e.target.value })); setPage(1) }
  return (
    <>
      <PageHeader title="Audit Logs" subtitle="Who did what, to which record, and whether it succeeded. Clinical content and chat text are never logged." />
      <Card>
        <div className="grid gap-3 border-b p-4 sm:grid-cols-3">
          <div className="relative"><Search className="pointer-events-none absolute top-3 left-3 size-4 text-subtle" aria-hidden />
            <Input aria-label="Search audit log" placeholder="Search user or action" className="pl-9" value={filters.q} onChange={set('q')} /></div>
          <Select aria-label="Action" value={filters.action} onChange={set('action')}>
            <option value="">All actions</option>
            {[['auth', 'Sign-in and registration'], ['patient', 'Patient records'], ['appointment', 'Appointments'], ['queue', 'Queue'], ['consultation', 'Consultations'], ['bed', 'Beds'],
              ['knowledge', 'Knowledge base'], ['chat', 'Chat escalations'], ['copilot', 'Copilot queries'], ['report', 'Report exports'], ['user', 'User management'], ['demo', 'Demo data']]
              .map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
          <Select aria-label="Result" value={filters.result} onChange={set('result')}><option value="">Any result</option><option value="success">Success</option><option value="failure">Failure</option><option value="denied">Denied</option></Select>
        </div>
        <Async query={query} what="the audit log">
          {(d) => <>
            <DataTable caption="Audit log" columns={AUDIT_COLUMNS} rows={d.items} rowKey={(a) => a.id} dim={query.isFetching} empty={{ title: 'No audit entries match', body: 'Try a different action or clear the search.' }} />
            <Pagination page={d.page} size={d.size} total={d.total} onChange={setPage} />
          </>}
        </Async>
      </Card>
    </>
  )
}

// ----------------------------------------------------------------------------- settings
interface SystemInfo {
  hospital: Record<string, string>; ai: Record<string, string | number | boolean>; rag: Record<string, number>
  security: Record<string, string | number | boolean>; data: Record<string, number>; notice: string
}
interface RoleInfo { name: Role; description: string; users: number; permissions: string[] }
interface UserRow { id: number; email: string; full_name: string; roles: Role[]; is_active: boolean; last_login_at: string | null }

function KeyValues({ title, values }: { title: string; values: Record<string, unknown> }) {
  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      <dl className="mt-3 space-y-2 text-sm">
        {Object.entries(values).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 border-b border-dashed pb-2 last:border-0 last:pb-0">
            <dt className="text-muted">{humanize(k)}</dt>
            <dd className="text-right font-medium tabular">{typeof v === 'boolean' ? (v ? 'Yes' : 'No') : typeof v === 'number' ? num(v, 2) : String(v)}</dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

function Users({ roles }: { roles: RoleInfo[] }) {
  const { user: me } = useAuth()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ full_name: '', email: '', password: '', role: 'receptionist' })
  const [error, setError] = useState('')
  const term = useDebounced(q)
  const query = useGet<Paged<UserRow>>('users', '/users', { q: term, role, page, size: 10 })
  const update = useAction((v: { id: number; body: object }) => patch(`/users/${v.id}`, v.body), { invalidate: ['users', 'roles'], success: 'User updated' })
  const create = useAction(() => post('/users', { full_name: form.full_name, email: form.email, password: form.password, roles: [form.role] }),
    { invalidate: ['users', 'roles'], success: 'User created', onSuccess: () => { setCreating(false); setForm({ full_name: '', email: '', password: '', role: 'receptionist' }) } })
  const submit = () => {
    if (form.full_name.trim().length < 2 || !/^\S+@\S+\.\S+$/.test(form.email)) return setError('Enter a name and a valid email address.')
    if (form.password.length < 8 || !/[A-Za-z]/.test(form.password) || !/\d/.test(form.password)) return setError('Password needs at least 8 characters, with a letter and a number.')
    setError(''); create.mutate()
  }
  const columns: Column<UserRow>[] = [
    { key: 'name', header: 'User', cell: (u) => <><span className="font-medium">{u.full_name}</span><span className="block text-xs text-subtle">{u.email}</span></> },
    { key: 'role', header: 'Role', cell: (u) => (
      <Select aria-label={`Role for ${u.full_name}`} value={u.roles[0]} disabled={u.id === me?.id} className="h-8 w-40 text-xs"
        onChange={(e) => update.mutate({ id: u.id, body: { roles: [e.target.value] } })}>
        {roles.map((r) => <option key={r.name} value={r.name}>{humanize(r.name)}</option>)}
      </Select>) },
    { key: 'login', header: 'Last sign-in', cell: (u) => <span className="text-muted tabular">{u.last_login_at ? formatDateTime(u.last_login_at) : 'Never'}</span>, hideBelow: 'md' },
    { key: 'status', header: 'Status', cell: (u) => <Badge tone={u.is_active ? 'ok' : 'neutral'}>{u.is_active ? 'Active' : 'Deactivated'}</Badge> },
    { key: 'actions', header: '', className: 'text-right', cell: (u) => u.id !== me?.id && (
      <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? 'Deactivate' : 'Reactivate'}</Button>) },
  ]
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 border-b p-4">
        <h2 className="mr-auto text-sm font-semibold">Users</h2>
        <Input aria-label="Search users" placeholder="Search name or email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} className="w-52" />
        <Select aria-label="Role" value={role} onChange={(e) => { setRole(e.target.value); setPage(1) }} className="w-40"><option value="">All roles</option>{roles.map((r) => <option key={r.name} value={r.name}>{humanize(r.name)}</option>)}</Select>
        <Button variant="primary" icon={UserPlus} onClick={() => setCreating(true)}>Add user</Button>
      </div>
      <Async query={query} what="users">
        {(d) => <><DataTable caption="Users" columns={columns} rows={d.items} rowKey={(u) => u.id} dim={query.isFetching} empty={{ title: 'No users match' }} />
          <Pagination page={d.page} size={d.size} total={d.total} onChange={setPage} /></>}
      </Async>
      <Modal open={creating} onClose={() => setCreating(false)} title="Add a staff user"
        footer={<><Button onClick={() => setCreating(false)}>Cancel</Button><Button variant="primary" onClick={submit} loading={create.isPending}>Create user</Button></>}>
        <div className="space-y-4">
          {error && <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2 text-sm text-crit">{error}</p>}
          <Input label="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <Input label="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Input label="Temporary password" type="password" autoComplete="new-password" maxLength={72} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} hint="At least 8 characters, with a letter and a number." />
          <Select label="Role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{roles.filter((r) => r.name !== 'patient').map((r) => <option key={r.name} value={r.name}>{humanize(r.name)}</option>)}</Select>
        </div>
      </Modal>
    </Card>
  )
}

function Settings() {
  const { can, adopt } = useAuth()
  const manageUsers = can('users:manage')
  const [tab, setTab] = useState<'system' | 'users' | 'demo'>('system')
  const [confirm, setConfirm] = useState(false)
  const info = useGet<SystemInfo>('system', '/settings/system')
  const roles = useGet<RoleInfo[]>('roles', '/roles', undefined, { enabled: manageUsers })
  const load = useAction(() => post<{ loaded: Record<string, number>; session: { access_token: string; user: User } | null }>('/demo/load'), {
    success: (out) => `Demo hospital loaded: ${out.loaded.patients} patients, ${out.loaded.appointments} appointments, ${out.loaded.knowledge_documents} documents`,
    // Reloading wipes sessions too, so the server signs us straight back in.
    onSuccess: (out) => { setConfirm(false); if (out.session) adopt(out.session); setTimeout(() => location.reload(), 600) },
  })
  const tabs = [{ id: 'system' as const, label: 'System' }, ...(manageUsers ? [{ id: 'users' as const, label: 'Users & roles' }] : []), ...(can('demo:load') ? [{ id: 'demo' as const, label: 'Demo mode' }] : [])]
  return (
    <>
      <PageHeader title="Settings" subtitle="Runtime configuration, access control and demo data." />
      <Tabs label="Settings" tabs={tabs} value={tab} onChange={setTab} />
      {tab === 'system' && (
        <Async query={info} what="system settings" skeleton={<LoadingSkeleton variant="cards" rows={4} />}>
          {(s) => (
            <>
              <p className="mb-4 rounded-lg border border-dashed px-3 py-2.5 text-sm text-muted">{s.notice}</p>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                <KeyValues title="Hospital" values={s.hospital} /><KeyValues title="AI configuration" values={s.ai} /><KeyValues title="RAG parameters" values={s.rag} />
                <KeyValues title="Security" values={s.security} /><KeyValues title="Data" values={s.data} />
                <Card className="p-4 text-sm text-muted"><h2 className="text-sm font-semibold text-text">Changing configuration</h2>
                  <p className="mt-2">These values come from environment variables and are read-only here. Edit <code className="rounded bg-surface-2 px-1">.env</code> and restart the backend. API keys are never sent to the browser; only whether one is set.</p></Card>
              </div>
            </>
          )}
        </Async>
      )}
      {tab === 'users' && manageUsers && (
        <Async query={roles} what="roles" skeleton={<LoadingSkeleton rows={6} />}>
          {(r) => (
            <div className="space-y-4">
              <Users roles={r} />
              <Card className="p-4">
                <h2 className="text-sm font-semibold">Roles and permissions</h2>
                <ul className="mt-3 divide-y">
                  {r.map((role) => (
                    <li key={role.name} className="py-3 first:pt-0 last:pb-0">
                      <p className="flex items-center gap-2 text-sm font-medium">{humanize(role.name)}<Badge>{role.users} users</Badge></p>
                      <p className="text-xs text-muted">{role.description}</p>
                      <p className="mt-1.5 flex flex-wrap gap-1">{role.permissions.map((p) => <code key={p} className="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">{p}</code>)}</p>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          )}
        </Async>
      )}
      {tab === 'demo' && can('demo:load') && (
        <Card className="max-w-2xl p-5">
          <DatabaseZap className="size-6 text-brand" aria-hidden />
          <h2 className="mt-3 font-semibold">Load Demo Hospital</h2>
          <p className="mt-1.5 text-sm text-muted">Rebuilds MedFlow General Hospital from scratch, anchored to the current hospital time: users, 500+ patients, doctors, about 12,000 appointments, live queues, beds, feedback, analytics history and the 24-document knowledge base.</p>
          <p className="mt-2 text-sm text-warn">This replaces all current data, including anything you created during this session.</p>
          <Button variant="primary" className="mt-4" icon={DatabaseZap} onClick={() => setConfirm(true)}>Load Demo Hospital</Button>
        </Card>
      )}
      <ConfirmDialog open={confirm} onClose={() => setConfirm(false)} danger loading={load.isPending} confirmLabel="Replace all data"
        title="Reload the demo hospital?" body="All existing records, conversations and uploaded documents will be deleted and regenerated. This takes about ten seconds."
        onConfirm={() => load.mutate()} />
    </>
  )
}

export default function System({ view }: { view: 'audit' | 'settings' }) {
  return view === 'audit' ? <Audit /> : <Settings />
}
