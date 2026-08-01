from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = ROOT / "docs" / "development" / "v1.1" / "acceptance"
APP_ORIGIN = "http://127.0.0.1:5174"

NOW = "2026-07-29T10:00:00+08:00"


DEPARTMENTS = [
    {
        "id": "dept-after-sales",
        "name": "售后部",
        "code": "after-sales",
        "parentId": None,
        "userCount": 8,
        "createdAt": "2026-07-01T09:00:00+08:00",
    },
    {
        "id": "dept-product",
        "name": "产品部",
        "code": "product",
        "parentId": None,
        "userCount": 5,
        "createdAt": "2026-07-01T09:10:00+08:00",
    },
]

INITIAL_SPACES = [
    {
        "id": "space-001",
        "name": "客服知识库",
        "code": "customer-service",
        "description": "客服与售后标准知识。",
        "status": "ACTIVE",
        "sortOrder": 10,
        "createdAt": "2026-07-01T09:00:00+08:00",
        "updatedAt": "2026-07-01T09:00:00+08:00",
    },
    {
        "id": "space-002",
        "name": "内部知识库",
        "code": "internal",
        "description": "内部流程知识。",
        "status": "ACTIVE",
        "sortOrder": 20,
        "createdAt": "2026-07-01T09:20:00+08:00",
        "updatedAt": "2026-07-01T09:20:00+08:00",
    },
]

INITIAL_CATEGORIES = [
    {
        "id": "cat-refund",
        "spaceId": "space-001",
        "departmentId": "dept-after-sales",
        "parentId": None,
        "name": "退款专题",
        "code": "refund",
        "categoryType": "TOPIC",
        "description": "退款政策与 SOP。",
        "status": "ACTIVE",
        "sortOrder": 10,
        "createdAt": "2026-07-01T10:00:00+08:00",
        "updatedAt": "2026-07-01T10:00:00+08:00",
    },
    {
        "id": "cat-logistics",
        "spaceId": "space-001",
        "departmentId": "dept-after-sales",
        "parentId": None,
        "name": "物流专题",
        "code": "logistics",
        "categoryType": "TOPIC",
        "description": "物流与签收问题。",
        "status": "ACTIVE",
        "sortOrder": 20,
        "createdAt": "2026-07-01T10:10:00+08:00",
        "updatedAt": "2026-07-01T10:10:00+08:00",
    },
    {
        "id": "cat-product-faq",
        "spaceId": "space-001",
        "departmentId": "dept-product",
        "parentId": None,
        "name": "产品 FAQ",
        "code": "product-faq",
        "categoryType": "PROJECT",
        "description": "产品常见问题。",
        "status": "ACTIVE",
        "sortOrder": 30,
        "createdAt": "2026-07-01T10:20:00+08:00",
        "updatedAt": "2026-07-01T10:20:00+08:00",
    },
]

BASE_DOCUMENT = {
    "id": "doc-ready",
    "title": "Refund SOP",
    "fileName": "refund.md",
    "fileType": "MARKDOWN",
    "mimeType": "text/markdown",
    "fileSize": 120,
    "status": "READY",
    "parserName": "LIGHTWEIGHT",
    "parserVersion": "1.0",
    "pageCount": 2,
    "qaPairCount": 1,
    "chunkCount": 1,
    "objectKey": "uploads/refund.md",
    "checksum": "sha256:refund",
    "permissions": {
        "allAuthenticated": True,
        "departments": [],
        "roles": [],
        "users": [],
    },
    "latestJob": {
        "id": "job-ready",
        "status": "COMPLETED",
        "stage": "COMPLETED",
        "progress": 100,
        "retryCount": 0,
        "errorCode": None,
        "errorMessage": None,
        "failedStage": None,
        "retryable": False,
    },
    "lastErrorCode": None,
    "lastErrorMessage": None,
    "processingLogs": [
        {
            "id": "task-ready",
            "taskType": "embed_qa_pairs_task",
            "queueName": "embedding",
            "stage": "EMBEDDING",
            "status": "SUCCESS",
            "error": None,
            "requestId": "req_ready",
        }
    ],
    "createdAt": "2026-07-05T10:00:00+08:00",
    "updatedAt": "2026-07-05T10:10:00+08:00",
}


