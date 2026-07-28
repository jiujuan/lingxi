from base64 import b64encode

from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def _create_import_classification(client, SessionLocal, headers) -> dict:
    from server.app.models.user import Department

    with SessionLocal() as session:
        support = session.scalar(select(Department).where(Department.code == "SUPPORT"))
        assert support is not None
        support_id = support.id

    space_response = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={"name": "客服知识库", "code": "support-kb"},
    )
    assert space_response.status_code == 201
    space = space_response.json()

    category_response = client.post(
        "/api/v1/knowledge-categories",
        headers=headers,
        json={
            "spaceId": space["id"],
            "departmentId": support_id,
            "name": "退款专题",
            "code": "refund",
        },
    )
    assert category_response.status_code == 201
    category = category_response.json()

    return {
        "space_id": space["id"],
        "department_id": support_id,
        "category_id": category["id"],
    }


def test_create_import_job_writes_document_and_access_rules():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    from server.app.models.user import Department

    with SessionLocal() as session:
        department = session.scalar(select(Department).where(Department.code == "SUPPORT"))

    response = client.post(
        "/api/v1/import-jobs",
        headers=headers,
        json={
            "title": "Refund SOP",
            "permission": {
                "departmentIds": [department.id],
                "roleIds": [],
                "userIds": [],
                "allAuthenticated": False,
            },
            "parseOptions": {"preferredParser": "LIGHTWEIGHT"},
            "processingOptions": {"enableQaSplit": True, "enableEmbedding": True},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["stage"] == "CREATED"
    assert body["documentId"]

    from server.app.models.document import Document, DocumentAccessRule
    from server.app.models.import_job import ImportJob

    with SessionLocal() as session:
        job = session.get(ImportJob, body["id"])
        document = session.get(Document, body["documentId"])
        rules = session.scalars(
            select(DocumentAccessRule).where(
                DocumentAccessRule.document_id == body["documentId"]
            )
        ).all()

    assert job is not None
    assert job.document_id == body["documentId"]
    assert document is not None
    assert document.knowledge_space_id is None
    assert document.category_department_id is None
    assert document.knowledge_category_id is None
    assert len(rules) == 1
    assert rules[0].subject_id == department.id


def test_create_import_job_with_classification_writes_document_fields():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)
    classification = _create_import_classification(client, SessionLocal, headers)

    response = client.post(
        "/api/v1/import-jobs",
        headers=headers,
        json={
            "title": "Refund SOP",
            "classification": {
                "spaceId": classification["space_id"],
                "departmentId": classification["department_id"],
                "categoryId": classification["category_id"],
            },
            "permission": {"allAuthenticated": True},
            "processingOptions": {"enableQaSplit": True, "enableEmbedding": True},
        },
    )

    assert response.status_code == 201
    body = response.json()

    from server.app.models.document import Document, DocumentAccessRule
    from server.app.models.import_job import ImportJob

    with SessionLocal() as session:
        document = session.get(Document, body["documentId"])
        job = session.get(ImportJob, body["id"])
        rules = session.scalars(
            select(DocumentAccessRule).where(
                DocumentAccessRule.document_id == body["documentId"]
            )
        ).all()

    assert document is not None
    assert document.knowledge_space_id == classification["space_id"]
    assert document.category_department_id == classification["department_id"]
    assert document.knowledge_category_id == classification["category_id"]
    assert job is not None
    assert job.document_id == document.id
    assert len(rules) == 1


def test_create_import_job_rejects_inconsistent_classification_path():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)
    classification = _create_import_classification(client, SessionLocal, headers)

    other_space = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={"name": "内部知识库", "code": "internal-kb"},
    ).json()

    response = client.post(
        "/api/v1/import-jobs",
        headers=headers,
        json={
            "title": "Refund SOP",
            "classification": {
                "spaceId": other_space["id"],
                "departmentId": classification["department_id"],
                "categoryId": classification["category_id"],
            },
            "permission": {"allAuthenticated": True},
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CLASSIFICATION_PATH_INVALID"


def test_bind_import_file_validates_object_key_and_enqueues_parser(monkeypatch, tmp_path):
    client, _ = build_test_client()
    headers = login_admin(client)
    queued: list[str] = []

    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.services import import_service

    monkeypatch.setattr(
        import_service,
        "get_storage_adapter",
        lambda: LocalObjectStorage(tmp_path),
    )
    monkeypatch.setattr(import_service, "enqueue_parse_task", lambda job_id: queued.append(job_id))

    job = client.post(
        "/api/v1/import-jobs",
        headers=headers,
        json={
            "title": "Markdown Guide",
            "permission": {"allAuthenticated": True},
            "parseOptions": {"preferredParser": "LIGHTWEIGHT"},
            "processingOptions": {"enableQaSplit": True, "enableEmbedding": True},
        },
    ).json()

    invalid = client.post(
        f"/api/v1/import-jobs/{job['id']}/files",
        headers=headers,
        json={
            "objectKey": "../private.md",
            "fileName": "private.md",
            "mimeType": "text/markdown",
            "fileSize": 12,
            "checksum": "bad",
            "contentBase64": b64encode(b"unsafe").decode("ascii"),
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_OBJECT_KEY"

    response = client.post(
        f"/api/v1/import-jobs/{job['id']}/files",
        headers=headers,
        json={
            "objectKey": "uploads/markdown-guide.md",
            "fileName": "markdown-guide.md",
            "mimeType": "text/markdown",
            "fileSize": 25,
            "checksum": "sha256:markdown-guide",
            "contentBase64": b64encode(b"# Guide\n\nUse the refund flow.").decode("ascii"),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "RUNNING"
    assert body["stage"] == "PARSING"
    assert body["file"]["objectKey"] == "uploads/markdown-guide.md"
    assert queued == [job["id"]]


def test_upload_import_file_via_multipart_enqueues_parser(monkeypatch, tmp_path):
    client, _ = build_test_client()
    headers = login_admin(client)
    queued: list[str] = []

    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.services import import_service

    monkeypatch.setattr(
        import_service,
        "get_storage_adapter",
        lambda: LocalObjectStorage(tmp_path),
    )
    monkeypatch.setattr(import_service, "enqueue_parse_task", lambda job_id: queued.append(job_id))

    job = client.post(
        "/api/v1/import-jobs",
        headers=headers,
        json={
            "title": "Multipart Guide",
            "permission": {"allAuthenticated": True},
            "parseOptions": {"preferredParser": "LIGHTWEIGHT"},
            "processingOptions": {"enableQaSplit": True, "enableEmbedding": True},
        },
    ).json()

    content = b"# Guide\n\nUse the refund flow."
    response = client.post(
        f"/api/v1/import-jobs/{job['id']}/file",
        headers=headers,
        files={"file": ("multipart-guide.md", content, "text/markdown")},
        data={"object_key": "uploads/multipart-guide.md", "checksum": "sha256:multipart-guide"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "RUNNING"
    assert body["stage"] == "PARSING"
    assert body["file"]["fileName"] == "multipart-guide.md"
    assert body["file"]["fileSize"] == len(content)
    assert queued == [job["id"]]


def test_upload_gate_follows_parser_registry_allowlist(monkeypatch, tmp_path):
    client, _ = build_test_client()
    headers = login_admin(client)

    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.services import import_service

    monkeypatch.setattr(
        import_service,
        "get_storage_adapter",
        lambda: LocalObjectStorage(tmp_path),
    )
    monkeypatch.setattr(import_service, "enqueue_parse_task", lambda _job_id: None)

    def create_job(title: str) -> dict:
        return client.post(
            "/api/v1/import-jobs",
            headers=headers,
            json={"title": title, "permission": {"allAuthenticated": True}},
        ).json()

    def bind(job: dict, file_name: str, mime_type: str, content: bytes):
        return client.post(
            f"/api/v1/import-jobs/{job['id']}/file",
            headers=headers,
            files={"file": (file_name, content, mime_type)},
            data={
                "object_key": f"uploads/{file_name}",
                "checksum": f"sha256:{file_name}",
            },
        )

    # 白名单不含 .pdf（MinerU 未配置的形态）：上传门直接 415
    monkeypatch.setattr(
        import_service,
        "allowed_upload_extensions",
        lambda: frozenset({".md", ".markdown", ".txt", ".csv"}),
    )
    csv_response = bind(
        create_job("CSV Staff"), "staff.csv", "text/csv", "姓名,部门\n张三,售后\n".encode()
    )
    assert csv_response.status_code == 201
    assert csv_response.json()["file"]["fileName"] == "staff.csv"

    pdf_rejected = bind(
        create_job("PDF Doc"), "doc.pdf", "application/pdf", b"%PDF-1.7"
    )
    assert pdf_rejected.status_code == 415

    # 白名单含 .pdf（MinerU 已配置的形态）：上传门放行
    monkeypatch.setattr(
        import_service,
        "allowed_upload_extensions",
        lambda: frozenset({".md", ".pdf"}),
    )
    pdf_accepted = bind(
        create_job("PDF Doc 2"), "doc2.pdf", "application/pdf", b"%PDF-1.7"
    )
    assert pdf_accepted.status_code == 201


def test_file_type_mapping_covers_new_formats():
    from server.app.services.import_service import ImportService

    assert ImportService._file_type("a.md") == "MARKDOWN"
    assert ImportService._file_type("a.txt") == "TEXT"
    assert ImportService._file_type("a.csv") == "CSV"
    assert ImportService._file_type("a.pdf") == "PDF"
    assert ImportService._file_type("a.docx") == "WORD"
    assert ImportService._file_type("a.pptx") == "PPT"
    assert ImportService._file_type("a.xlsx") == "EXCEL"
    assert ImportService._file_type("a.html") == "HTML"
    assert ImportService._file_type("a.htm") == "HTML"
    assert ImportService._file_type("a.JPG") == "IMAGE"
    assert ImportService._file_type("a.unknown") == "UNKNOWN"


def test_import_job_rejects_duplicate_checksum(monkeypatch, tmp_path):
    client, _ = build_test_client()
    headers = login_admin(client)

    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.services import import_service

    monkeypatch.setattr(
        import_service,
        "get_storage_adapter",
        lambda: LocalObjectStorage(tmp_path),
    )
    monkeypatch.setattr(import_service, "enqueue_parse_task", lambda _job_id: None)

    first_job = client.post(
        "/api/v1/import-jobs",
        headers=headers,
        json={"title": "First", "permission": {"allAuthenticated": True}},
    ).json()
    second_job = client.post(
        "/api/v1/import-jobs",
        headers=headers,
        json={"title": "Second", "permission": {"allAuthenticated": True}},
    ).json()

    payload = {
        "objectKey": "uploads/first.txt",
        "fileName": "first.txt",
        "mimeType": "text/plain",
        "fileSize": 5,
        "checksum": "same-checksum",
        "contentBase64": b64encode(b"first").decode("ascii"),
    }
    assert (
        client.post(
            f"/api/v1/import-jobs/{first_job['id']}/files",
            headers=headers,
            json=payload,
        ).status_code
        == 201
    )

    duplicate = client.post(
        f"/api/v1/import-jobs/{second_job['id']}/files",
        headers=headers,
        json={**payload, "objectKey": "uploads/second.txt", "fileName": "second.txt"},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_DOCUMENT"
