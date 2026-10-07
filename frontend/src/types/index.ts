export type Role = 'patient' | 'doctor' | 'nurse' | 'receptionist' | 'administrator' | 'super_admin'

export interface User {
  id: number
  email: string
  full_name: string
  roles: Role[]
  permissions: string[]
  patient_id: number | null
  doctor_id: number | null
  home: string
  profile?: PatientSelfProfile
}

export interface PatientSelfProfile {
  mrn: string; date_of_birth: string; gender: string; phone: string; address: string
  emergency_contact: string; allergies: string; blood_group: string; insurance_provider: string
}

export interface Paged<T> { items: T[]; total: number; page: number; size: number }

export type AppointmentStatus =
  | 'scheduled' | 'checked_in' | 'waiting' | 'in_consultation' | 'completed' | 'cancelled' | 'no_show'

export interface Appointment {
  id: number; scheduled_at: string; duration_minutes: number; status: AppointmentStatus
  appointment_type: string; reason: string; checked_in_at: string | null; started_at: string | null
  completed_at: string | null; patient_id: number; patient: string; mrn: string; doctor_id: number
  doctor: string; room: string; department_id: number; department: string; token: string | null
}

export interface Doctor {
  id: number; name: string; department_id: number; department: string; specialty: string; room: string
  years_experience: number; shift_start: number; shift_end: number; is_available: boolean; on_shift: boolean
  avg_consult_minutes: number; rating: number | null; reviews: number; patients_today: number
}

export interface Department {
  id: number; name: string; code: string; floor: string; location: string; description: string
  open_hour: number; close_hour: number; doctors: number; patients_today: number; waiting: number
  avg_wait_7d: number | null; satisfaction: number | null
}

export interface PatientRow {
  id: number; mrn: string; full_name: string; gender: string; status: string; age: number
  department: string | null; appointment_at: string | null; appointment_status: string | null
  doctor: string | null; last_visit: string | null
}

export interface Factor { name: string; detail: string; weight?: number }

export interface QueueEstimate {
  token: string; status: string; patients_ahead: number; currently_serving: string | null
  estimated_wait_minutes: number; confidence: number; factors: Factor[]; label: string
  doctor?: string; room?: string; department?: string
}

export interface QueueEntry {
  id: number; token: string; status: string; priority: number; patient: string | null; patient_id: number
  appointment_id: number | null; joined_at: string; waited_minutes: number; estimated_wait_minutes: number | null
}

export interface QueueView {
  id: number; doctor_id: number; doctor: string; room: string; department_id: number; department: string
  avg_consult_minutes: number; current: QueueEntry | null; waiting: QueueEntry[]; completed: number
}

export type BedStatus = 'available' | 'occupied' | 'cleaning' | 'maintenance' | 'reserved'

export interface Bed {
  id: number; ward_id: number; label: string; status: BedStatus; patient_id: number | null
  patient: string | null; assigned_at: string | null; expected_discharge_at: string | null
}

export interface Ward {
  id: number; name: string; floor: string; ward_type: string; department: string | null
  beds: Bed[]; occupancy_rate: number
}

export interface Insight {
  id: number; key: string; title: string; description: string; severity: 'low' | 'medium' | 'high' | 'critical'
  category: string; confidence: number; impact: string; recommendation: string
  evidence: { label: string; value: string }[]; created_at: string; label: string
}

export interface Notification {
  id: number; type: string; title: string; body: string; severity: 'info' | 'success' | 'warning' | 'critical'
  link: string; is_read: boolean; created_at: string
}

export interface Source {
  index: number; chunk_id: number; document_id: number; document: string; section: string; page: number
  kb: 'medical' | 'hospital'; version: string; score: number; semantic: number; keyword: number
  snippet: string; cited: boolean
}

export interface ChatMessage {
  id: number | string; role: 'user' | 'assistant'; content: string; sources?: Source[]
  confidence?: number | null; safety_category?: string | null; knowledge_scope?: string | null
  feedback?: number; follow_ups?: string[]; streaming?: boolean; failed?: boolean
}

export interface Metric { value: number | string | null; unit?: string; trend?: number | null; lower_is_better?: boolean }
export interface ChartBlock<T = Record<string, any>> { data: T[]; range: string; metric?: Metric }

export interface CopilotResult {
  intent: string; answer: string; mode: string; note: string
  queries: { title: string; sql: string; params: Record<string, string>; rows: Record<string, any>[] }[]
  chart: { type: 'bar' | 'line'; x: string; series: { key: string; label: string }[] } | null
  data: Record<string, any>[]
}