class KnowledgeApiMock:
    """Stateful mock API for Task 7 phase-2 frontend regression acceptance."""

    def __init__(self) -> None:
        self.spaces = deepcopy(INITIAL_SPACES)
        self.categories = deepcopy(INITIAL_CATEGORIES)
        self.departments = deepcopy(DEPARTMENTS)
        self.document_categories = {"doc-ready": "cat-refund", "doc-unclassified": None}
        self.requests: list[dict] = []

    def handle(self, route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = api_path(route)
        method = request.method
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        body = request_json(request.post_data)
        self.requests.append({"method": method, "path": path, "query": query, "body": body})

        if method == "GET" and path == "/api/v1/departments":
            fulfill_json(route, {"data": self.departments})
            return

        if method == "POST" and path == "/api/v1/departments":
            payload = body or {}
            department = {
                "id": "dept-created",
                "userCount": 0,
                "createdAt": NOW,
                **payload,
            }
            self.departments.append(department)
            fulfill_json(route, department, status=201)
            return

        if method == "PUT" and path.startswith("/api/v1/departments/"):
            department_id = path.rsplit("/", 1)[-1]
            department = self._department(department_id)
            department.update(body or {})
            fulfill_json(route, department)
            return

        if method == "DELETE" and path.startswith("/api/v1/departments/"):
            department_id = path.rsplit("/", 1)[-1]
            self.departments = [
                department for department in self.departments if department["id"] != department_id
            ]
            fulfill_json(route, {"ok": True})
            return

        if method == "GET" and path == "/api/v1/knowledge-spaces":
            fulfill_json(route, {"data": self.spaces})
            return

        if method == "GET" and path == "/api/v1/knowledge-spaces/stats":
            fulfill_json(route, self._space_stats_response())
            return

        if method == "POST" and path == "/api/v1/knowledge-spaces":
            payload = body or {}
            space = {
                "id": "space-created",
                "createdAt": NOW,
                "updatedAt": NOW,
                **payload,
            }
            self.spaces.append(space)
            fulfill_json(route, space, status=201)
            return

        if method == "PUT" and path.startswith("/api/v1/knowledge-spaces/"):
            space_id = path.rsplit("/", 1)[-1]
            payload = body or {}
            space = self._space(space_id)
            space.update(payload)
            space["updatedAt"] = NOW
            fulfill_json(route, space)
            return

        if method == "POST" and path.startswith("/api/v1/knowledge-spaces/") and path.endswith("/migrate-documents"):
            source_space_id = path.split("/")[-2]
            payload = body or {}
            target_category_id = payload.get("targetCategoryId")
            migrated_count = 0
            for document_id, category_id in list(self.document_categories.items()):
                if category_id and self._category(category_id)["spaceId"] == source_space_id:
                    self.document_categories[document_id] = target_category_id
                    migrated_count += 1
            fulfill_json(
                route,
                {
                    "sourceType": "SPACE",
                    "sourceId": source_space_id,
                    "migratedCount": migrated_count,
                    "targetClassification": self._classification(target_category_id),
                },
            )
            return

        if method == "DELETE" and path.startswith("/api/v1/knowledge-spaces/"):
            space_id = path.rsplit("/", 1)[-1]
            document_count = self._document_count_for_space(space_id)
            if document_count:
                fulfill_json(
                    route,
                    api_error(
                        "KNOWLEDGE_SPACE_HAS_DOCUMENTS",
                        f"请先迁移空间下的 {document_count} 篇文档",
                        {
                            "resourceType": "SPACE",
                            "resourceId": space_id,
                            "documentCount": document_count,
                        },
                    ),
                    status=409,
                )
                return
            self.spaces = [space for space in self.spaces if space["id"] != space_id]
            self.categories = [category for category in self.categories if category["spaceId"] != space_id]
            fulfill_json(route, {"ok": True})
            return

        if method == "GET" and path == "/api/v1/knowledge-categories":
            space_id = query.get("spaceId")
            department_id = query.get("departmentId")
            categories = [
                category
                for category in self.categories
                if (not space_id or category["spaceId"] == space_id)
                and (not department_id or category["departmentId"] == department_id)
            ]
            fulfill_json(route, {"data": categories})
            return

        if method == "GET" and path == "/api/v1/knowledge-categories/stats":
            fulfill_json(
                route,
                self._category_stats_response(query.get("spaceId"), query.get("departmentId")),
            )
            return

        if method == "POST" and path == "/api/v1/knowledge-categories":
            payload = body or {}
            category = {
                "id": "cat-created",
                "createdAt": NOW,
                "updatedAt": NOW,
                **payload,
            }
            self.categories.append(category)
            fulfill_json(route, category, status=201)
            return

        if method == "PUT" and path.startswith("/api/v1/knowledge-categories/"):
            category_id = path.rsplit("/", 1)[-1]
            payload = body or {}
            category = self._category(category_id)
            category.update(payload)
            category["updatedAt"] = NOW
            fulfill_json(route, category)
            return

        if method == "POST" and path.startswith("/api/v1/knowledge-categories/") and path.endswith("/migrate-documents"):
            source_category_id = path.split("/")[-2]
            payload = body or {}
            target_category_id = payload.get("targetCategoryId")
            migrated_count = 0
            for document_id, category_id in list(self.document_categories.items()):
                if category_id == source_category_id:
                    self.document_categories[document_id] = target_category_id
                    migrated_count += 1
            fulfill_json(
                route,
                {
                    "sourceType": "CATEGORY",
                    "sourceId": source_category_id,
                    "migratedCount": migrated_count,
                    "targetClassification": self._classification(target_category_id),
                },
            )
            return

        if method == "DELETE" and path.startswith("/api/v1/knowledge-categories/"):
            category_id = path.rsplit("/", 1)[-1]
            document_count = self._document_count_for_category(category_id)
            if document_count:
                fulfill_json(
                    route,
                    api_error(
                        "KNOWLEDGE_CATEGORY_HAS_DOCUMENTS",
                        f"请先迁移分类下的 {document_count} 篇文档",
                        {
                            "resourceType": "CATEGORY",
                            "resourceId": category_id,
                            "documentCount": document_count,
                        },
                    ),
                    status=409,
                )
                return
            self.categories = [category for category in self.categories if category["id"] != category_id]
            fulfill_json(route, {"ok": True})
            return

        if method == "GET" and path == "/api/v1/documents/summary":
            fulfill_json(
                route,
                {
                    "syncedDocumentCount": 2,
                    "totalChunkCount": 8,
                },
            )
            return

        if method == "GET" and path == "/api/v1/documents":
            documents = [self._document("doc-ready"), self._document("doc-unclassified")]
            if query.get("keyword"):
                keyword = query["keyword"].lower()
                documents = [
                    document
                    for document in documents
                    if keyword in document["title"].lower()
                    or keyword in document["fileName"].lower()
                ]
            if query.get("isUnclassified") == "true":
                documents = [document for document in documents if document["classification"] is None]
            if query.get("spaceId"):
                documents = [
                    document
                    for document in documents
                    if document["classification"]
                    and document["classification"]["knowledgeSpaceId"] == query["spaceId"]
                ]
            if query.get("classificationDepartmentId"):
                documents = [
                    document
                    for document in documents
                    if document["classification"]
                    and document["classification"]["categoryDepartmentId"]
                    == query["classificationDepartmentId"]
                ]
            if query.get("categoryId"):
                documents = [
                    document
                    for document in documents
                    if document["classification"]
                    and document["classification"]["knowledgeCategoryId"] == query["categoryId"]
                ]
            fulfill_json(
                route,
                {
                    "data": documents,
                    "pagination": {
                        "page": int(query.get("page", 1)),
                        "pageSize": int(query.get("pageSize", 20)),
                        "totalItems": len(documents),
                        "totalPages": 1 if documents else 0,
                    },
                },
            )
            return

        if method == "GET" and path == "/api/v1/documents/doc-ready":
            fulfill_json(route, self._document("doc-ready"))
            return

        if method == "GET" and path == "/api/v1/documents/doc-ready/chunks":
            fulfill_json(
                route,
                {
                    "data": [
                        {
                            "id": "chunk-ready",
                            "documentId": "doc-ready",
                            "chunkIndex": 0,
                            "titlePath": ["退款流程"],
                            "content": "退款需要主管审批。",
                            "pageNo": 1,
                            "tokenCount": 4,
                            "sourceLocator": {"lineStart": 1},
                            "status": "ACTIVE",
                        }
                    ],
                    "pagination": {"page": 1, "pageSize": 20, "totalItems": 1, "totalPages": 1},
                },
            )
            return

        if method == "GET" and path == "/api/v1/documents/doc-ready/qa-pairs":
            fulfill_json(
                route,
                {
                    "data": [
                        {
                            "id": "qa-ready",
                            "documentId": "doc-ready",
                            "chunkId": "chunk-ready",
                            "question": "退款需要谁审批？",
                            "answer": "退款需要主管审批。",
                            "quote": "退款需要主管审批。",
                            "pageNo": 1,
                            "embeddingStatus": "READY",
                            "status": "ACTIVE",
                        }
                    ],
                    "pagination": {"page": 1, "pageSize": 20, "totalItems": 1, "totalPages": 1},
                },
            )
            return

        if method == "PATCH" and path == "/api/v1/documents/doc-ready/classification":
            payload = body or {}
            self.document_categories["doc-ready"] = payload.get("categoryId")
            category_id = self.document_categories["doc-ready"]
            fulfill_json(route, self._classification(category_id) if category_id else None)
            return

        if method == "PATCH" and path == "/api/v1/documents/bulk-classification":
            payload = body or {}
            classification = payload.get("classification")
            category_id = classification.get("categoryId") if classification else None
            for document_id in payload.get("documentIds", []):
                self.document_categories[document_id] = category_id
            fulfill_json(
                route,
                {
                    "updatedCount": len(payload.get("documentIds", [])),
                    "documentIds": payload.get("documentIds", []),
                    "classification": self._classification(category_id) if category_id else None,
                },
            )
            return

        if method == "POST" and path == "/api/v1/import-jobs":
            title = (body or {}).get("title")
            job_id = "job-upload-failed" if title == "playwright-failed" else "job-upload"
            fulfill_json(
                route,
                {
                    "id": job_id,
                    "documentId": None,
                    "status": "PENDING",
                    "stage": "CREATED",
                    "progress": 0,
                    "retryCount": 0,
                    "errorCode": None,
                    "errorMessage": None,
                    "failedStage": None,
                    "retryable": False,
                    "file": None,
                },
                status=201,
            )
            return

        if method == "POST" and path == "/api/v1/import-jobs/job-upload-failed/file":
            fulfill_json(
                route,
                {
                    "id": "job-upload-failed",
                    "documentId": None,
                    "status": "FAILED",
                    "stage": "PARSING",
                    "progress": 35,
                    "retryCount": 0,
                    "errorCode": "PARSE_INVALID",
                    "errorMessage": "模拟文档解析失败。",
                    "failedStage": "PARSING",
                    "retryable": True,
                    "file": {
                        "id": "file-upload-failed",
                        "objectKey": "uploads/playwright-failed.md",
                        "fileName": "playwright-failed.md",
                        "mimeType": "text/markdown",
                        "fileSize": 32,
                        "checksum": "sha256:playwright-failed",
                    },
                },
            )
            return

        if method == "POST" and path == "/api/v1/import-jobs/job-upload/file":
            fulfill_json(
                route,
                {
                    "id": "job-upload",
                    "documentId": "doc-ready",
                    "status": "COMPLETED",
                    "stage": "COMPLETED",
                    "progress": 100,
                    "retryCount": 0,
                    "errorCode": None,
                    "errorMessage": None,
                    "failedStage": None,
                    "retryable": False,
                    "file": {
                        "id": "file-upload",
                        "objectKey": "uploads/playwright-refund.md",
                        "fileName": "playwright-refund.md",
                        "mimeType": "text/markdown",
                        "fileSize": 34,
                        "checksum": "sha256:playwright",
                    },
                },
            )
            return

        fulfill_json(
            route,
            api_error("MOCK_NOT_FOUND", f"未配置 mock: {method} {path}"),
            status=404,
        )

    def find_request(self, method: str, path: str, **query: str) -> dict:
        for request in reversed(self.requests):
            if request["method"] != method or request["path"] != path:
                continue
            if all(request["query"].get(key) == value for key, value in query.items()):
                return request
        raise AssertionError(f"未捕获请求: {method} {path} query={query}; captured={self.requests}")

    def request_count(self, method: str, path: str) -> int:
        return sum(
            1
            for request in self.requests
            if request["method"] == method and request["path"] == path
        )

    def _space(self, space_id: str) -> dict:
        for space in self.spaces:
            if space["id"] == space_id:
                return space
        raise AssertionError(f"未知知识库空间: {space_id}")

    def _category(self, category_id: str) -> dict:
        for category in self.categories:
            if category["id"] == category_id:
                return category
        raise AssertionError(f"未知项目 / 专题: {category_id}")

    def _department(self, department_id: str) -> dict:
        for department in self.departments:
            if department["id"] == department_id:
                return department
        raise AssertionError(f"未知部门: {department_id}")

    def _document_count_for_category(self, category_id: str) -> int:
        return sum(1 for value in self.document_categories.values() if value == category_id)

    def _document_count_for_space(self, space_id: str) -> int:
        count = 0
        for category_id in self.document_categories.values():
            if category_id and self._category(category_id)["spaceId"] == space_id:
                count += 1
        return count

    def _space_stats_response(self) -> dict:
        data = []
        for space in self.spaces:
            stats = self._zero_stats()
            if space["id"] == "space-001":
                stats.update(
                    {
                        "totalCount": 3,
                        "processingCount": 1,
                        "readyCount": 2,
                        "failedCount": 0,
                        "unclassifiedCount": 1,
                    }
                )
            data.append({"spaceId": space["id"], **stats})
        return {
            "data": data,
            "summary": {
                "totalCount": 1,
                "processingCount": 0,
                "readyCount": 0,
                "failedCount": 1,
                "unclassifiedCount": 1,
            },
        }

    def _category_stats_response(
        self, space_id: str | None, department_id: str | None
    ) -> dict:
        stats_by_category = {
            "cat-refund": {
                "totalCount": 2,
                "processingCount": 0,
                "readyCount": 2,
                "failedCount": 0,
                "unclassifiedCount": 0,
            },
            "cat-logistics": {
                "totalCount": 1,
                "processingCount": 1,
                "readyCount": 0,
                "failedCount": 0,
                "unclassifiedCount": 0,
            },
        }
        categories = [
            category
            for category in self.categories
            if (not space_id or category["spaceId"] == space_id)
            and (not department_id or category["departmentId"] == department_id)
        ]
        has_after_sales_unclassified = (
            space_id == "space-001" and department_id == "dept-after-sales"
        )
        return {
            "data": [
                {
                    "categoryId": category["id"],
                    "spaceId": category["spaceId"],
                    "departmentId": category["departmentId"],
                    **stats_by_category.get(category["id"], self._zero_stats()),
                }
                for category in categories
            ],
            "unclassified": {
                "totalCount": 1 if has_after_sales_unclassified else 0,
                "processingCount": 0,
                "readyCount": 0,
                "failedCount": 1 if has_after_sales_unclassified else 0,
                "unclassifiedCount": 1 if has_after_sales_unclassified else 0,
            },
        }

    @staticmethod
    def _zero_stats() -> dict:
        return {
            "totalCount": 0,
            "processingCount": 0,
            "readyCount": 0,
            "failedCount": 0,
            "unclassifiedCount": 0,
        }

    def _classification(self, category_id: str) -> dict:
        category = self._category(category_id)
        return {
            "knowledgeSpaceId": category["spaceId"],
            "knowledgeSpace": self._space(category["spaceId"]),
            "categoryDepartmentId": category["departmentId"],
            "categoryDepartment": self._department(category["departmentId"]),
            "knowledgeCategoryId": category["id"],
            "knowledgeCategory": category,
        }

    def _document(self, document_id: str = "doc-ready") -> dict:
        document = deepcopy(BASE_DOCUMENT)
        if document_id == "doc-unclassified":
            document.update(
                {
                    "id": "doc-unclassified",
                    "title": "Unclassified FAQ",
                    "fileName": "unclassified.md",
                    "objectKey": "uploads/unclassified.md",
                    "checksum": "sha256:unclassified",
                    "qaPairCount": 0,
                    "chunkCount": 0,
                }
            )
        category_id = self.document_categories.get(document_id)
        document["classification"] = self._classification(category_id) if category_id else None
        return document


def fulfill_json(route: Route, payload: dict, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload, ensure_ascii=False),
    )


