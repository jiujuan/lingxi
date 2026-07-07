from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.core.config import settings
from server.app.core.security import hash_password
import server.app.db.base  # noqa: F401  (registers all models before model imports)
from server.app.models.permission import Permission
from server.app.models.role import Role, RolePermission, UserRole
from server.app.models.user import Department, Tenant, User

SYSTEM_PERMISSIONS = [
    "DASHBOARD_READ",
    "DOCUMENT_READ",
    "DOCUMENT_UPLOAD",
    "DOCUMENT_WRITE",
    "DOCUMENT_DELETE",
    "DOCUMENT_PERMISSION_WRITE",
    "QA_PAIR_READ",
    "QA_PAIR_REGENERATE",
    "CHAT_READ",
    "CHAT_WRITE",
    "RETRIEVAL_EXPLAIN_READ",
    "MODEL_CONFIG_READ",
    "MODEL_CONFIG_WRITE",
    "API_KEY_READ",
    "API_KEY_WRITE",
    "LOG_READ",
    "TASK_RETRY",
    "USER_READ",
    "USER_WRITE",
    "ROLE_READ",
    "ROLE_WRITE",
    "SETTING_READ",
    "SETTING_WRITE",
    "AUDIT_READ",
]

ROLE_PERMISSION_MAP = {
    "SYSTEM_ADMIN": SYSTEM_PERMISSIONS,
    "KNOWLEDGE_ADMIN": [
        "DASHBOARD_READ",
        "DOCUMENT_READ",
        "DOCUMENT_UPLOAD",
        "DOCUMENT_WRITE",
        "DOCUMENT_PERMISSION_WRITE",
        "QA_PAIR_READ",
        "QA_PAIR_REGENERATE",
        "TASK_RETRY",
        "LOG_READ",
    ],
    "EMPLOYEE": ["DOCUMENT_READ", "CHAT_READ", "CHAT_WRITE"],
}


def seed_identity_data(session: Session) -> dict:
    existing = session.scalar(select(Tenant).where(Tenant.name == settings.seed_tenant_name))
    if existing:
        return _identity_snapshot(session, existing)

    tenant = Tenant(name=settings.seed_tenant_name)
    session.add(tenant)
    session.flush()

    support = Department(tenant_id=tenant.id, name="Support", code="SUPPORT")
    private = Department(tenant_id=tenant.id, name="Private", code="PRIVATE")
    session.add_all([support, private])
    session.flush()

    permissions = {}
    for code in SYSTEM_PERMISSIONS:
        module, _, action = code.partition("_")
        permission = Permission(code=code, module=module, action=action or "ACCESS")
        permissions[code] = permission
        session.add(permission)
    session.flush()

    roles = {
        "system_admin": Role(
            tenant_id=tenant.id, code="SYSTEM_ADMIN", name="系统管理员"
        ),
        "knowledge_admin": Role(
            tenant_id=tenant.id, code="KNOWLEDGE_ADMIN", name="知识库管理员"
        ),
        "employee": Role(tenant_id=tenant.id, code="EMPLOYEE", name="员工"),
    }
    session.add_all(roles.values())
    session.flush()

    for role in roles.values():
        for permission_code in ROLE_PERMISSION_MAP[role.code]:
            session.add(
                RolePermission(
                    role_id=role.id, permission_id=permissions[permission_code].id
                )
            )

    users = {
        "admin": User(
            tenant_id=tenant.id,
            department_id=support.id,
            email=settings.seed_admin_email,
            name="Admin",
            password_hash=hash_password(settings.seed_admin_password),
        ),
        "employee": User(
            tenant_id=tenant.id,
            department_id=support.id,
            email=settings.seed_employee_email,
            name="Employee",
            password_hash=hash_password(settings.seed_employee_password),
        ),
    }
    session.add_all(users.values())
    session.flush()
    session.add_all(
        [
            UserRole(user_id=users["admin"].id, role_id=roles["system_admin"].id),
            UserRole(user_id=users["employee"].id, role_id=roles["employee"].id),
        ]
    )
    session.commit()
    return _identity_snapshot(session, tenant)


def _identity_snapshot(session: Session, tenant: Tenant) -> dict:
    departments = {
        department.code.lower(): department
        for department in session.scalars(
            select(Department).where(Department.tenant_id == tenant.id)
        )
    }
    roles = {
        role.code.lower().replace("system_", "system_").replace("knowledge_", "knowledge_"): role
        for role in session.scalars(select(Role).where(Role.tenant_id == tenant.id))
    }
    users = {
        user.email.split("@")[0]: user
        for user in session.scalars(select(User).where(User.tenant_id == tenant.id))
    }
    return {
        "tenant": tenant,
        "departments": departments,
        "roles": {
            "system_admin": next(role for role in roles.values() if role.code == "SYSTEM_ADMIN"),
            "knowledge_admin": next(role for role in roles.values() if role.code == "KNOWLEDGE_ADMIN"),
            "employee": next(role for role in roles.values() if role.code == "EMPLOYEE"),
        },
        "users": users,
    }
