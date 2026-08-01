"""Idempotently refresh stored QA FTS text after tokenizer/template changes."""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.db.session import SessionLocal
from server.app.integrations.tokenizers.jieba_tokenizer import JiebaTokenizer
from server.app.models.document import Document
from server.app.models.qa_pair import DocumentChunk, QaPair
from server.app.services.embedding_service import build_search_text


def backfill_search_text(
    session: Session, batch_size: int = 500, dry_run: bool = False
) -> dict:
    tokenizer = JiebaTokenizer()
    updated = 0
    unchanged = 0
    last_id = ""
    while True:
        rows = session.execute(
            select(QaPair, Document, DocumentChunk)
            .join(Document, Document.id == QaPair.document_id)
            .outerjoin(DocumentChunk, DocumentChunk.id == QaPair.chunk_id)
            .where(
                QaPair.deleted_at.is_(None),
                QaPair.search_text != "",
                QaPair.id > last_id,
            )
            .order_by(QaPair.id)
            .limit(batch_size)
        ).all()
        if not rows:
            break
        last_id = rows[-1][0].id
        for qa_pair, document, source_chunk in rows:
            new_text = build_search_text(tokenizer, qa_pair, document, source_chunk)
            if qa_pair.search_text == new_text:
                unchanged += 1
                continue
            updated += 1
            if not dry_run:
                qa_pair.search_text = new_text
                qa_pair.token_count = len(new_text.split())
        if not dry_run:
            session.commit()
    return {"updated": updated, "unchanged": unchanged}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute qa_pairs.search_text with the current tokenizer"
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        result = backfill_search_text(
            session, batch_size=args.batch_size, dry_run=args.dry_run
        )
    verb = "would update" if args.dry_run else "updated"
    print(
        f"{verb} {result['updated']} qa_pair(s); "
        f"{result['unchanged']} already current"
    )


if __name__ == "__main__":
    main()
