"""Recompute ``qa_pairs.search_text`` with the current search tokenizer.

Run this once after any tokenizer behavior change (e.g. the unigram -> jieba
word migration, a jieba upgrade, or a new user dictionary): stored
``search_text`` must be re-tokenized, otherwise word-level query lexemes no
longer match the old index entries and the text retrieval channel silently
returns nothing for pre-existing rows. PostgreSQL recomputes the
``search_vector`` generated column and its GIN index automatically on UPDATE.

Deployment order: deploy the new code first, then run this immediately. Rows
imported during the window are already written with the new tokenizer; only
pre-existing rows stay stale until the backfill finishes.

Usage::

    python -m server.scripts.backfill_search_text [--batch-size N] [--dry-run]

Idempotent: rows whose search_text already matches the current tokenizer
output are skipped. Rows with empty search_text have not been embedded yet
and are left alone (the embedding task will populate them).
"""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

import server.app.db.base  # noqa: F401  (registers all models before qa_pair import)
from server.app.db.session import SessionLocal
from server.app.integrations.tokenizers.jieba_tokenizer import JiebaTokenizer
from server.app.models.qa_pair import QaPair
from server.app.services.embedding_service import build_search_text


def backfill_search_text(
    session: Session, batch_size: int = 500, dry_run: bool = False
) -> dict:
    tokenizer = JiebaTokenizer()
    updated = 0
    unchanged = 0
    last_id = ""
    while True:
        rows = session.scalars(
            select(QaPair)
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
        last_id = rows[-1].id
        for qa_pair in rows:
            new_text = build_search_text(tokenizer, qa_pair)
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