def api_error(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details or {}},
        "requestId": "req_playwright_mock",
    }


def api_path(route: Route) -> str:
    parsed = urlparse(route.request.url)
    path = parsed.path
    marker = "/api/v1"
    if marker in path:
        return path[path.index(marker) :]
    return path


def request_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def prepare_page(page: Page) -> tuple[list[str], KnowledgeApiMock]:
    console_errors: list[str] = []
    api = KnowledgeApiMock()
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type in {"error", "warning"}
        and "409 (Conflict)" not in message.text
        else None,
    )
    page.route("**/*/api/v1/**", api.handle)
    page.route("**/api/v1/**", api.handle)
    page.add_init_script(
        """
        localStorage.setItem('lingxi_access_token', 'playwright-token');
        localStorage.setItem('lingxi_user', JSON.stringify({
          id: 'admin-playwright',
          email: 'admin@example.com',
          name: 'Playwright 管理员',
          roles: ['admin'],
          permissions: [
            'DASHBOARD_READ', 'DOCUMENT_READ', 'DOCUMENT_WRITE',
            'DOCUMENT_PERMISSION_WRITE', 'DOCUMENT_DELETE', 'TASK_RETRY', 'USER_WRITE'
          ]
        }));
        """
    )
    return console_errors, api


def verify_phase_two_desktop_flow(page: Page) -> tuple[list[str], KnowledgeApiMock]:
    errors, api = prepare_page(page)

    verify_classification_admin_flow(page, api)
    verify_upload_flow(page, api)
    verify_document_filter_detail_edit_flow(page, api)
    verify_category_migration_flow(page, api)

    return errors, api


