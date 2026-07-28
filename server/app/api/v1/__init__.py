from fastapi import APIRouter

from server.app.api.v1 import (
    auth,
    api_keys,
    chat,
    citations,
    dashboard,
    departments,
    documents,
    import_jobs,
    knowledge_categories,
    logs,
    model_config,
    query_runs,
    settings,
    task_runs,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(api_keys.router)
api_router.include_router(departments.router)
api_router.include_router(users.router)
api_router.include_router(model_config.router)
api_router.include_router(import_jobs.router)
api_router.include_router(knowledge_categories.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(query_runs.router)
api_router.include_router(citations.router)
api_router.include_router(logs.router)
api_router.include_router(task_runs.router)
api_router.include_router(dashboard.router)
api_router.include_router(settings.router)
