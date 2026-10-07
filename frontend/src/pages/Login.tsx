import { ShieldCheck } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { Button, Card, Input, Select } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { Logo, ThemeToggle } from '@/layouts/Layouts'
import { ApiError } from '@/lib/api'

/** Documented demo credentials (see README). These accounts only exist in the synthetic demo hospital. */
const DEMO_PASSWORD = 'MedFlow#2026'
const DEMO_ACCOUNTS = [
  { role: 'Administrator', email: 'admin@demo.medflow.ai', note: 'Command center, analytics, AI insights' },
  { role: 'Doctor', email: 'doctor@demo.medflow.ai', note: 'Dr. Priya Sharma, live clinic queue' },
  { role: 'Patient', email: 'patient@demo.medflow.ai', note: 'Alex Morgan, appointment today' },
  { role: 'Super Admin', email: 'superadmin@demo.medflow.ai', note: 'Knowledge base, RAG debugger, audit' },
  { role: 'Nurse', email: 'nurse@demo.medflow.ai', note: 'Wards, beds and queue' },
  { role: 'Receptionist', email: 'reception@demo.medflow.ai', note: 'Registration and check-in' },
]

export default function Login() {
  const { user, loading, login, register } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [form, setForm] = useState({ email: '', password: '', full_name: '', date_of_birth: '', gender: 'Female' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [banner, setBanner] = useState('')
  const [pending, setPending] = useState<string | null>(null)

  if (!loading && user) return <Navigate to={user.home} replace />
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const finish = async (action: () => Promise<{ home: string }>, tag: string) => {
    setPending(tag); setBanner(''); setErrors({})
    try {
      const signedIn = await action()
      const from = (location.state as { from?: string } | null)?.from
      navigate(from && from.startsWith(signedIn.home.split('/').slice(0, 2).join('/')) ? from : signedIn.home, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.details?.length) setErrors(Object.fromEntries(err.details.map((d) => [d.field, d.message])))
      setBanner(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setPending(null)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!/^\S+@\S+\.\S+$/.test(form.email)) local.email = 'Enter a valid email address'
    if (!form.password) local.password = 'Enter your password'
    if (mode === 'register') {
      if (form.full_name.trim().length < 2) local.full_name = 'Enter your full name'
      if (!form.date_of_birth) local.date_of_birth = 'Enter your date of birth'
      if (form.password.length < 8 || !/[A-Za-z]/.test(form.password) || !/\d/.test(form.password)) local.password = 'At least 8 characters, with a letter and a number'
    }
    if (Object.keys(local).length) return setErrors(local)
    finish(() => (mode === 'login' ? login(form.email, form.password) : register(form)), 'form')
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1.05fr]">
      <div className="flex flex-col px-5 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Link to="/" aria-label="MedFlow AI home"><Logo className="text-lg" /></Link>
          <ThemeToggle />
        </div>
        <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">
          <h1 className="text-2xl font-semibold">{mode === 'login' ? 'Sign in' : 'Create a patient account'}</h1>
          <p className="mt-1.5 text-sm text-muted">
            {mode === 'login' ? 'Access your hospital workspace or patient portal.' : 'Book appointments, join queues and view your records.'}
          </p>
          <form onSubmit={submit} noValidate className="mt-6 space-y-4">
            {banner && <p role="alert" className="rounded-lg bg-crit-soft px-3 py-2.5 text-sm text-crit">{banner}</p>}
            {mode === 'register' && <>
              <Input label="Full name" autoComplete="name" value={form.full_name} onChange={set('full_name')} error={errors.full_name} />
              <div className="grid grid-cols-2 gap-3">
                <Input label="Date of birth" type="date" value={form.date_of_birth} onChange={set('date_of_birth')} error={errors.date_of_birth} />
                <Select label="Gender" value={form.gender} onChange={set('gender')}><option>Female</option><option>Male</option><option>Other</option></Select>
              </div>
            </>}
            <Input label="Email" type="email" autoComplete="email" value={form.email} onChange={set('email')} error={errors.email} />
            <Input label="Password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={form.password} onChange={set('password')} error={errors.password} maxLength={72} />
            <Button type="submit" variant="primary" className="w-full" loading={pending === 'form'}>{mode === 'login' ? 'Sign in' : 'Create account'}</Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted">
            {mode === 'login' ? 'New patient? ' : 'Already registered? '}
            <button onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setErrors({}); setBanner('') }} className="font-medium text-brand hover:underline">
              {mode === 'login' ? 'Create an account' : 'Sign in'}
            </button>
          </p>
        </main>
        <p className="flex items-start gap-2 text-xs text-subtle">
          <ShieldCheck className="mt-px size-3.5 shrink-0" aria-hidden />
          This prototype demonstrates privacy-conscious architecture and is not certified for production clinical use.
        </p>
      </div>

      <aside className="border-t bg-surface px-5 py-8 sm:px-10 lg:border-t-0 lg:border-l lg:py-16" aria-label="Demo accounts">
        <div className="mx-auto max-w-md">
          <p className="text-xs font-medium tracking-wide text-brand uppercase">Demo hospital</p>
          <h2 className="mt-1.5 text-lg font-semibold">Explore with a demo account</h2>
          <p className="mt-1 text-sm text-muted">
            Every role sees a different product. All accounts use the password <code className="rounded bg-surface-2 px-1.5 py-0.5 text-[13px]">{DEMO_PASSWORD}</code>. All data is synthetic.
          </p>
          <div className="mt-5 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            {DEMO_ACCOUNTS.map((a) => (
              <Card key={a.email} className="p-0">
                <button disabled={!!pending} onClick={() => finish(() => login(a.email, DEMO_PASSWORD), a.email)}
                  className="w-full rounded-xl p-3.5 text-left hover:bg-surface-2 disabled:opacity-60">
                  <span className="flex items-center justify-between text-sm font-semibold">{a.role}
                    <span className="text-xs font-medium text-brand">{pending === a.email ? 'Signing in…' : 'Sign in →'}</span></span>
                  <span className="mt-0.5 block truncate text-xs text-muted">{a.email}</span>
                  <span className="mt-1.5 block text-xs text-subtle">{a.note}</span>
                </button>
              </Card>
            ))}
          </div>
        </div>
      </aside>
    </div>
  )
}