def verify_classification_admin_flow(page: Page, api: KnowledgeApiMock) -> None:
    page.goto(f"{APP_ORIGIN}/#knowledge-classification", wait_until="networkidle")
    expect(page.get_by_role("heading", name="知识库分类管理")).to_be_visible()
    expect(page.get_by_text("客服知识库").first).to_be_visible()
    expect(
        page.locator(".classification-space-row", has_text="客服知识库").get_by_text("总数 3")
    ).to_be_visible()

    page.get_by_role("button", name="增加知识库空间").click()
    space_dialog = page.get_by_role("dialog", name="增加知识库空间")
    space_dialog.get_by_label("空间名称").fill("运营知识库")
    space_dialog.get_by_label("空间编码").fill("operations")
    space_dialog.get_by_label("描述").fill("运营 SOP 分类空间")
    space_dialog.get_by_label("排序").fill("30")
    space_dialog.get_by_role("button", name="保存").click()
    expect(page.get_by_text("知识库空间已创建。")).to_be_visible()
    created_space = api.find_request("POST", "/api/v1/knowledge-spaces")["body"]
    assert created_space == {
        "name": "运营知识库",
        "code": "operations",
        "description": "运营 SOP 分类空间",
        "sortOrder": 30,
        "status": "ACTIVE",
    }

    page.locator(".classification-space-row", has_text="运营知识库").get_by_role(
        "button", name="编辑"
    ).click()
    edit_space_dialog = page.get_by_role("dialog", name="编辑知识库空间")
    edit_space_dialog.get_by_label("空间名称").fill("运营知识库 v2")
    edit_space_dialog.get_by_role("button", name="保存").click()
    expect(page.get_by_text("知识库空间已更新。")).to_be_visible()
    updated_space = api.find_request("PUT", "/api/v1/knowledge-spaces/space-created")["body"]
    assert updated_space["name"] == "运营知识库 v2"

    page.locator(".classification-space-row", has_text="运营知识库 v2").get_by_role(
        "button", name="删除"
    ).click()
    delete_dialog = page.get_by_role("dialog", name="删除确认")
    expect(delete_dialog.get_by_text("确定删除「运营知识库 v2」吗？")).to_be_visible()
    delete_dialog.get_by_role("button", name="确认删除").click()
    expect(page.get_by_text("知识库空间已删除。")).to_be_visible()
    api.find_request("DELETE", "/api/v1/knowledge-spaces/space-created")

    page.locator(".classification-space-row", has_text="客服知识库").get_by_role(
        "button", name="删除"
    ).click()
    page.get_by_role("dialog", name="删除确认").get_by_role("button", name="确认删除").click()
    expect(page.get_by_text("知识库空间「客服知识库」下仍有 1 篇文档，请先迁移。")).to_be_visible()
    migration_dialog = page.locator(".classification-migration-modal")
    expect(migration_dialog.get_by_text("1 篇关联文档")).to_be_visible()
    migration_dialog.get_by_role("button", name="关闭").click()

    page.get_by_role("tab", name="部门").click()
    expect(page.locator(".classification-department-row", has_text="售后部")).to_be_visible()
    page.get_by_role("button", name="增加部门").click()
    department_dialog = page.get_by_role("dialog", name="增加部门")
    department_dialog.get_by_label("部门名称").fill("运营部")
    department_dialog.get_by_label("部门编码").fill("operations")
    department_dialog.get_by_role("button", name="保存").click()
    expect(page.get_by_text("部门已创建。")).to_be_visible()
    created_department = api.find_request("POST", "/api/v1/departments")["body"]
    assert created_department == {
        "name": "运营部",
        "code": "operations",
        "parentId": None,
    }

    page.locator(".classification-department-row", has_text="运营部").get_by_role(
        "button", name="编辑"
    ).click()
    edit_department_dialog = page.get_by_role("dialog", name="编辑部门")
    edit_department_dialog.get_by_label("部门名称").fill("运营部 v2")
    edit_department_dialog.get_by_role("button", name="保存").click()
    expect(page.get_by_text("部门已更新。")).to_be_visible()
    assert api.find_request("PUT", "/api/v1/departments/dept-created")["body"]["name"] == "运营部 v2"

    page.locator(".classification-department-row", has_text="运营部 v2").get_by_role(
        "button", name="删除"
    ).click()
    delete_dialog = page.get_by_role("dialog", name="删除确认")
    expect(delete_dialog.get_by_text("确定删除「运营部 v2」吗？")).to_be_visible()
    delete_dialog.get_by_role("button", name="确认删除").click()
    expect(page.get_by_text("部门已删除。")).to_be_visible()
    api.find_request("DELETE", "/api/v1/departments/dept-created")

    page.get_by_role("tab", name="专题 / 项目").click()
    expect(page.get_by_text("退款专题").first).to_be_visible()
    expect(page.get_by_text("当前范围未分类：总数 1")).to_be_visible()
    page.get_by_role("button", name="增加专题 / 项目").click()
    category_dialog = page.get_by_role("dialog", name="增加专题 / 项目")
    category_dialog.get_by_label("名称").fill("售后知识")
    category_dialog.get_by_label("编码").fill("after-sales-guide")
    category_dialog.get_by_label("类型").select_option("PROJECT")
    category_dialog.get_by_label("排序").fill("40")
    category_dialog.get_by_label("描述").fill("售后知识分类验收。")
    category_dialog.get_by_role("button", name="保存").click()
    expect(page.get_by_text("项目 / 专题已创建。")).to_be_visible()
    created_category = api.find_request("POST", "/api/v1/knowledge-categories")["body"]
    assert created_category == {
        "spaceId": "space-001",
        "departmentId": "dept-after-sales",
        "name": "售后知识",
        "code": "after-sales-guide",
        "categoryType": "PROJECT",
        "description": "售后知识分类验收。",
        "parentId": None,
        "sortOrder": 40,
        "status": "ACTIVE",
    }

    page.locator(".classification-category-row", has_text="售后知识").get_by_role(
        "button", name="编辑"
    ).click()
    edit_category_dialog = page.get_by_role("dialog", name="编辑专题 / 项目")
    edit_category_dialog.get_by_label("名称").fill("售后知识 v2")
    edit_category_dialog.get_by_role("button", name="保存").click()
    expect(page.get_by_text("项目 / 专题已更新。")).to_be_visible()
    updated_category = api.find_request("PUT", "/api/v1/knowledge-categories/cat-created")["body"]
    assert updated_category["name"] == "售后知识 v2"
    assert updated_category["spaceId"] == "space-001"
    assert updated_category["departmentId"] == "dept-after-sales"

    page.locator(".classification-category-row", has_text="售后知识 v2").get_by_role(
        "button", name="删除"
    ).click()
    page.get_by_role("dialog", name="删除确认").get_by_role("button", name="确认删除").click()
    expect(page.get_by_text("项目 / 专题已删除。")).to_be_visible()
    api.find_request("DELETE", "/api/v1/knowledge-categories/cat-created")
    api.find_request("GET", "/api/v1/knowledge-spaces/stats")
    api.find_request(
        "GET",
        "/api/v1/knowledge-categories/stats",
        spaceId="space-001",
        departmentId="dept-after-sales",
    )

    categories_request = api.find_request(
        "GET",
        "/api/v1/knowledge-categories",
        spaceId="space-001",
        departmentId="dept-after-sales",
    )
    assert categories_request["query"] == {"spaceId": "space-001", "departmentId": "dept-after-sales"}
    page.screenshot(path=str(SCREENSHOT_DIR / "t09-knowledge-classification-desktop.png"), full_page=True)


