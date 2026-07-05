import json
from time import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.core.secrets import decrypt_secret
from server.app.integrations.model_providers.registry import build_provider_adapter
from server.app.models.document import Document
from server.app.models.model_config import ModelCapability, ModelConfig, ModelProvider
from server.app.repositories.query_run_repo import QueryRunRepository
from server.app.schemas.retrieval import RetrievalAccessScope, RetrievalCandidate
from server.app.services.prompt_service import PromptService
from server.app.services.retrieval_service import RetrievalService


class OpenAICompatibleService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.prompt_service = PromptService()
        self.run_repo = QueryRunRepository(session)

    def create_completion(self, api_key, payload) -> dict:
        question = self._last_user_message(payload.messages)
        retrieval = self._retrieve(api_key, question)
        run_public_id = f"chatcmpl_{uuid4().hex}"
        run = self.run_repo.create_run(
            tenant_id=api_key.tenant_id,
            run_id=run_public_id,
            session_id=None,
            user_message_id=None,
            question=question,
            request_id=current_request_id(),
            retrieval_snapshot=retrieval.snapshot,
        )

        if retrieval.has_answer:
            answer = self._complete_answer(api_key.tenant_id, question, retrieval.candidates)
            status = "COMPLETED"
        else:
            answer = self.prompt_service.refusal_text
            status = "NO_ANSWER"

        run.status = status
        citations = self._persist_citations(api_key.tenant_id, run.id, retrieval.candidates if retrieval.has_answer else [])
        self.session.commit()
        return {
            "id": run_public_id,
            "object": "chat.completion",
            "created": int(time()),
            "model": payload.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "citations": citations,
            "request_id": current_request_id(),
        }

    def stream_completion(self, api_key, payload):
        question = self._last_user_message(payload.messages)
        retrieval = self._retrieve(api_key, question)
        run_public_id = f"chatcmpl_{uuid4().hex}"
        run = self.run_repo.create_run(
            tenant_id=api_key.tenant_id,
            run_id=run_public_id,
            session_id=None,
            user_message_id=None,
            question=question,
            request_id=current_request_id(),
            retrieval_snapshot=retrieval.snapshot,
        )
        self.session.commit()

        if retrieval.has_answer:
            prompt = self.prompt_service.build_chat_prompt(question, retrieval.candidates)
            adapter = self._default_chat_adapter(api_key.tenant_id)
            answer_chunks = adapter.stream_chat(prompt)
            for delta in answer_chunks:
                yield self._data(
                    {
                        "id": run_public_id,
                        "object": "chat.completion.chunk",
                        "created": int(time()),
                        "model": payload.model,
                        "choices": [{"index": 0, "delta": {"content": delta}}],
                    }
                )
            citations = self._persist_citations(api_key.tenant_id, run.id, retrieval.candidates)
            run.status = "COMPLETED"
            self.session.commit()
            for citation in citations:
                yield self._data({"type": "citation", "citation": citation})
        else:
            run.status = "NO_ANSWER"
            self.session.commit()
            yield self._data(
                {
                    "id": run_public_id,
                    "object": "chat.completion.chunk",
                    "created": int(time()),
                    "model": payload.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": self.prompt_service.refusal_text},
                        }
                    ],
                }
            )

        yield "data: [DONE]\n\n"

    def _retrieve(self, api_key, question: str):
        context = AccessContext(
            tenant_id=api_key.tenant_id,
            user_id=api_key.id,
            department_id=(api_key.allowed_department_ids or [None])[0],
            role_ids=api_key.allowed_role_ids or [],
            permissions={"CHAT_READ"},
            role_codes=set(),
            department_ids=api_key.allowed_department_ids or [],
        )
        return RetrievalService(self.session).retrieve(
            context,
            question,
            access_scope=RetrievalAccessScope(document_ids=None),
        )

    def _complete_answer(
        self, tenant_id: str, question: str, candidates: list[RetrievalCandidate]
    ) -> str:
        prompt = self.prompt_service.build_chat_prompt(question, candidates)
        return self._default_chat_adapter(tenant_id).complete_chat(prompt)

    def _persist_citations(
        self, tenant_id: str, run_db_id: str, candidates: list[RetrievalCandidate]
    ) -> list[dict]:
        citations: list[dict] = []
        for rank, candidate in enumerate(candidates, start=1):
            quote = candidate.quote or candidate.answer
            db_citation = self.run_repo.add_citation(
                tenant_id=tenant_id,
                run_db_id=run_db_id,
                message_id=None,
                document_id=candidate.document_id,
                qa_pair_id=candidate.qa_pair_id,
                quote=quote,
                rank=rank,
                snapshot=candidate.to_snapshot(),
            )
            document = self.session.get(Document, candidate.document_id)
            citations.append(
                {
                    "id": db_citation.id,
                    "document_id": candidate.document_id,
                    "qa_pair_id": candidate.qa_pair_id,
                    "title": document.title if document is not None else None,
                    "page_no": candidate.page_no,
                    "quote": quote,
                    "rank": rank,
                    "score": round(candidate.rerank_score, 6),
                }
            )
        return citations

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
        return build_provider_adapter(
            provider.provider_type,
            provider.base_url,
            decrypt_secret(provider.encrypted_api_key),
            {**(provider.config or {}), **(model_config.config or {})},
            model_name=model_config.model_name,
            timeout_ms=model_config.timeout_ms,
        )

    @staticmethod
    def _last_user_message(messages) -> str:
        for message in reversed(messages):
            if message.role == "user" and message.content.strip():
                return message.content.strip()
        raise ValueError("messages must contain a user message")

    @staticmethod
    def _data(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
