import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import Assistant from '@/pages/Assistant'
import { AppRoutes } from '@/routes'
import { fail, makeUser, mockApi, renderApp, sessionRoutes } from './helpers'

const sse = (events: [string, unknown][]) =>
  new Response(events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join(''),
    { headers: { 'Content-Type': 'text/event-stream' } })

describe('routing and access', () => {
  it('sends signed-out visitors from a protected route to the login page', async () => {
    mockApi(sessionRoutes(null))
    renderApp(<AppRoutes />, '/admin/patients')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByText(/not certified for production clinical use/)).toBeInTheDocument()
  })

  it('keeps a patient out of the staff area', async () => {
    mockApi({
      ...sessionRoutes(makeUser('patient', ['chat:use'])),
      'GET /api/appointments': { items: [], total: 0, page: 1, size: 20 },
      'GET /api/queues/me': { entry: null, can_check_in: [] },
      'GET /api/patients/me': { visits: [], documents: [], prescriptions: [] },
    })
    renderApp(<AppRoutes />, '/admin/command-center')
    expect(await screen.findByRole('heading', { name: /Alex/ })).toBeInTheDocument() // redirected to the patient home
    expect(await screen.findByText('No upcoming appointments')).toBeInTheDocument()
    expect(screen.queryByText('Command Center')).not.toBeInTheDocument()
  })

  it('hides navigation the role lacks and blocks the page itself', async () => {
    mockApi(sessionRoutes(makeUser('receptionist', ['patients:read', 'appointments:read', 'queue:read'])))
    renderApp(<AppRoutes />, '/admin/audit')
    expect(await screen.findByText("You don't have access")).toBeInTheDocument()
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0]
    expect(within(nav).getByRole('link', { name: 'Queue' })).toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Audit Logs' })).not.toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Analytics' })).not.toBeInTheDocument()
  })

  it('shows a not-found page for unknown routes', async () => {
    mockApi(sessionRoutes(null))
    renderApp(<AppRoutes />, '/nope')
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
  })
})