def verify_upload_flow(page: Page, api: KnowledgeApiMock) -> None:
    upload_dir = Path(tempfile.mkdtemp(prefix="lingxi-t09-"))
    failed_upload_file = upload_dir / "playwright-failed.md"
    failed_upload_file.write_text("# Invalid SOP\n\n模拟失败。\n", encoding="utf-8")
    upload_file = upload_dir / "playwright-refund.md"
    upload_file.write_text("# Refund SOP\n\n退款需要主管审批。\n", encoding="utf-8")

    page.goto(f"{APP_ORIGIN}/#knowledge", wait_until="networkidle")
    expect(page.get_by_role("heading", name="文档解析与知识提炼中心")).to_be_visible()
    expect(page.get_by_text("已同步文档")).to_be_visible()
    expect(page.get_by_text("已解析 Chunks")).to_be_visible()
    expect(page.get_by_role("heading", name="上传源文件")).to_be_visible()
    expect(page.get_by_role("heading", name="从原始文档到可检索知识")).to_be_visible()
    expect(page.get_by_role("heading", name="已同步与正在处理的文档")).to_be_visible()
    expect(page.get_by_text("空闲：上传文档并点击一键构建解析任务后开始处理。")).to_be_visible()

    department_input = page.get_by_label("部门 ID")
    role_input = page.get_by_label("角色 ID")
    user_input = page.get_by_label("用户 ID")
    expect(department_input).to_be_disabled()
    expect(role_input).to_be_disabled()
    expect(user_input).to_be_disabled()

    ordered_ids = page.evaluate(
        '''
        [
          'knowledge-classification-space',
          'knowledge-classification-department',
          'knowledge-classification-category',
          'knowledge-all-authenticated',
          'knowledge-department-ids',
          'knowledge-role-ids',
          'knowledge-user-ids',
          'document-processing-submit'
        ].map((id) => ({ id, position: [...document.querySelectorAll('*')].indexOf(document.getElementById(id)) }))
        '''
    )
    assert all(item["position"] >= 0 for item in ordered_ids), ordered_ids
    assert [item["position"] for item in ordered_ids] == sorted(
        item["position"] for item in ordered_ids
    ), ordered_ids

    page.locator("#knowledge-classification-space").select_option("space-001")
    expect(page.locator("#knowledge-classification-department")).to_be_enabled()
    page.locator("#knowledge-classification-department").select_option("dept-after-sales")
    expect(page.locator("#knowledge-classification-category")).to_be_enabled()
    page.locator("#knowledge-classification-category").select_option("cat-refund")

    page.get_by_label("所有登录用户可访问").uncheck()
    expect(department_input).to_be_enabled()
    expect(role_input).to_be_enabled()
    expect(user_input).to_be_enabled()
    department_input.fill("dept-after-sales")

    summary_requests_before = api.request_count("GET", "/api/v1/documents/summary")
    document_requests_before = api.request_count("GET", "/api/v1/documents")

    page.locator("input[type=file]").set_input_files(str(failed_upload_file))
    page.get_by_role("button", name="▷ 一键构建解析任务").click()
    expect(page.get_by_text("模拟文档解析失败。")).to_be_visible()
    expect(page.get_by_text("PARSE_INVALID")).to_be_visible()
    expect(page.get_by_role("button", name="重试当前任务")).to_be_visible()
    expect(page.locator(".task-pipeline-step.failed")).to_have_count(1)

    page.locator("#knowledge-classification-space").select_option("space-001")
    page.locator("#knowledge-classification-department").select_option("dept-after-sales")
    page.locator("#knowledge-classification-category").select_option("cat-refund")
    page.get_by_label("所有登录用户可访问").uncheck()
    department_input.fill("dept-after-sales")
    page.locator("input[type=file]").set_input_files(str(upload_file))
    page.get_by_role("button", name="▷ 一键构建解析任务").click()
    expect(page.locator(".task-pipeline-step.completed")).to_have_count(4)
    expect(page.get_by_text("完成上架，可检索使用")).to_be_visible()
    expect(page.get_by_text("INDEXING")).to_have_count(0)
    expect(page.get_by_text("Refund SOP").first).to_be_visible()

    import_request = api.find_request("POST", "/api/v1/import-jobs")
    assert import_request["body"] == {
        "title": "playwright-refund",
        "classification": {
            "spaceId": "space-001",
            "departmentId": "dept-after-sales",
            "categoryId": "cat-refund",
        },
        "permission": {
            "allAuthenticated": False,
            "departmentIds": ["dept-after-sales"],
            "roleIds": [],
            "userIds": [],
        },
        "processingOptions": {"enableQaSplit": True, "enableEmbedding": True},
    }
    api.find_request("POST", "/api/v1/import-jobs/job-upload-failed/file")
    api.find_request("POST", "/api/v1/import-jobs/job-upload/file")
    assert api.request_count("GET", "/api/v1/documents/summary") > summary_requests_before
    assert api.request_count("GET", "/api/v1/documents") > document_requests_before
    page.screenshot(path=str(SCREENSHOT_DIR / "t09-knowledge-upload-desktop.png"), full_page=True)

