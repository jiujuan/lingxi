from sqlalchemy import select

from server.app.integrations.tokenizers.jieba_tokenizer import JiebaTokenizer
from server.app.models.document import Document
from server.app.models.qa_pair import DocumentChunk
from server.app.services.embedding_service import build_search_text
from server.scripts.backfill_search_text import backfill_search_text
from server.tests.test_embedding_task import add_qa_pairs
from server.tests.test_qa_split_task import build_qa_session, create_qa_ready_job


def _session_with_pairs():
    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, chunks = create_qa_ready_job(session, identity)
    pairs = add_qa_pairs(
        session, tenant_id, document_id, job_id, [chunk.id for chunk in chunks]
    )
    document = session.get(Document, pairs[0].document_id)
    chunks = {item.id: item for item in session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()}
    return session, document, chunks, pairs


def test_backfill_rewrites_stale_rows_and_skips_current_and_pending_rows():
    session, document, chunks, pairs = _session_with_pairs()
    tokenizer = JiebaTokenizer()
    # pairs[0]: 旧 unigram 格式，需要重算；pairs[1]: 已是当前分词器输出，应跳过
    pairs[0].search_text = "退 款 需 要 主 管 审 批"
    pairs[0].token_count = 7
    pairs[1].search_text = build_search_text(tokenizer, pairs[1], document, chunks[pairs[1].chunk_id])
    pairs[1].token_count = len(pairs[1].search_text.split())
    session.commit()

    # batch_size=1 同时覆盖 keyset 分页路径
    result = backfill_search_text(session, batch_size=1)

    assert result == {"updated": 1, "unchanged": 1}
    session.refresh(pairs[0])
    assert pairs[0].search_text == build_search_text(tokenizer, pairs[0], document, chunks[pairs[0].chunk_id])
    assert pairs[0].token_count == len(pairs[0].search_text.split())
    assert " 退 款 " not in f" {pairs[0].search_text} "


def test_backfill_ignores_rows_without_search_text():
    session, document, chunks, pairs = _session_with_pairs()
    # 未嵌入的行 search_text 为空串，应完全不被触碰
    assert all(item.search_text == "" for item in pairs)

    result = backfill_search_text(session)

    assert result == {"updated": 0, "unchanged": 0}


def test_backfill_dry_run_reports_without_writing():
    session, document, chunks, pairs = _session_with_pairs()
    pairs[0].search_text = "退 款 需 要 主 管 审 批"
    session.commit()

    result = backfill_search_text(session, dry_run=True)

    assert result["updated"] == 1
    session.refresh(pairs[0])
    assert pairs[0].search_text == "退 款 需 要 主 管 审 批"



def test_backfill_includes_document_title_and_source_chunk_title_path_idempotently():
    session, document, chunks, pairs = _session_with_pairs()
    tokenizer = JiebaTokenizer()
    pairs[0].search_text = "legacy stale text"
    session.commit()

    first = backfill_search_text(session)
    second = backfill_search_text(session)

    expected = build_search_text(tokenizer, pairs[0], document, chunks[pairs[0].chunk_id])
    session.refresh(pairs[0])
    assert first["updated"] == 1
    assert second == {"updated": 0, "unchanged": 1}
    assert pairs[0].search_text == expected
    assert "refund" in pairs[0].search_text
    assert "退款 流程" in pairs[0].search_text
