"""Role -> permission matrix. Seeded into roles/permissions/role_permissions; checked on every request."""

PERMISSIONS = [
    "patients:read", "patients:write", "clinical:read", "clinical:write",
    "appointments:read", "appointments:write", "queue:read", "queue:manage",
    "beds:read", "beds:manage", "analytics:read", "experience:read", "insights:read",
    "copilot:use", "reports:read", "staff:read", "settings:read",
    "knowledge:manage", "rag:debug", "audit:read", "users:manage", "demo:load",
    "chat:use", "feedback:write",
]

_ADMIN = ["patients:read", "patients:write", "appointments:read", "appointments:write", "queue:read",
          "queue:manage", "beds:read", "beds:manage", "analytics:read", "experience:read", "insights:read",
          "copilot:use", "reports:read", "staff:read", "settings:read", "chat:use"]

ROLES: dict[str, tuple[str, list[str]]] = {
    "patient": ("Own appointments, queue, documents, feedback and the medical assistant",
                ["chat:use", "feedback:write"]),
    "doctor": ("Clinical workflow for own patients",
               ["patients:read", "clinical:read", "clinical:write", "appointments:read", "appointments:write",
                "queue:read", "queue:manage", "beds:read", "chat:use"]),
    "nurse": ("Ward, bed and queue workflow",
              ["patients:read", "clinical:read", "appointments:read", "queue:read", "queue:manage",
               "beds:read", "beds:manage", "chat:use"]),
    "receptionist": ("Registration, scheduling and check-in",
                     ["patients:read", "patients:write", "appointments:read", "appointments:write",
                      "queue:read", "queue:manage", "chat:use"]),
    # Administrators run operations but do not get clinical content (minimum necessary).
    "administrator": ("Hospital operations, analytics and reporting", _ADMIN),
    "super_admin": ("Everything, including users, audit, knowledge base and AI configuration", PERMISSIONS),
}

STAFF_ROLES = {"doctor", "nurse", "receptionist", "administrator", "super_admin"}