def verify_document_filter_detail_edit_flow(page: Page, api: KnowledgeApiMock) -> None:
    page.goto(f"{APP_ORIGIN}/#documents", wait_until="networkidle")
    expect(page.get_by_role("heading", name="文档列表").first).to_be_visible()
    expect(page.get_by_text("Refund SOP").first).to_be_visible()
    expect(page.get_by_text("Unclassified FAQ").first).to_be_visible()
    expect(page.get_by_text("客服知识库 / 售后部 / 退款专题").first).to_be_visible()
    expect(page.get_by_text("退款需要主管审批。").first).to_be_visible()

    page.get_by_label("仅看未分类").check()
    expect(page.locator(".document-row", has_text="Unclassified FAQ")).to_be_visible()
    expect(page.locator(".document-row", has_text="Refund SOP")).to_have_count(0)
    api.find_request("GET", "/api/v1/documents", isUnclassified="true")

    page.get_by_label("选择文档 Unclassified FAQ").check()
    page.get_by_role("button", name="批量归类（1）").click()
    bulk_modal = page.get_by_role("dialog")
    expect(bulk_modal.get_by_role("heading", name="批量归类")).to_be_visible()
    bulk_modal.locator("#bulk-document-classification-space").select_option("space-001")
    expect(bulk_modal.locator("#bulk-document-classification-department")).to_be_enabled()
    bulk_modal.locator("#bulk-document-classification-department").select_option("dept-after-sales")
    expect(bulk_modal.locator("#bulk-document-classification-category")).to_be_enabled()
    bulk_modal.locator("#bulk-document-classification-category").select_option("cat-refund")
    bulk_modal.get_by_role("button", name="确认批量归类").click()
    expect(page.locator(".document-row", has_text="Unclassified FAQ")).to_have_count(0)
    bulk_request = api.find_request("PATCH", "/api/v1/documents/bulk-classification")
    assert bulk_request["body"] == {
        "documentIds": ["doc-unclassified"],
        "classification": {
            "spaceId": "space-001",
            "departmentId": "dept-after-sales",
            "categoryId": "cat-refund",
        },
    }

    page.get_by_label("仅看未分类").uncheck()
    expect(page.locator(".document-row", has_text="Refund SOP")).to_be_visible()

    page.locator("#document-list-classification-space").select_option("space-001")
    expect(page.locator("#document-list-classification-department")).to_be_enabled()
    page.locator("#document-list-classification-department").select_option("dept-after-sales")
    expect(page.locator("#document-list-classification-category")).to_be_enabled()
    page.locator("#document-list-classification-category").select_option("cat-refund")
    expect(page.get_by_text("客服知识库 / 售后部 / 退款专题").first).to_be_visible()

    filtered_request = api.find_request(
        "GET",
        "/api/v1/documents",
        spaceId="space-001",
        classificationDepartmentId="dept-after-sales",
        categoryId="cat-refund",
    )
    assert filtered_request["query"]["page"] == "1"
    assert filtered_request["query"]["pageSize"] == "20"

    page.get_by_role("button", name="编辑分类").click()
    modal = page.get_by_role("dialog")
    expect(modal.get_by_text("当前分类：客服知识库 / 售后部 / 退款专题")).to_be_visible()
    modal.locator("#document-classification-edit-category").select_option("cat-logistics")
    modal.get_by_role("button", name="保存分类").click()
    expect(page.get_by_text("客服知识库 / 售后部 / 物流专题").first).to_be_visible()

    update_request = api.find_request("PATCH", "/api/v1/documents/doc-ready/classification")
    assert update_request["body"] == {
        "spaceId": "space-001",
        "departmentId": "dept-after-sales",
        "categoryId": "cat-logistics",
    }

    page.locator("#document-list-classification-category").select_option("cat-logistics")
    expect(page.get_by_text("Refund SOP").first).to_be_visible()
    expect(page.get_by_text("客服知识库 / 售后部 / 物流专题").first).to_be_visible()
    api.find_request(
        "GET",
        "/api/v1/documents",
        spaceId="space-001",
        classificationDepartmentId="dept-after-sales",
        categoryId="cat-logistics",
    )
    page.screenshot(path=str(SCREENSHOT_DIR / "t09-knowledge-documents-desktop.png"), full_page=True)


