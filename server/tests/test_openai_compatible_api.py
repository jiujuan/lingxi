from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_chat_sse import _seed_chat_data
from server.tests.test_model_config import login_admin


def _create_api_key(client, headers, scopes=None, rate_limit=20, departments=None):
    response = client.post(
        "/api/v1/api-keys",
        headers=headers,
        json={
            "name": "OpenAI Client",
            "scopes": scopes or ["chat:completions"],
            "allowedDepartmentIds": departments or [],
            "allowedRoleIds": [],
            "rateLimitPerMinute": rate_limit,
        },
    )
    assert response.status_code == 200
    return response.json()


def _chat_payload(content: str, stream: bool = False):
    return {
        "model": "knowledge-chat",
        "messages": [{"role": "user", "content": content}],
        "stream": stream,
    }


def test_openai_chat_completions_non_stream_returns_choices_citations_and_logs():
    from server.app.models.api_key import ApiCallLog

    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    admin_headers = login_admin(client)
    api_key = _create_api_key(client, admin_headers)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("退款需要谁审批？"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert "主管审批" in body["choices"][0]["message"]["content"]
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["citations"][0]["title"] == "Refund SOP"
    assert body["citations"][0]["rank"] == 1
    assert body["request_id"].startswith("req_")

    with SessionLocal() as session:
        log = session.scalar(select(ApiCallLog).where(ApiCallLog.path == "/v1/chat/completions"))

    assert log is not None
    assert log.status_code == 200
    assert log.key_prefix == api_key["keyPrefix"]
    assert "Authorization" not in str(log.request_metadata)
    assert api_key["key"] not in str(log.request_metadata)


def test_openai_chat_completions_stream_returns_chunks_citation_and_done():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    admin_headers = login_admin(client)
    api_key = _create_api_key(client, admin_headers)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("退款需要谁审批？", stream=True),
    )

    assert response.status_code == 200
    text = response.text
    assert '"object": "chat.completion.chunk"' in text
    assert '"delta": {"content":' in text
    assert '"type": "citation"' in text
    assert "data: [DONE]" in text


def test_openai_chat_completions_refuses_when_knowledge_is_insufficient():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    admin_headers = login_admin(client)
    api_key = _create_api_key(client, admin_headers)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("火星基地报销制度是什么？"),
    )

    assert response.status_code == 200
    body = response.json()
    assert "知识库中没有找到足够可靠的信息" in body["choices"][0]["message"]["content"]
    assert body["citations"] == []


def test_openai_chat_completions_api_key_scope_and_rate_limit_errors():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    admin_headers = login_admin(client)
    forbidden_key = _create_api_key(client, admin_headers, scopes=["chat:read"])

    forbidden = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {forbidden_key['key']}"},
        json=_chat_payload("退款需要谁审批？"),
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "API_KEY_FORBIDDEN"

    limited_key = _create_api_key(client, admin_headers, rate_limit=1)
    first = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {limited_key['key']}"},
        json=_chat_payload("退款需要谁审批？"),
    )
    second = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {limited_key['key']}"},
        json=_chat_payload("退款需要谁审批？"),
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"


def test_openai_chat_completions_api_key_department_scope_filters_citations():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    admin_headers = login_admin(client)

    from server.app.models.user import Department

    with SessionLocal() as session:
        private_department = session.scalar(
            select(Department).where(Department.code == "PRIVATE")
        )

    api_key = _create_api_key(
        client,
        admin_headers,
        departments=[private_department.id],
    )

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("已开票订单退款前要做什么？"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["citations"] == []
    assert "知识库中没有找到足够可靠的信息" in body["choices"][0]["message"]["content"]


def test_openai_chat_completions_api_key_allows_any_configured_department():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    admin_headers = login_admin(client)

    from server.app.models.user import Department

    with SessionLocal() as session:
        departments = {
            item.code: item.id
            for item in session.scalars(select(Department)).all()
        }

    api_key = _create_api_key(
        client,
        admin_headers,
        departments=[departments["PRIVATE"], departments["SUPPORT"]],
    )

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key['key']}"},
        json=_chat_payload("已开票订单退款前要做什么？"),
    )

    assert response.status_code == 200
    assert response.json()["citations"][0]["title"] == "Invoice SOP"
