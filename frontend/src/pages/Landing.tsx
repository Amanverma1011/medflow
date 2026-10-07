import { motion } from 'framer-motion'
import {
  Activity, ArrowRight, BarChart3, BedDouble, BookOpen, CalendarCheck, FileSearch, HeartPulse, Lock, MessageSquareHeart,
  Radar, ShieldCheck, Sparkles, Users,
} from 'lucide-react'
import { Link } from 'react-router'
import { Badge, Card, DemoTag } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { Logo, ThemeToggle } from '@/layouts/Layouts'

const CTA = 'inline-flex h-11 items-center justify-center gap-2 rounded-lg px-5 text-sm font-medium transition-colors'
const reveal = { initial: { opacity: 0, y: 14 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true, margin: '-60px' }, transition: { duration: 0.4 } }

const PILLARS = [
  { id: 'operations', icon: Radar, title: 'Operations Intelligence', body: 'One live view of patient flow, queues, doctor availability, beds and emergency load. Detectors surface bottlenecks with the evidence behind them.',
    points: ['Command center', 'Bed and ward map', 'Doctor utilization'] },
  { id: 'experience', icon: HeartPulse, title: 'Patient Experience', body: 'Patients book, reschedule, check in from their phone and watch a live queue position with an explained wait estimate.',
    points: ['Digital queue tokens', 'Appointment self-service', 'Feedback with AI classification'] },
  { id: 'assistant', icon: MessageSquareHeart, title: 'AI Medical Assistant', body: 'A retrieval-augmented assistant that answers only from hospital-approved documents, cites every claim, and escalates emergencies instead of advising.',
    points: ['Hybrid vector + keyword retrieval', 'Clickable citations', 'Safety classification'] },
  { id: 'analytics', icon: BarChart3, title: 'Real-Time Analytics', body: 'Seven analytics views and an Operations Copilot that turns a plain-English question into validated, read-only SQL and shows its work.',
    points: ['Natural-language analytics', 'Explainable predictions', 'CSV and PDF reports'] },
]
const SECURITY = [
  { icon: Lock, title: 'Role-based access', body: 'Six roles and a permission matrix enforced on every API route. Administrators run operations without seeing clinical notes.' },
  { icon: FileSearch, title: 'Audit trail', body: 'Sign-ins, record views, exports and knowledge changes are logged without storing clinical content.' },
  { icon: ShieldCheck, title: 'Guarded AI', body: 'Generated SQL runs as a SELECT-only database role. Chat answers pass a safety validator before they are shown.' },
]
const STEPS = [
  ['Connect', 'Appointments, queues, beds and feedback live in one PostgreSQL schema with pgvector for the knowledge base.'],
  ['Observe', 'Dashboards and detectors compute every number from live records. Nothing on screen is hard-coded.'],
  ['Explain', 'Predictions arrive with a confidence level and their main contributing factors.'],
  ['Act', 'Recommendations are reviewed by people. The platform never changes staffing or care on its own.'],
]
const IMPACT = [['−12%', 'average wait time'], ['+9%', 'resource utilization'], ['3× faster', 'appointment management'], ['4.6 / 5', 'patient satisfaction']]

function Preview() {
  return (
    <Card className="overflow-hidden shadow-xl" aria-hidden>
      <div className="flex items-center gap-1.5 border-b bg-surface-2 px-3 py-2">
        {[0, 1, 2].map((i) => <span key={i} className="size-2.5 rounded-full bg-border" />)}
        <span className="ml-2 text-[11px] text-subtle">Command Center · illustrative preview</span>
      </div>
      <div className="grid gap-3 p-4 sm:grid-cols-3">
        {[['Patients today', '280', '+8.4%'], ['Avg wait', '23 min', '−12%'], ['Bed occupancy', '72%', '']].map(([label, value, trend]) => (
          <div key={label} className="rounded-lg border p-3">
            <p className="text-[11px] text-muted">{label}</p>
            <p className="mt-1 text-lg font-semibold tabular">{value} <span className="text-xs font-medium text-ok">{trend}</span></p>
          </div>
        ))}
        <div className="rounded-lg border p-3 sm:col-span-2">
          <p className="text-[11px] text-muted">Patient flow</p>
          <svg viewBox="0 0 300 80" className="mt-2 h-20 w-full">
            <polyline fill="none" stroke="var(--series-1)" strokeWidth="2" points="0,62 30,55 60,40 90,28 120,34 150,46 180,40 210,22 240,14 270,26 300,38" />
            <polyline fill="none" stroke="var(--series-3)" strokeWidth="2" points="0,70 30,66 60,58 90,44 120,42 150,52 180,50 210,38 240,30 270,34 300,46" />
          </svg>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-[11px] text-muted">Your queue number</p>
          <p className="mt-1 text-2xl font-semibold tabular">A-047</p>
          <p className="text-[11px] text-subtle">6 ahead · ~32 min</p>
        </div>
        <div className="rounded-lg border border-l-4 border-l-warn p-3 sm:col-span-2">
          <Badge tone="brand" icon={Sparkles}>AI recommendation</Badge>
          <p className="mt-1.5 text-xs font-medium">Emergency inflow surge, 17:00–20:00</p>
          <p className="text-[11px] text-muted">Consider reallocating 1 physician and 2 nurses. Confidence 87%.</p>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-[11px] text-muted">Medical Assistant</p>
          <p className="mt-1 text-[11px]">Hypertension is persistently raised blood pressure <span className="rounded bg-brand-soft px-1 font-semibold text-brand">1</span></p>
        </div>
      </div>
    </Card>
  )
}

