from pydantic import BaseModel, ConfigDict, Field

from server.app.schemas.classification import ClassificationPathResponse


class QueryRunResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    run_id: str = Field(alias="runId")
    session_id: str | None = Field(alias="sessionId")
    question: str
    status: str
    latency_ms: int | None = Field(alias="latencyMs")
    request_id: str | None = Field(alias="requestId")
    retrieval_scope: ClassificationPathResponse | None = Field(
        default=None, alias="retrievalScope"
    )


class RetrievalExplanationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(alias="runId")
    question: str
    stages: dict
    filters: dict
    retrieval_scope: ClassificationPathResponse | None = Field(
        default=None, alias="retrievalScope"
    )
