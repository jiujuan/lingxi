"""Run a resumable Adaptive Hierarchical Chunking backfill.

The command is intentionally conservative: operators see the database target,
number of eligible Documents and dry-run mode before any mutation.  Production
writes additionally require an explicit confirmation flag.
"""

from __future__ import annotations

import argparse
from uuid import uuid4

from sqlalchemy.engine import make_url

from server.app.core.config import settings
from server.app.core.service_factory import ServiceDependencies
from server.app.db.session import SessionLocal
from server.app.services.chunk_backfill_service import BackfillOptions, ChunkBackfillService
from server.app.services.chunking import ChunkingService
from server.app.tasks.maintenance_tasks import schedule_qa_rebuild


def _build_service(session) -> ChunkBackfillService:
    dependencies = ServiceDependencies.from_settings()
    counter = dependencies.build_token_counter()
    return ChunkBackfillService(
        session,
        chunking_service=ChunkingService(counter),
        chunking_policy=dependencies.build_chunk_policy(counter),
        qa_rebuilder=lambda document, enqueue_embedding: schedule_qa_rebuild(
            session, document, enqueue_embedding=enqueue_embedding
        ),
    )


def _options(args: argparse.Namespace) -> BackfillOptions:
    return BackfillOptions(
        tenant_id=args.tenant_id,
        document_id=args.document_id,
        from_chunker_version=args.from_chunker_version,
        to_chunker_version=args.to_chunker_version,
        batch_size=args.batch_size,
        resume_after=args.resume_after,
        dry_run=args.dry_run,
        rebuild_qa=args.rebuild_qa,
        rebuild_embedding=args.rebuild_embedding,
        execution_id=args.execution_id or str(uuid4()),
        operator_id=args.operator_id,
        audit_source="cli",
        audit_reason=args.reason,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill versioned adaptive chunks")
    parser.add_argument("--tenant-id")
    parser.add_argument("--document-id")
    parser.add_argument("--from-chunker-version")
    parser.add_argument("--to-chunker-version")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--resume-after")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild-qa", action="store_true")
    parser.add_argument("--rebuild-embedding", action="store_true")
    parser.add_argument("--execution-id")
    parser.add_argument("--operator-id")
    parser.add_argument("--reason")
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        help="required for a non-dry-run when APP_ENV is production",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.dry_run and not args.operator_id:
        parser.error("non-dry-run requires --operator-id")
    if settings.environment.lower() == "production" and not args.dry_run and not args.confirm_production:
        parser.error("production non-dry-run requires --confirm-production")

    options = _options(args)
    database = make_url(settings.database_url)
    host = database.host or "local"
    name = database.database or "unknown"
    with SessionLocal() as session:
        service = _build_service(session)
        target_count = service.count_targets(
            options,
            task_type="backfill_adaptive_chunks_cli",
        )
        print(
            f"databaseHost={host} databaseName={name} targetCount={target_count} "
            f"dryRun={options.dry_run} executionId={options.execution_id}"
        )
        result = service.backfill(
            options,
            task_type="backfill_adaptive_chunks_cli",
            queue_name="maintenance",
        )
    print(result.as_dict())


if __name__ == "__main__":
    main()