def verify_category_migration_flow(page: Page, api: KnowledgeApiMock) -> None:
    page.goto(f"{APP_ORIGIN}/#knowledge-classification", wait_until="networkidle")
    expect(page.get_by_role("heading", name="知识库分类管理")).to_be_visible()
    page.get_by_role("tab", name="专题 / 项目").click()
    expect(page.get_by_text("物流专题").first).to_be_visible()

    page.locator(".classification-category-row", has_text="物流专题").get_by_role(
        "button", name="删除"
    ).click()
    page.get_by_role("dialog", name="删除确认").get_by_role("button", name="确认删除").click()
    expect(page.get_by_text("项目 / 专题「物流专题」下仍有 1 篇文档，请先迁移。")).to_be_visible()

    migration_dialog = page.locator(".classification-migration-modal")
    expect(migration_dialog.get_by_text("物流专题")).to_be_visible()
    migration_dialog.locator("#classification-document-migration-space").select_option("space-001")
    migration_dialog.locator("#classification-document-migration-department").select_option(
        "dept-after-sales"
    )
    migration_dialog.locator("#classification-document-migration-category").select_option("cat-refund")
    migration_dialog.get_by_role("button", name="确认迁移文档").click()
    expect(page.get_by_text("文档迁移成功，请重新执行删除。")).to_be_visible()

    migrate_request = api.find_request(
        "POST", "/api/v1/knowledge-categories/cat-logistics/migrate-documents"
    )
    assert migrate_request["body"] == {
        "targetSpaceId": "space-001",
        "targetDepartmentId": "dept-after-sales",
        "targetCategoryId": "cat-refund",
    }

    page.locator(".classification-category-row", has_text="物流专题").get_by_role(
        "button", name="删除"
    ).click()
    page.get_by_role("dialog", name="删除确认").get_by_role("button", name="确认删除").click()
    expect(page.get_by_text("项目 / 专题已删除。")).to_be_visible()
    api.find_request("DELETE", "/api/v1/knowledge-categories/cat-logistics")