describe('login form', () => {
  it('validates before calling the API', async () => {
    const calls = mockApi(sessionRoutes(null))
    renderApp(<AppRoutes />, '/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(screen.getByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
    expect(calls.some((c) => c.key === 'POST /api/auth/login')).toBe(false)
  })

  it('shows the server message when credentials are wrong', async () => {
    mockApi({ ...sessionRoutes(null), 'POST /api/auth/login': fail(401, 'Incorrect email or password.') })
    renderApp(<AppRoutes />, '/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'doctor@demo.medflow.ai')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
  })

  it('signs in and lands on the role home', async () => {
    const admin = { ...makeUser('administrator', ['analytics:read']), home: '/admin/doctors' }
    mockApi({
      ...sessionRoutes(null), 'POST /api/auth/login': { access_token: 't', user: admin },
      'GET /api/doctors': [], 'GET /api/departments': [],
    })
    renderApp(<AppRoutes />, '/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'admin@demo.medflow.ai')
    await userEvent.type(screen.getByLabelText('Password'), 'MedFlow#2026')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Doctors & Staff' })).toBeInTheDocument()
  })
})

describe('medical assistant', () => {
  const status = {
    llm_demo: true, embedding_demo: true, documents: 24, suggestions: ['What is hypertension?'],
    disclaimer: 'This AI assistant provides general medical information and is not a substitute for professional medical advice, diagnosis, or treatment.',
    emergency_notice: 'If you believe you are experiencing a medical emergency, contact your local emergency service or seek immediate medical attention.',
  }
  const source = {
    index: 1, chunk_id: 9, document_id: 1, document: 'Hospital Hypertension Guide', section: 'What is hypertension', page: 1,
    kb: 'medical', version: '2.1', score: 1, semantic: 0.32, keyword: 1, snippet: '', cited: true,
  }
  const base = { ...sessionRoutes(makeUser('patient', ['chat:use'])), 'GET /api/rag/status': status, 'GET /api/rag/conversations': [] }

  it('shows the empty state, both disclaimers and the demo-mode label', async () => {
    mockApi(base)
    renderApp(<Assistant />)
    expect(await screen.findByText('Ask the Medical Assistant')).toBeInTheDocument()
    expect(screen.getByText(/not a substitute for professional medical advice/)).toBeInTheDocument()
    expect(screen.getByText(/contact your local emergency service/)).toBeInTheDocument()
    expect(await screen.findByText(/Demo mode/)).toBeInTheDocument()
  })

  it('streams an answer, renders citations and opens the source', async () => {
    const answer = '**Short answer**\n\nHypertension is high blood pressure. [1] [9]'
    const calls = mockApi({
      ...base,
      'POST /api/rag/chat/stream': sse([
        ['meta', { conversation_id: 5, safety_category: 'GENERAL_INFORMATION', knowledge_scope: 'medical', confidence: 0.89, sources: [source] }],
        ['token', { t: '**Short answer**\n\n' }],
        ['token', { t: 'Hypertension is high blood pressure. [1]' }],
        ['done', { conversation_id: 5, message_id: 77, answer, sources: [source], confidence: 0.89, safety_category: 'GENERAL_INFORMATION',
          knowledge_scope: 'medical', follow_ups: ['What does the guide say about symptoms?'] }],
      ]),
      'GET /api/rag/sources/9': {
        chunk_id: 9, section: 'What is hypertension', page: 1,
        content: 'Hypertension is a condition where blood pressure remains consistently above the healthy range.',
        document: { name: 'Hospital Hypertension Guide', kb: 'medical', source_type: 'hospital_guideline', version: '2.1', uploaded_at: '2026-10-01T09:00:00' },
      },
      'POST /api/rag/messages/77/feedback': new Response(null, { status: 204 }),
    })
    renderApp(<Assistant />)
    await userEvent.click(await screen.findByRole('button', { name: 'What is hypertension?' }))

    const message = await screen.findByRole('article', { name: 'Assistant message' })
    const citation = await within(message).findByRole('button', { name: 'Source 1: Hospital Hypertension Guide' })
    expect(calls.find((c) => c.key === 'POST /api/rag/chat/stream')?.body).toEqual({ message: 'What is hypertension?', conversation_id: null })
    expect(within(message).getByText(/Hypertension is high blood pressure/)).toBeInTheDocument()
    expect(within(message).getByText('Medical Information')).toBeInTheDocument()
    expect(within(message).queryByText(/\[9\]/)).not.toBeInTheDocument() // a citation that points at nothing is dropped
    expect(within(message).getByText('Sources')).toBeInTheDocument()

    await userEvent.click(citation)
    expect((await screen.findAllByText(/consistently above the healthy range/)).length).toBeGreaterThan(0)

    await userEvent.click(within(message).getByRole('button', { name: 'Helpful' }))
    await waitFor(() => expect(calls.find((c) => c.key === 'POST /api/rag/messages/77/feedback')?.body).toEqual({ value: 1 }))
    expect(screen.getByRole('button', { name: 'What does the guide say about symptoms?' })).toBeInTheDocument()
  })

  it('renders an emergency escalation distinctly, with no sources', async () => {
    const answer = '**This may be a medical emergency.**\n\nPlease seek immediate medical attention or contact your local emergency service now.'
    mockApi({
      ...base,
      'POST /api/rag/chat/stream': sse([
        ['meta', { conversation_id: 6, safety_category: 'EMERGENCY', knowledge_scope: 'none', confidence: 0, sources: [] }],
        ['token', { t: answer }],
        ['done', { conversation_id: 6, message_id: 78, answer, sources: [], confidence: 0, safety_category: 'EMERGENCY', knowledge_scope: 'none', follow_ups: [] }],
      ]),
    })
    renderApp(<Assistant />)
    await userEvent.type(await screen.findByLabelText(/Ask a healthcare/), 'I have severe chest pain{Enter}')
    const message = await screen.findByRole('article', { name: 'Assistant message' })
    expect(await within(message).findByText('Urgent')).toBeInTheDocument()
    expect(within(message).getByText(/seek immediate medical attention/)).toBeInTheDocument()
    expect(within(message).queryByText('Sources')).not.toBeInTheDocument()
  })

  it('recovers when the request is rejected, and lets the user try again', async () => {
    mockApi({ ...base, 'POST /api/rag/chat/stream': fail(429, 'Too many requests. Please slow down and try again shortly.') })
    renderApp(<Assistant />)
    await userEvent.type(await screen.findByLabelText(/Ask a healthcare/), 'What is asthma?{Enter}')
    expect(await screen.findByText(/Too many requests/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Ask a healthcare/)).toBeEnabled()
  })
})
