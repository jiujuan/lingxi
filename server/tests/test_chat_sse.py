from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_embedding_task import add_default_embedding_model
from server.tests.test_knowledge_documents_api import login_employee
from server.tests.test_model_config import login_admin
from server.tests.test_retrieval_service import _seed_retrieval_dataset


def _add_default_chat_model(session, tenant_id, response="主管审批。"):
    from server.app.core.secrets import encrypt_secret
    from server.app.models.model_config import ModelConfig, ModelProvider

    provider = ModelProvider(
        tenant_id=tenant_id,
        provider_type="OPENAI_COMPATIBLE",
        name="Fake Chat Provider",
        base_url="mock://success",
        encrypted_api_key=encrypt_secret("sk-chat"),
        status="ACTIVE",
        config={"chatResponse": response},
    )
    session.add(provider)
    session.flush()
    model = ModelConfig(
        tenant_id=tenant_id,
        provider_id=provider.id,
        capability="CHAT",
        model_name="fake-chat",
        max_tokens=1024,
        timeout_ms=30000,
        is_default=True,
        status="ACTIVE",
        config={},
    )
    session.add(model)
    session.commit()
    return model


def _seed_chat_data(SessionLocal):
    from server.app.models.user import Department, Tenant

    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant))
        add_default_embedding_model(session, tenant.id, expected_dimension=4)
        _add_default_chat_model(session, tenant.id)
        _seed_retrieval_dataset(session, {
            "tenant": tenant,
            "departments": {
                department.code.lower(): department
                for department in session.scalars(select(Department)).all()
            },
            "roles": {},
            "users": {},
        })


def test_chat_session_api_and_sse_event_order_persist_messages():
    client, SessionLocal = build_test_client()
    login_admin(client)
    _seed_chat_data(SessionLocal)
    headers = login_employee(client)

    created = client.post("/api/v1/chat/sessions", headers=headers, json={"title": "退款咨询"})
    assert created.status_code == 200
    session_id = created.json()["id"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=headers,
        json={"content": "退款需要谁审批？"},
    )

    assert response.status_code == 200
    text = response.text
    assert "event: run_started" in text
    assert "event: delta" in text
    assert "event: citation" in text
    assert "event: done" in text
    assert text.index("event: run_started") < text.index("event: done")

    messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()["data"]] == ["USER", "ASSISTANT"]

    from server.app.models.chat import ChatMessage, QueryCitation

    with SessionLocal() as session:
        assert session.scalar(select(ChatMessage).where(ChatMessage.role == "ASSISTANT"))
        assert session.scalar(select(QueryCitation))


def test_chat_low_confidence_refuses_without_citation():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    headers = login_employee(client)
    session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=headers,
        json={"content": "火星基地报销制度是什么？"},
    )

    assert response.status_code == 200
    assert "知识库中没有找到足够可靠的信息" in response.text
    assert "event: citation" not in response.text


def test_chat_model_failure_returns_error_event_without_leaking_prompt():
    client, SessionLocal = build_test_client()
    from server.app.models.model_config import ModelProvider

    _seed_chat_data(SessionLocal)
    with SessionLocal() as session:
        provider = session.scalar(select(ModelProvider).where(ModelProvider.name == "Fake Chat Provider"))
        provider.config = {"chatError": "MODEL_TIMEOUT"}
        session.commit()

    headers = login_employee(client)
    session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=headers,
        json={"content": "退款需要谁审批？"},
    )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "参考资料" not in response.text


def test_message_run_returns_404_before_streaming_for_missing_session():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    headers = login_employee(client)

    response = client.post(
        "/api/v1/chat/sessions/does-not-exist/message-runs",
        headers=headers,
        json={"content": "退款需要谁审批？"},
    )

    # The precondition check must run before the 200 event-stream starts.
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_message_run_returns_400_for_whitespace_only_content():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    headers = login_employee(client)
    session_id = client.post(
        "/api/v1/chat/sessions", headers=headers, json={}
    ).json()["id"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=headers,
        json={"content": "    "},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_MESSAGE"


def test_stream_with_heartbeat_injects_comment_during_gaps():
    import time

    from server.app.services.sse_service import SseService

    def slow_source():
        yield "event: run_started\ndata: {}\n\n"
        time.sleep(0.25)  # gap longer than the heartbeat interval
        yield "event: done\ndata: {}\n\n"

    frames = list(SseService().stream_with_heartbeat(slow_source(), interval=0.05))
    text = "".join(frames)

    assert ": heartbeat" in text  # keep-alive emitted during the gap
    assert "event: run_started" in text
    assert "event: done" in text
    # heartbeat lands between the two real events, not after done
    assert text.index("event: run_started") < text.index(": heartbeat")
    assert text.index(": heartbeat") < text.index("event: done")


def test_stream_with_heartbeat_propagates_source_errors():
    import pytest

    from server.app.services.sse_service import SseService

    def failing_source():
        yield "event: run_started\ndata: {}\n\n"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        list(SseService().stream_with_heartbeat(failing_source(), interval=5))


def test_feedback_cannot_mutate_message_from_another_tenant():
    import pytest
    from fastapi import HTTPException

    from server.tests.test_document_permissions import build_session

    session, identity = build_session()
    from server.app.core.permissions import AccessContext
    from server.app.models.chat import ChatMessage, ChatSession
    from server.app.models.user import Tenant
    from server.app.services.chat_service import ChatService

    other_tenant = Tenant(name="Other Tenant")
    session.add(other_tenant)
    session.flush()
    other_session = ChatSession(
        tenant_id=other_tenant.id,
        user_id=None,
        title="Other",
        status="ACTIVE",
    )
    session.add(other_session)
    session.flush()
    other_message = ChatMessage(
        tenant_id=other_tenant.id,
        session_id=other_session.id,
        role="ASSISTANT",
        content="secret",
        status="COMPLETED",
    )
    session.add(other_message)
    session.commit()

    context = AccessContext(
        tenant_id=identity["tenant"].id,
        user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        role_ids=[identity["roles"]["employee"].id],
        permissions={"CHAT_WRITE"},
    )

    with pytest.raises(HTTPException):
        ChatService(session).record_feedback(context, other_message.id, "up")

    session.refresh(other_message)
    assert other_message.status == "COMPLETED"