def verify_intermediate_viewport_smoke(page: Page) -> list[str]:
    errors, _api = prepare_page(page)
    page.goto(f"{APP_ORIGIN}/#knowledge", wait_until="networkidle")
    expect(page.get_by_role("heading", name="文档解析与知识提炼中心")).to_be_visible()
    expect(page.get_by_role("heading", name="从原始文档到可检索知识")).to_be_visible()
    expect(page.get_by_role("heading", name="已同步与正在处理的文档")).to_be_visible()
    verify_no_overflow(page)
    return errors


def verify_mobile_smoke(page: Page) -> list[str]:
    errors, _api = prepare_page(page)
    page.goto(f"{APP_ORIGIN}/#knowledge", wait_until="networkidle")
    expect(page.get_by_role("heading", name="文档解析与知识提炼中心")).to_be_visible()
    expect(page.get_by_role("heading", name="从原始文档到可检索知识")).to_be_visible()
    expect(page.get_by_role("heading", name="已同步与正在处理的文档")).to_be_visible()
    expect(page.locator("#knowledge-classification-space")).to_be_visible()
    verify_no_overflow(page)
    page.screenshot(path=str(SCREENSHOT_DIR / "t09-knowledge-mobile.png"), full_page=True)
    return errors


def verify_no_overflow(page: Page) -> None:
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    if overflow:
        raise AssertionError("页面存在水平溢出")

    local_overflows = page.evaluate(
        """
        Array.from(document.querySelectorAll(
          '.panel, .document-table, .filter-grid, .pagination-row, .document-processing-workspace, .document-processing-list'
        ))
          .filter((element) => element.scrollWidth > element.clientWidth + 1)
          .map((element) => ({
            className: element.className,
            scrollWidth: element.scrollWidth,
            clientWidth: element.clientWidth
          }))
        """
    )
    if local_overflows:
        raise AssertionError(f"关键容器存在局部水平溢出: {local_overflows}")


def assert_phase_two_contracts(api: KnowledgeApiMock) -> None:
    api.find_request("POST", "/api/v1/import-jobs")
    api.find_request("POST", "/api/v1/import-jobs/job-upload/file")
    api.find_request("PATCH", "/api/v1/documents/doc-ready/classification")
    api.find_request("PATCH", "/api/v1/documents/bulk-classification")
    api.find_request("POST", "/api/v1/knowledge-spaces")
    api.find_request("PUT", "/api/v1/knowledge-spaces/space-created")
    api.find_request("DELETE", "/api/v1/knowledge-spaces/space-created")
    api.find_request("POST", "/api/v1/departments")
    api.find_request("PUT", "/api/v1/departments/dept-created")
    api.find_request("DELETE", "/api/v1/departments/dept-created")
    api.find_request("POST", "/api/v1/knowledge-categories")
    api.find_request("PUT", "/api/v1/knowledge-categories/cat-created")
    api.find_request("DELETE", "/api/v1/knowledge-categories/cat-created")
    api.find_request("POST", "/api/v1/knowledge-categories/cat-logistics/migrate-documents")
    api.find_request("DELETE", "/api/v1/knowledge-categories/cat-logistics")
    api.find_request("GET", "/api/v1/documents/summary")
    api.find_request("GET", "/api/v1/documents", page="1", pageSize="10")
    api.find_request("GET", "/api/v1/knowledge-spaces/stats")
    api.find_request(
        "GET",
        "/api/v1/knowledge-categories/stats",
        spaceId="space-001",
        departmentId="dept-after-sales",
    )


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop_errors, desktop_api = verify_phase_two_desktop_flow(desktop_page)
        assert_phase_two_contracts(desktop_api)
        desktop_page.close()

        intermediate_page = browser.new_page(viewport={"width": 1024, "height": 900})
        intermediate_errors = verify_intermediate_viewport_smoke(intermediate_page)
        intermediate_page.close()

        mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_errors = verify_mobile_smoke(mobile_page)
        mobile_page.close()
        browser.close()

    all_errors = desktop_errors + intermediate_errors + mobile_errors
    if all_errors:
        raise AssertionError(f"浏览器控制台存在错误或警告: {all_errors}")

    print("T09 Playwright phase-2 knowledge classification acceptance passed")
    print(f"classification={SCREENSHOT_DIR / 't09-knowledge-classification-desktop.png'}")
    print(f"upload={SCREENSHOT_DIR / 't09-knowledge-upload-desktop.png'}")
    print(f"documents={SCREENSHOT_DIR / 't09-knowledge-documents-desktop.png'}")
    print(f"mobile={SCREENSHOT_DIR / 't09-knowledge-mobile.png'}")


if __name__ == "__main__":
    main()
