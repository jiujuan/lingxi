from base64 import b64encode

from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


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

    from server.app.models.document import DocumentAccessRule
    from server.app.models.import_job import ImportJob

    with SessionLocal() as session:
        job = session.get(ImportJob, body["id"])
        rules = session.scalars(
            select(DocumentAccessRule).where(
                DocumentAccessRule.document_id == body["documentId"]
            )
        ).all()

    assert job is not None
    assert job.document_id == body["documentId"]
    assert len(rules) == 1
    assert rules[0].subject_id == department.id


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
