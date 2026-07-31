from base64 import b64encode

from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_chat_sse import _add_default_chat_model
from server.tests.test_embedding_task import add_default_embedding_model
from server.tests.test_knowledge_documents_api import login_employee
from server.tests.test_model_config import login_admin


def test_knowledge_import_to_ready_chat_citation_and_openai_api(monkeypatch, tmp_path):
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)

    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.services import import_service

    storage = LocalObjectStorage(tmp_path)
    monkeypatch.setattr(import_service, "get_storage_adapter", lambda: storage)
    monkeypatch.setattr(import_service, "enqueue_parse_task", lambda _job_id: None)

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        _add_default_qa_model(session, tenant_id)
        add_default_embedding_model(session, tenant_id, expected_dimension=4)
        _add_default_chat_model(session, tenant_id, response="退款需要主管审批。")

    job = client.post(
        "/api/v1/import-jobs",
        headers=admin_headers,
        json={
            "title": "Refund SOP",
            "permission": {"allAuthenticated": True},
            "parseOptions": {"preferredParser": "LIGHTWEIGHT"},
            "processingOptions": {"enableQaSplit": True, "enableEmbedding": True},
        },
    ).json()
    bind = client.post(
        f"/api/v1/import-jobs/{job['id']}/files",
        headers=admin_headers,
        json={
            "objectKey": "seed/refund-sop.md",
            "fileName": "refund-sop.md",
            "mimeType": "text/markdown",
            "fileSize": 50,
            "checksum": "sha256:refund-e2e",
            "contentBase64": b64encode("# 退款流程\n\n退款需要主管审批。".encode("utf-8")).decode("ascii"),
        },
    )
    assert bind.status_code == 201

    _run_import_pipeline(SessionLocal, storage, job["id"])

    document = client.get(f"/api/v1/documents/{job['documentId']}", headers=admin_headers)
    assert document.status_code == 200
    assert document.json()["status"] == "READY"
    assert document.json()["qaPairCount"] == 1

    employee_headers = login_employee(client)
    session_id = client.post(
        "/api/v1/chat/sessions", headers=employee_headers, json={"title": "退款咨询"}
    ).json()["id"]
    chat = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=employee_headers,
        json={"content": "退款需要谁审批？"},
    )
    assert chat.status_code == 200
    assert "event: citation" in chat.text
    assert "退款需要主管审批" in chat.text

    api_key = _create_openai_key(client, admin_headers)
    non_stream = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("退款需要谁审批？", stream=False),
    )
    assert non_stream.status_code == 200
    assert non_stream.json()["citations"][0]["title"] == "Refund SOP"
    assert non_stream.json()["request_id"].startswith("req_")

    stream = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("退款需要谁审批？", stream=True),
    )
    assert stream.status_code == 200
    assert '"type": "citation"' in stream.text
    assert "data: [DONE]" in stream.text


def test_permission_isolation_refusal_and_api_key_lifecycle():
    client, SessionLocal = build_test_client()
    from server.tests.test_chat_sse import _seed_chat_data

    _seed_chat_data(SessionLocal)
    admin_headers = login_admin(client)
    employee_headers = login_employee(client)

    session_id = client.post(
        "/api/v1/chat/sessions", headers=employee_headers, json={}
    ).json()["id"]
    private_answer = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=employee_headers,
        json={"content": "工资表在哪里？"},
    )
    assert private_answer.status_code == 200
    assert "Private Payroll" not in private_answer.text
    assert "工资表在财务私有目录" not in private_answer.text

    no_answer = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=employee_headers,
        json={"content": "火星基地报销制度是什么？"},
    )
    assert no_answer.status_code == 200
    assert "知识库中没有找到足够可靠的信息" in no_answer.text
    assert "event: citation" not in no_answer.text

    api_key = _create_openai_key(client, admin_headers, rate_limit=20)
    ok = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("退款需要谁审批？"),
    )
    assert ok.status_code == 200

    disabled = client.post(
        f"/api/v1/api-keys/{api_key['id']}/disable", headers=admin_headers
    )
    assert disabled.status_code == 200
    disabled_call = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("退款需要谁审批？"),
    )
    assert disabled_call.status_code == 401

    rotated = client.post(
        f"/api/v1/api-keys/{api_key['id']}/rotations", headers=admin_headers
    ).json()
    old_key = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("退款需要谁审批？"),
    )
    new_key = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {rotated['key']}"},
        json=_chat_payload("退款需要谁审批？"),
    )
    assert old_key.status_code == 401
    assert new_key.status_code == 200


