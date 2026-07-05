from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.models.import_job import ImportJob, ImportJobFile


class ImportJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, job_id: str) -> ImportJob | None:
        return self.session.get(ImportJob, job_id)

    def get_for_tenant(self, tenant_id: str, job_id: str) -> ImportJob | None:
        return self.session.scalar(
            select(ImportJob).where(
                ImportJob.tenant_id == tenant_id,
                ImportJob.id == job_id,
                ImportJob.deleted_at.is_(None),
            )
        )

    def add(self, job: ImportJob) -> ImportJob:
        self.session.add(job)
        self.session.flush()
        return job

    def list_files(self, tenant_id: str, job_id: str) -> list[ImportJobFile]:
        return list(
            self.session.scalars(
                select(ImportJobFile)
                .where(
                    ImportJobFile.tenant_id == tenant_id,
                    ImportJobFile.job_id == job_id,
                )
                .order_by(ImportJobFile.id)
            ).all()
        )
