from base64 import b64encode
import json
import re
import time

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


def test_qa_split_long_running_fixture_reaches_ready_after_slow_success_and_split(
    monkeypatch, tmp_path
):
    """Exercise the full parse -> QA checkpoint -> embedding fixture path.

    The slow provider uses a short wall-clock delay so the acceptance test
    remains practical. The recorded call log still proves that a non-zero
    read-window delay completed without replaying a successful batch.
    """

    from server.app.integrations.model_providers.base import ProviderError
    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.model_config import ModelCallLog
    from server.app.models.qa_pair import QaPair
    from server.app.models.qa_split_run import QaSplitBatch, QaSplitRun
    from server.app.services import import_service

    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    storage = LocalObjectStorage(tmp_path)
    monkeypatch.setattr(import_service, "get_storage_adapter", lambda: storage)

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        _add_default_qa_model(session, tenant_id)
        add_default_embedding_model(session, tenant_id, expected_dimension=4)
        session.commit()

    class FixtureQaProvider:
        provider_type = "OPENAI_COMPATIBLE"
        last_endpoint = "fixture://qa-split/chat/completions"

        def __init__(
            self,
            *,
            model_name: str,
            slow_delay_seconds: float = 0.03,
        ):
            self.model_name = model_name
            self.slow_delay_seconds = slow_delay_seconds
            self.calls: list[dict] = []

        def generate_qa_pairs(self, prompt: str) -> str:
            indexes = [int(value) for value in re.findall(r"chunkIndex=(\d+)", prompt)]
            self.calls.append({"chunkIndexes": indexes, "promptLength": len(prompt)})
            if len(indexes) == 6:
                raise ProviderError(
                    "PROVIDER_INFERENCE_TIMEOUT",
                    "fixture 模型读取空闲超时",
                    retryable=True,
                    provider_name="Fixture QA Gateway",
                    provider_type=self.provider_type,
                    model_name=self.model_name,
                    endpoint=self.last_endpoint,
                    timeout_ms=240000,
                    timeout_phase="read",
                )
            if len(indexes) <= 2:
                time.sleep(self.slow_delay_seconds)
            return json.dumps(
                {
                    "items": [
                        {
                            "question": f"团队 {index} 的审批负责人是谁？",
                            "answer": f"团队 {index} 的审批负责人是团队 {index}。",
                            "quote": (
                                f"This is fact number {index}. "
                                f"The approval owner is team {index}."
                            ),
                            "pageNo": 1,
                            "chunkIndex": index,
                        }
                        for index in indexes
                    ],
                    "coveredChunkIndexes": indexes,
                    "skippedChunks": [],
                },
                ensure_ascii=False,
            )

    def create_markdown_job(title: str, body: str, checksum: str) -> dict:
        job = client.post(
            "/api/v1/import-jobs",
            headers=admin_headers,
            json={
                "title": title,
                "permission": {"allAuthenticated": True},
                "parseOptions": {"preferredParser": "LIGHTWEIGHT"},
                "processingOptions": {
                    "enableQaSplit": True,
                    "enableEmbedding": True,
                },
            },
        ).json()
        response = client.post(
            f"/api/v1/import-jobs/{job['id']}/files",
            headers=admin_headers,
            json={
                "objectKey": f"seed/{checksum}.md",
                "fileName": f"{checksum}.md",
                "mimeType": "text/markdown",
                "fileSize": len(body.encode("utf-8")),
                "checksum": f"sha256:{checksum}",
                "contentBase64": b64encode(body.encode("utf-8")).decode("ascii"),
            },
        )
        assert response.status_code == 201
        return job

    slow_provider = FixtureQaProvider(model_name="fixture-qa-slow")
    slow_job = create_markdown_job(
        "Slow QA fixture",
        "\n\n".join(
            [
                f"# Slow section {index}\n\n"
                f"This is fact number {index}. The approval owner is team {index}."
                for index in range(2)
            ]
        ),
        "slow-qa-fixture",
    )
    _run_import_pipeline(
        SessionLocal,
        storage,
        slow_job["id"],
        qa_provider_factory=lambda *_args, **_kwargs: slow_provider,
        qa_service_kwargs={"max_retries": 0, "max_split_depth": 1},
    )

    split_body = "\n\n".join(
        [
            f"# Section {index}\n\n"
            f"This is fact number {index}. The approval owner is team {index}."
            for index in range(6)
        ]
    )
    split_provider = FixtureQaProvider(model_name="fixture-qa-split")
    split_job = create_markdown_job(
        "Split QA fixture", split_body, "split-qa-fixture"
    )
    _run_import_pipeline(
        SessionLocal,
        storage,
        split_job["id"],
        qa_provider_factory=lambda *_args, **_kwargs: split_provider,
        qa_service_kwargs={"max_retries": 0, "max_split_depth": 1},
    )

    with SessionLocal() as session:
        slow_document = session.get(Document, slow_job["documentId"])
        slow_import_job = session.get(ImportJob, slow_job["id"])
        split_document = session.get(Document, split_job["documentId"])
        split_import_job = session.get(ImportJob, split_job["id"])
        assert slow_document is not None and slow_import_job is not None
        assert split_document is not None and split_import_job is not None
        assert slow_document.status == DocumentStatus.READY, (
            slow_document.status,
            slow_document.last_error_code,
            slow_document.last_error_message,
            slow_import_job.status,
            slow_import_job.error_code,
            slow_import_job.error_message,
        )
        assert slow_import_job.status == "COMPLETED"
        assert split_document.status == DocumentStatus.READY
        assert split_import_job.status == "COMPLETED"

        slow_logs = session.scalars(
            select(ModelCallLog)
            .where(ModelCallLog.model_name_snapshot == slow_provider.model_name)
            .order_by(ModelCallLog.created_at)
        ).all()
        assert len(slow_logs) == 1
        assert slow_logs[0].status == "SUCCESS"
        assert slow_logs[0].timeout_phase is None
        assert slow_logs[0].latency_ms >= 20

        split_run = session.scalar(
            select(QaSplitRun)
            .where(QaSplitRun.job_id == split_job["id"])
        )
        assert split_run is not None
        assert split_run.status == "COMPLETED"
        split_batches = session.scalars(
            select(QaSplitBatch)
            .where(QaSplitBatch.run_id == split_run.id)
            .order_by(QaSplitBatch.batch_index)
        ).all()
        assert len(split_batches) == 1
        assert split_batches[0].status == "SUCCESS"
        assert split_batches[0].chunk_indexes == [0, 1, 2, 3, 4, 5]

        split_logs = session.scalars(
            select(ModelCallLog)
            .where(ModelCallLog.run_id == split_run.task_run_id)
            .order_by(ModelCallLog.created_at)
        ).all()
        assert [log.batch_index for log in split_logs] == ["0", "0.0", "0.1"]
        assert split_logs[0].status == "FAILED"
        assert split_logs[0].error_code == "PROVIDER_INFERENCE_TIMEOUT"
        assert [log.status for log in split_logs[1:]] == ["SUCCESS", "SUCCESS"]
        assert all(log.timeout_phase == "read" for log in split_logs[:1])

        split_pairs = session.scalars(
            select(QaPair)
            .where(QaPair.document_id == split_job["documentId"])
            .order_by(QaPair.pair_index)
        ).all()
        assert [pair.qa_metadata["sourceChunkIndex"] for pair in split_pairs] == list(
            range(6)
        )