def test_logs_link_request_run_and_task_identifiers(monkeypatch, tmp_path):
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)

    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.models.chat import QueryRun
    from server.app.models.logs import TaskRun
    from server.app.models.model_config import ModelCallLog
    from server.app.services import import_service

    storage = LocalObjectStorage(tmp_path)
    monkeypatch.setattr(import_service, "get_storage_adapter", lambda: storage)
    monkeypatch.setattr(import_service, "enqueue_parse_task", lambda _job_id: None)

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        _add_default_qa_model(session, tenant_id)
        add_default_embedding_model(session, tenant_id, expected_dimension=4)
        _add_default_chat_model(session, tenant_id, response="退款需要主管审批。")

    job = client.post(
        "/api/v1/import-jobs",
        headers=admin_headers,
        json={"title": "Refund Logs", "permission": {"allAuthenticated": True}},
    ).json()
    client.post(
        f"/api/v1/import-jobs/{job['id']}/files",
        headers=admin_headers,
        json={
            "objectKey": "seed/refund-logs.md",
            "fileName": "refund-logs.md",
            "mimeType": "text/markdown",
            "fileSize": 50,
            "checksum": "sha256:refund-logs",
            "contentBase64": b64encode("# 退款流程\n\n退款需要主管审批。".encode("utf-8")).decode("ascii"),
        },
    )
    _run_import_pipeline(SessionLocal, storage, job["id"])

    with SessionLocal() as session:
        task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job["id"]))
        task_run_id = task_run.id

    task_logs = client.get(
        f"/api/v1/logs/task-runs?taskRunId={task_run_id}", headers=admin_headers
    )
    assert task_logs.status_code == 200
    assert task_logs.json()["data"][0]["id"] == task_run_id

    employee_headers = login_employee(client)
    session_id = client.post(
        "/api/v1/chat/sessions", headers=employee_headers, json={}
    ).json()["id"]
    chat = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=employee_headers,
        json={"content": "退款需要谁审批？"},
    )
    assert chat.status_code == 200

    with SessionLocal() as session:
        run = session.scalar(select(QueryRun).order_by(QueryRun.created_at.desc()))
        session.add(
            ModelCallLog(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                capability="CHAT",
                status="SUCCESS",
                latency_ms=25,
                token_usage={"prompt": 10, "completion": 5},
                request_id=run.request_id,
            )
        )
        session.commit()
        run_id = run.run_id
        request_id = run.request_id

    by_request = client.get(
        f"/api/v1/logs/model-calls?requestId={request_id}", headers=admin_headers
    )
    by_run = client.get(f"/api/v1/logs/model-calls?runId={run_id}", headers=admin_headers)
    assert by_request.status_code == 200
    assert by_request.json()["data"][0]["requestId"] == request_id
    assert by_run.status_code == 200
    assert by_run.json()["data"][0]["runId"] == run_id


def _run_import_pipeline(SessionLocal, storage, job_id: str) -> None:
    from server.app.services.document_parse_service import DocumentParseService
    from server.app.services.embedding_service import EmbeddingService
    from server.app.services.qa_split_service import QaSplitService

    with SessionLocal() as session:
        DocumentParseService(session, storage=storage).parse_import_job(job_id)
        QaSplitService(session).split_import_job(job_id)
        EmbeddingService(session).embed_import_job(job_id)


def _add_default_qa_model(session, tenant_id: str) -> None:
    from server.app.core.secrets import encrypt_secret
    from server.app.models.model_config import ModelConfig, ModelProvider

    provider = ModelProvider(
        tenant_id=tenant_id,
        provider_type="OPENAI_COMPATIBLE",
        name="Fake QA Provider",
        base_url="mock://success",
        encrypted_api_key=encrypt_secret("sk-qa"),
        status="ACTIVE",
        config={
            "qaSplitResponse": {
                "items": [
                    {
                        "question": "退款需要谁审批？",
                        "answer": "退款需要主管审批。",
                        "quote": "退款需要主管审批。",
                        "pageNo": 1,
                        "chunkIndex": 0,
                    }
                ],
                "coveredChunkIndexes": [0],
                "skippedChunks": [],
            }
        },
    )
    session.add(provider)
    session.flush()
    session.add(
        ModelConfig(
            tenant_id=tenant_id,
            provider_id=provider.id,
            capability="QA_SPLIT",
            model_name="fake-qa",
            is_default=True,
            status="ACTIVE",
            config={},
        )
    )
    session.commit()


def _create_openai_key(client, headers, rate_limit=20):
    response = client.post(
        "/api/v1/api-keys",
        headers=headers,
        json={
            "name": "E2E Client",
            "scopes": ["chat:completions"],
            "rateLimitPerMinute": rate_limit,
        },
    )
    assert response.status_code == 200
    return response.json()


def _chat_payload(content: str, stream: bool = False) -> dict:
    return {
        "model": "knowledge-chat",
        "messages": [{"role": "user", "content": content}],
        "stream": stream,
    }


def _tenant_id(session) -> str:
    from server.app.models.user import Tenant

    return session.scalar(select(Tenant.id))
