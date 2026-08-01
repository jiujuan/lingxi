from types import SimpleNamespace

from server.app.core.permissions import AccessContext
from server.app.schemas.retrieval import RetrievalCandidate
from server.app.services.chat_service import ChatService
from server.app.services.openai_compatible_service import OpenAICompatibleService


SENSITIVE_SNAPSHOT_FIELDS = {"question", "titlePath", "content", "quote", "embedding"}


class _RecordingRunRepository:
    def __init__(self):
        self.snapshots: list[dict] = []

    def add_citation(self, **kwargs):
        self.snapshots.append(kwargs["snapshot"])
        return SimpleNamespace(id="citation-1", quote=kwargs["quote"])


def _sensitive_candidate() -> RetrievalCandidate:
    candidate = RetrievalCandidate(
        qa_pair_id="qa-1",
        document_id="document-1",
        question="退款审批问题",
        answer="退款需要主管审批",
        quote="退款需要主管审批",
        page_no=3,
        pair_index=1,
        vector_score=0.2,
        text_score=0.3,
        rrf_score=0.4,
        rerank_score=0.9,
        evidence_id="evidence-1",
        evidence_type="CHUNK",
        chunk_id="chunk-1",
        parent_chunk_id="parent-1",
        page_start=3,
        page_end=4,
        channel_scores={"chunk_vector": 0.8},
        channel_ranks={"chunk_vector": 1},
        fused_score=0.8,
    )
    candidate.to_snapshot = lambda: {
        "qaPairId": "qa-1",
        "documentId": "document-1",
        "evidenceId": "evidence-1",
        "evidenceType": "CHUNK",
        "chunkId": "chunk-1",
        "parentChunkId": "parent-1",
        "pageNo": 3,
        "rank": 1,
        "rerankScore": 0.9,
        "fusedScore": 0.8,
        "channelRanks": {"chunk_vector": 1},
        "channelScores": {"chunk_vector": 0.8},
        "question": "退款审批问题",
        "titlePath": ["财务", "退款"],
        "content": "只允许作为上下文使用的正文",
        "quote": "不应进入 snapshot 的引用正文",
        "embedding": [0.1, 0.2],
    }
    return candidate


def _assert_safe_citation_snapshot(snapshot: dict) -> None:
    assert not (SENSITIVE_SNAPSHOT_FIELDS & snapshot.keys())
    assert snapshot == {
        "qaPairId": "qa-1",
        "documentId": "document-1",
        "evidenceId": "evidence-1",
        "evidenceType": "CHUNK",
        "chunkId": "chunk-1",
        "parentChunkId": "parent-1",
        "pageNo": 3,
        "rank": 1,
        "rerankScore": 0.9,
        "fusedScore": 0.8,
        "channelRanks": {"chunk_vector": 1},
        "channelScores": {"chunk_vector": 0.8},
    }


def test_openai_citation_persistence_sanitizes_candidate_snapshot():
    session = SimpleNamespace(get=lambda _model, _document_id: SimpleNamespace(title="退款流程"))
    service = OpenAICompatibleService(session)
    repository = _RecordingRunRepository()
    service.run_repo = repository

    citations = service._persist_citations("tenant-1", "run-db-1", [_sensitive_candidate()])

    assert citations[0]["quote"] == "退款需要主管审批"
    _assert_safe_citation_snapshot(repository.snapshots[0])


def test_chat_citation_persistence_sanitizes_candidate_snapshot(monkeypatch):
    import server.app.services.chat_service as chat_module

    class FakeSession:
        def commit(self):
            pass

    class FakeChatRepository:
        def __init__(self):
            self.message_count = 0

        def add_message(self, *_args):
            self.message_count += 1
            return SimpleNamespace(id=f"message-{self.message_count}")

    class FakeRunRepository(_RecordingRunRepository):
        def create_run(self, **_kwargs):
            return SimpleNamespace(id="run-db-1", status="RUNNING", assistant_message_id=None, latency_ms=None)

    class FakeRetrievalService:
        def retrieve(self, *_args, **_kwargs):
            return SimpleNamespace(
                has_answer=True,
                candidates=[_sensitive_candidate()],
                snapshot={"filters": {}},
            )

    class FakeClassificationPathService:
        def __init__(self, _session):
            pass

        def for_scope_filters(self, *_args):
            return None

        def for_document(self, *_args):
            return None

    session = FakeSession()
    service = ChatService(session)
    service.chat_repo = FakeChatRepository()
    repository = FakeRunRepository()
    service.run_repo = repository
    service._default_chat_adapter = lambda _tenant_id: SimpleNamespace(stream_chat=lambda _prompt: ["回答"])
    service._document_titles = lambda _document_ids: {"document-1": "退款流程"}
    service._documents_by_id = lambda _document_ids: {"document-1": SimpleNamespace()}
    monkeypatch.setattr(chat_module, "build_retrieval_service", lambda *_args, **_kwargs: FakeRetrievalService())
    monkeypatch.setattr(chat_module, "ClassificationPathService", FakeClassificationPathService)

    events = list(
        service._run_stream(
            AccessContext(
                tenant_id="tenant-1", user_id="user-1", permissions={"CHAT_READ"},
                role_ids=[], role_codes=set(), department_ids=[], department_id=None,
            ),
            "session-1",
            "退款怎么审批",
            None,
        )
    )

    assert any("event: citation" in event for event in events)
    _assert_safe_citation_snapshot(repository.snapshots[0])