export default function Landing() {
  const { user } = useAuth()
  const dashboard = user ? user.home : '/login'
  return (
    <div className="bg-bg">
      <header className="sticky top-0 z-20 border-b bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <Logo className="text-lg" />
          <nav aria-label="Sections" className="hidden gap-5 text-sm text-muted md:flex">
            {PILLARS.map((p) => <a key={p.id} href={`#${p.id}`} className="hover:text-text">{p.title.replace('AI ', '')}</a>)}
            <a href="#security" className="hover:text-text">Security</a>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <Link to={dashboard} className={`${CTA} h-9 bg-brand px-4 text-on-brand hover:bg-brand-strong`}>{user ? 'Open app' : 'Sign in'}</Link>
          </div>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 lg:grid-cols-[1fr_1.05fr] lg:py-20">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
            <DemoTag>Demo platform · synthetic data</DemoTag>
            <h1 className="mt-4 text-4xl leading-[1.08] font-semibold sm:text-5xl">Run a Smarter Hospital.<br /><span className="text-brand">Give Patients a Better Experience.</span></h1>
            <p className="mt-5 max-w-xl text-lg text-muted">MEDFLOW AI connects hospital operations, patient experience, analytics, and medical intelligence in one unified platform.</p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link to={dashboard} className={`${CTA} bg-brand text-on-brand hover:bg-brand-strong`}>Explore Dashboard<ArrowRight className="size-4" aria-hidden /></Link>
              <Link to={user ? (user.roles.includes('patient') ? '/patient/chat' : '/admin/assistant') : '/login'} className={`${CTA} border bg-surface hover:bg-surface-2`}>
                <MessageSquareHeart className="size-4" aria-hidden />Try Medical Assistant</Link>
            </div>
            <p className="mt-5 text-xs text-subtle">The assistant provides general medical information and is not a substitute for professional medical advice, diagnosis, or treatment.</p>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.1 }}><Preview /></motion.div>
        </section>

        <section className="border-y bg-surface">
          <div className="mx-auto grid max-w-6xl gap-px px-4 sm:grid-cols-2">
            {PILLARS.map((p) => (
              <motion.article key={p.id} id={p.id} {...reveal} className="scroll-mt-20 py-10 sm:px-6 sm:odd:pl-0">
                <span className="flex size-10 items-center justify-center rounded-lg bg-brand-soft text-brand"><p.icon className="size-5" aria-hidden /></span>
                <h2 className="mt-4 text-xl font-semibold">{p.title}</h2>
                <p className="mt-2 text-muted">{p.body}</p>
                <ul className="mt-4 flex flex-wrap gap-2">{p.points.map((x) => <li key={x} className="rounded-full border px-3 py-1 text-xs text-muted">{x}</li>)}</ul>
              </motion.article>
            ))}
          </div>
        </section>

        <section id="security" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-16">
          <h2 className="text-2xl font-semibold">Secure by Design</h2>
          <p className="mt-2 max-w-2xl text-muted">Built on minimum-necessary access, auditability and guarded AI from the first table. This prototype demonstrates privacy-conscious architecture and is not certified for production clinical use.</p>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {SECURITY.map((s) => (
              <motion.div key={s.title} {...reveal}><Card className="h-full p-5">
                <s.icon className="size-5 text-brand" aria-hidden />
                <h3 className="mt-3 font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm text-muted">{s.body}</p>
              </Card></motion.div>
            ))}
          </div>
        </section>

        <section className="border-y bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-16">
            <h2 className="text-2xl font-semibold">How It Works</h2>
            <ol className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map(([title, body], i) => (
                <motion.li key={title} {...reveal}>
                  <span className="text-sm font-semibold text-brand tabular">0{i + 1}</span>
                  <h3 className="mt-1 font-semibold">{title}</h3>
                  <p className="mt-1.5 text-sm text-muted">{body}</p>
                </motion.li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-16">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-2xl font-semibold">Hospital Impact</h2>
            <DemoTag>Demo / simulated metrics</DemoTag>
          </div>
          <p className="mt-2 max-w-2xl text-muted">Illustrative targets for a hospital of this size. They are not measured outcomes from a real deployment.</p>
          <dl className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {IMPACT.map(([value, label]) => (
              <Card key={label} className="p-5">
                <dd className="text-3xl font-semibold tabular">{value}</dd>
                <dt className="mt-1 text-sm text-muted">{label}</dt>
              </Card>
            ))}
          </dl>
          <div className="mt-12 flex flex-col items-start justify-between gap-5 rounded-2xl border bg-surface p-6 sm:flex-row sm:items-center sm:p-8">
            <div>
              <h2 className="text-xl font-semibold">See it with a live demo hospital</h2>
              <p className="mt-1 text-sm text-muted">8 departments, 25 doctors, 500+ synthetic patients and a 24-document knowledge base.</p>
            </div>
            <Link to={dashboard} className={`${CTA} shrink-0 bg-brand text-on-brand hover:bg-brand-strong`}>Explore Dashboard<ArrowRight className="size-4" aria-hidden /></Link>
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-6 text-xs text-subtle">
          <Logo className="text-sm text-text" />
          <span>AI-powered hospital operations, patient experience, and medical intelligence.</span>
          <span className="flex items-center gap-4 sm:ml-auto"><Users className="size-3.5" aria-hidden /><BedDouble className="size-3.5" aria-hidden /><CalendarCheck className="size-3.5" aria-hidden /><BookOpen className="size-3.5" aria-hidden /><Activity className="size-3.5" aria-hidden /></span>
        </div>
      </footer>
    </div>
  )
}