def test_qa_split_structure_error_is_terminal_and_keeps_active_pairs(
    monkeypatch, tmp_path
):
    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.model_config import ModelCallLog
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services import import_service

    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    storage = LocalObjectStorage(tmp_path)
    monkeypatch.setattr(import_service, "get_storage_adapter", lambda: storage)

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        _add_default_qa_model(session, tenant_id)
        add_default_embedding_model(session, tenant_id, expected_dimension=4)
        session.commit()

    body = "# Invalid output\n\nThis is fact number 0. The approval owner is team 0."
    job = client.post(
        "/api/v1/import-jobs",
        headers=admin_headers,
        json={
            "title": "Invalid QA fixture",
            "permission": {"allAuthenticated": True},
            "parseOptions": {"preferredParser": "LIGHTWEIGHT"},
            "processingOptions": {"enableQaSplit": True, "enableEmbedding": True},
        },
    ).json()
    response = client.post(
        f"/api/v1/import-jobs/{job['id']}/files",
        headers=admin_headers,
        json={
            "objectKey": "seed/invalid-qa-fixture.md",
            "fileName": "invalid-qa-fixture.md",
            "mimeType": "text/markdown",
            "fileSize": len(body.encode("utf-8")),
            "checksum": "sha256:invalid-qa-fixture",
            "contentBase64": b64encode(body.encode("utf-8")).decode("ascii"),
        },
    )
    assert response.status_code == 201

    from server.app.services.document_parse_service import DocumentParseService
    from server.app.services.qa_split_service import QaSplitService

    with SessionLocal() as session:
        DocumentParseService(session, storage=storage).parse_import_job(job["id"])
        document = session.get(Document, job["documentId"])
        assert document is not None
        chunk = session.scalar(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
        )
        assert chunk is not None
        session.add(
            QaPair(
                tenant_id=document.tenant_id,
                document_id=document.id,
                chunk_id=chunk.id,
                job_id=job["id"],
                pair_index=0,
                question="旧问题",
                answer="旧答案",
                quote=chunk.content,
                page_no=chunk.page_no or 1,
                search_text="旧问题 旧答案",
                status="ACTIVE",
            )
        )
        session.commit()

        class InvalidOutputProvider:
            provider_type = "OPENAI_COMPATIBLE"
            model_name = "fixture-invalid-output"

            @staticmethod
            def generate_qa_pairs(_prompt: str) -> str:
                return json.dumps({"items": {}})

        result = QaSplitService(
            session,
            provider_factory=lambda *_args, **_kwargs: InvalidOutputProvider(),
            max_retries=2,
            max_split_depth=1,
        ).split_import_job(job["id"])

        refreshed_document = session.get(Document, document.id)
        refreshed_job = session.get(ImportJob, job["id"])
        pairs = session.scalars(
            select(QaPair)
            .where(QaPair.document_id == document.id)
            .order_by(QaPair.pair_index)
        ).all()
        logs = session.scalars(
            select(ModelCallLog).where(ModelCallLog.run_id.is_not(None))
        ).all()

        assert result.status == "FAILED"
        assert refreshed_document is not None
        assert refreshed_job is not None
        assert refreshed_document.status == DocumentStatus.FAILED
        assert refreshed_document.last_error_code == "QA_PROVENANCE_CONTRACT_INVALID"
        assert refreshed_job.error_code == "QA_PROVENANCE_CONTRACT_INVALID"
        assert len(logs) == 1
        assert [(pair.question, pair.status) for pair in pairs] == [
            ("旧问题", "ACTIVE")
        ]


def _run_import_pipeline(
    SessionLocal,
    storage,
    job_id: str,
    *,
    qa_provider_factory=None,
    embedding_provider_factory=None,
    qa_service_kwargs: dict | None = None,
) -> None:
    from server.app.services.document_parse_service import DocumentParseService
    from server.app.services.embedding_service import EmbeddingService
    from server.app.services.qa_split_service import QaSplitService

    with SessionLocal() as session:
        DocumentParseService(session, storage=storage).parse_import_job(job_id)
        qa_options = dict(qa_service_kwargs or {})
        if qa_provider_factory is not None:
            qa_options["provider_factory"] = qa_provider_factory
        QaSplitService(session, **qa_options).split_import_job(job_id)
        embedding_options = {}
        if embedding_provider_factory is not None:
            embedding_options["provider_factory"] = embedding_provider_factory
        EmbeddingService(session, **embedding_options).embed_import_job(job_id)


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
