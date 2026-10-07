import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router'
import { Button, EmptyState, ErrorState, Spinner } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { PatientLayout, StaffLayout } from '@/layouts/Layouts'
import { ApiError } from '@/lib/api'
import type { Role } from '@/types'

// Route-level code splitting: each area loads only when visited.
const Landing = lazy(() => import('@/pages/Landing'))
const Login = lazy(() => import('@/pages/Login'))
const Assistant = lazy(() => import('@/pages/Assistant'))
const Overview = lazy(() => import('@/pages/admin/Overview'))
const CommandCenter = lazy(() => import('@/pages/admin/CommandCenter'))
const Patients = lazy(() => import('@/pages/admin/Patients'))
const PatientProfile = lazy(() => import('@/pages/admin/PatientProfile'))
const Appointments = lazy(() => import('@/pages/admin/Appointments'))
const Queue = lazy(() => import('@/pages/admin/Queue'))
const Directory = lazy(() => import('@/pages/admin/Directory'))
const Beds = lazy(() => import('@/pages/admin/Beds'))
const Analytics = lazy(() => import('@/pages/admin/Analytics'))
const Experience = lazy(() => import('@/pages/admin/Experience'))
const AIInsights = lazy(() => import('@/pages/admin/AIInsights'))
const Reports = lazy(() => import('@/pages/admin/Reports'))
const Knowledge = lazy(() => import('@/pages/admin/Knowledge'))
const RagDebug = lazy(() => import('@/pages/admin/RagDebug'))
const System = lazy(() => import('@/pages/admin/System'))
const DoctorDashboard = lazy(() => import('@/pages/doctor/Dashboard'))
const PatientHome = lazy(() => import('@/pages/patient/Home'))
const PatientAppointments = lazy(() => import('@/pages/patient/Appointments'))
const PatientQueue = lazy(() => import('@/pages/patient/Queue'))
const PatientRecords = lazy(() => import('@/pages/patient/Records'))

const STAFF: Role[] = ['doctor', 'nurse', 'receptionist', 'administrator', 'super_admin']

function FullPageSpinner() {
  return <div className="flex min-h-[60dvh] items-center justify-center"><Spinner className="size-6" /></div>
}

/** Gate by role and, optionally, permission. The API enforces the same rules; this only shapes the UI. */
function Guard({ roles, permission }: { roles?: Role[]; permission?: string }) {
  const { user, loading, can } = useAuth()
  const location = useLocation()
  if (loading) return <FullPageSpinner />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (roles && !roles.some((r) => user.roles.includes(r))) return <Navigate to={user.home} replace />
  if (permission && !can(permission)) return <ErrorState error={new ApiError(403, 'forbidden', '')} what="this page" />
  return <Suspense fallback={<FullPageSpinner />}><Outlet /></Suspense>
}

function HomeRedirect() {
  const { user, loading } = useAuth()
  if (loading) return <FullPageSpinner />
  return user ? <Navigate to={user.home} replace /> : <Navigate to="/login" replace />
}

function NotFound() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <EmptyState title="Page not found" body="The page you're looking for doesn't exist or has moved."
        action={<Button variant="primary" onClick={() => (location.href = '/')}>Back to home</Button>} />
    </div>
  )
}

/** A route that additionally requires one permission. */
const gated = (path: string, permission: string, element: React.ReactNode) => (
  <Route path={path} element={<Guard permission={permission} />}><Route index element={element} /></Route>
)

export function AppRoutes() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />

        <Route element={<Guard roles={['patient']} />}>
          <Route path="/patient" element={<PatientLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={<PatientHome />} />
            <Route path="appointments" element={<PatientAppointments />} />
            <Route path="queue" element={<PatientQueue />} />
            <Route path="chat" element={<Assistant />} />
            <Route path="documents" element={<PatientRecords view="documents" />} />
            <Route path="feedback" element={<PatientRecords view="feedback" />} />
            <Route path="profile" element={<PatientRecords view="profile" />} />
          </Route>
        </Route>

        <Route element={<Guard roles={STAFF} />}>
          <Route element={<StaffLayout />}>
            <Route path="/doctor" element={<Guard roles={['doctor', 'super_admin']} />}>
              <Route index element={<Navigate to="dashboard" replace />} />
              <Route path="dashboard" element={<DoctorDashboard />} />
              <Route path="appointments" element={<Appointments />} />
              <Route path="patients" element={<Patients base="/doctor" />} />
              <Route path="patients/:id" element={<PatientProfile />} />
              <Route path="assistant" element={<Assistant />} />
            </Route>
            <Route path="/admin">
              <Route index element={<HomeRedirect />} />
              {gated('dashboard', 'analytics:read', <Overview />)}
              {gated('command-center', 'analytics:read', <CommandCenter />)}
              {gated('patients', 'patients:read', <Patients base="/admin" />)}
              {gated('patients/:id', 'patients:read', <PatientProfile />)}
              {gated('appointments', 'appointments:read', <Appointments />)}
              {gated('queue', 'queue:read', <Queue />)}
              <Route path="doctors" element={<Directory view="doctors" />} />
              <Route path="departments" element={<Directory view="departments" />} />
              {gated('beds', 'beds:read', <Beds />)}
              {gated('analytics', 'analytics:read', <Analytics />)}
              {gated('experience', 'experience:read', <Experience />)}
              {gated('ai-insights', 'insights:read', <AIInsights />)}
              {gated('reports', 'reports:read', <Reports />)}
              <Route path="assistant" element={<Assistant />} />
              {gated('knowledge', 'knowledge:manage', <Knowledge />)}
              {gated('rag-debug', 'rag:debug', <RagDebug />)}
              {gated('audit', 'audit:read', <System view="audit" />)}
              {gated('settings', 'settings:read', <System view="settings" />)}
            </Route>
          </Route>
        </Route>

        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
