from collections.abc import Iterator
from time import perf_counter
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.core.errors import bad_request, not_found
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.core.secrets import decrypt_secret
from server.app.integrations.model_providers.registry import (
    ProviderFactory,
    build_provider_adapter,
)
from server.app.models.document import Document
from server.app.models.model_config import ModelCapability, ModelConfig, ModelProvider
from server.app.repositories.chat_repo import ChatRepository
from server.app.repositories.feedback_repo import FeedbackRepository
from server.app.repositories.query_run_repo import QueryRunRepository
from server.app.services.prompt_service import PromptService
from server.app.services.retrieval_service import RetrievalService
from server.app.services.sse_service import SseService


class ChatService:
    def __init__(
        self,
        session: Session,
        provider_factory: ProviderFactory = build_provider_adapter,
    ) -> None:
        self.session = session
        self.chat_repo = ChatRepository(session)
        self.run_repo = QueryRunRepository(session)
        self.prompt_service = PromptService()
        self.sse = SseService()
        self._build_adapter = provider_factory

    def create_session(self, context: AccessContext, title: str | None):
        chat_session = self.chat_repo.create_session(context.tenant_id, context.user_id, title)
        self.session.commit()
        return chat_session

    def list_sessions(self, context: AccessContext):
        return self.chat_repo.list_sessions(context.tenant_id, context.user_id)

    def list_messages(self, context: AccessContext, session_id: str):
        messages = self.chat_repo.list_messages(
            context.tenant_id, context.user_id, session_id
        )
        if not messages and self.chat_repo.get_session(context.tenant_id, context.user_id, session_id) is None:
            raise not_found("会话不存在")
        return messages

    def record_feedback(self, context: AccessContext, message_id: str, feedback: str):
        message = FeedbackRepository(self.session).mark_feedback(
            context.tenant_id, message_id, feedback
        )
        if message is None:
            raise not_found("消息不存在")
        self.session.commit()
        return message

    def stream_message_run(
        self, context: AccessContext, session_id: str, content: str
    ) -> Iterator[str]:
        """Validate preconditions eagerly, then return the streaming generator.

        Validation runs here (not inside the generator) so a missing session or
        empty message raises 404/400 *before* the StreamingResponse sends its 200
        headers. A generator body cannot do this: its code only runs once the
        response is already being iterated.
        """
        chat_session = self.chat_repo.get_session(
            context.tenant_id, context.user_id, session_id
        )
        if chat_session is None:
            raise not_found("会话不存在")
        content = content.strip()
        if not content:
            raise bad_request("EMPTY_MESSAGE", "消息内容不能为空")
        return self._run_stream(context, session_id, content)

    def _run_stream(
        self, context: AccessContext, session_id: str, content: str
    ) -> Iterator[str]:
        request_id = current_request_id()
        started = perf_counter()
        user_message = self.chat_repo.add_message(
            context.tenant_id, session_id, "USER", content, request_id
        )
        retrieval = RetrievalService(
            self.session, provider_factory=self._build_adapter
        ).retrieve(context, content)
        run_public_id = f"run_{uuid4().hex}"
        run = self.run_repo.create_run(
            tenant_id=context.tenant_id,
            run_id=run_public_id,
            session_id=session_id,
            user_message_id=user_message.id,
            question=content,
            request_id=request_id,
            retrieval_snapshot=retrieval.snapshot,
        )
        self.session.commit()

        yield self.sse.event(
            "run_started",
            {
                "runId": run_public_id,
                "requestId": request_id,
                "userMessageId": user_message.id,
            },
        )

        if not retrieval.has_answer:
            assistant_message = self.chat_repo.add_message(
                context.tenant_id,
                session_id,
                "ASSISTANT",
                self.prompt_service.refusal_text,
                request_id,
                "COMPLETED",
            )
            run.status = "NO_ANSWER"
            run.assistant_message_id = assistant_message.id
            run.latency_ms = int((perf_counter() - started) * 1000)
            self.session.commit()
            yield self.sse.event(
                "delta",
                {"runId": run_public_id, "content": self.prompt_service.refusal_text},
            )
            yield self.sse.event(
                "done",
                {
                    "runId": run_public_id,
                    "messageId": assistant_message.id,
                    "requestId": request_id,
                    "status": "NO_ANSWER",
                },
            )
            return

        prompt = self.prompt_service.build_chat_prompt(content.strip(), retrieval.candidates)
        answer_parts: list[str] = []
        try:
            adapter = self._default_chat_adapter(context.tenant_id)
            for delta in adapter.stream_chat(prompt):
                if not delta:
                    continue
                answer_parts.append(delta)
                yield self.sse.event("delta", {"runId": run_public_id, "content": delta})
            answer = "".join(answer_parts).strip()
            if not answer:
                raise RuntimeError("EMPTY_MODEL_RESPONSE")
        except Exception as exc:
            run.status = "FAILED"
            run.latency_ms = int((perf_counter() - started) * 1000)
            self.session.commit()
            yield self.sse.event(
                "error",
                {
                    "runId": run_public_id,
                    "requestId": request_id,
                    "code": "MODEL_CALL_FAILED",
                    "message": str(exc) if str(exc) else "模型调用失败",
                },
            )
            return

        assistant_message = self.chat_repo.add_message(
            context.tenant_id,
            session_id,
            "ASSISTANT",
            answer,
            request_id,
            "COMPLETED",
        )
        run.status = "COMPLETED"
        run.assistant_message_id = assistant_message.id
        run.latency_ms = int((perf_counter() - started) * 1000)
        titles = self._document_titles({c.document_id for c in retrieval.candidates})
        for rank, candidate in enumerate(retrieval.candidates, start=1):
            citation = self.run_repo.add_citation(
                tenant_id=context.tenant_id,
                run_db_id=run.id,
                message_id=assistant_message.id,
                document_id=candidate.document_id,
                qa_pair_id=candidate.qa_pair_id,
                quote=candidate.quote or candidate.answer,
                rank=rank,
                snapshot=candidate.to_snapshot(),
            )
            yield self.sse.event(
                "citation",
                {
                    "runId": run_public_id,
                    "citationId": citation.id,
                    "documentId": candidate.document_id,
                    "qaPairId": candidate.qa_pair_id,
                    "title": titles.get(candidate.document_id),
                    "quote": citation.quote,
                    "rank": rank,
                    "pageNo": candidate.page_no,
                    "score": round(candidate.rerank_score, 6),
                },
            )
        self.session.commit()
        yield self.sse.event(
            "done",
            {
                "runId": run_public_id,
                "messageId": assistant_message.id,
                "requestId": request_id,
                "status": "COMPLETED",
            },
        )

    def _default_chat_adapter(self, tenant_id: str):
        row = self.session.execute(
            select(ModelConfig, ModelProvider)
            .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
            .where(
                ModelConfig.tenant_id == tenant_id,
                ModelConfig.capability == ModelCapability.CHAT.value,
                ModelConfig.is_default.is_(True),
                ModelConfig.status == "ACTIVE",
                ModelConfig.deleted_at.is_(None),
                ModelProvider.status == "ACTIVE",
                ModelProvider.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            raise RuntimeError("CHAT_MODEL_MISSING")
        model_config, provider = row
        return self._build_adapter(
            provider.provider_type,
            provider.base_url,
            decrypt_secret(provider.encrypted_api_key),
            {**(provider.config or {}), **(model_config.config or {})},
            model_name=model_config.model_name,
            timeout_ms=model_config.timeout_ms,
        )

    def _document_titles(self, document_ids: set[str]) -> dict[str, str | None]:
        if not document_ids:
            return {}
        rows = self.session.execute(
            select(Document.id, Document.title).where(Document.id.in_(document_ids))
        ).all()
        return {row.id: row.title for row in rows}
