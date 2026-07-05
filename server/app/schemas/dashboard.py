from pydantic import BaseModel, ConfigDict, Field


class DashboardMetricResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_count: int = Field(alias="documentCount")
    qa_pair_count: int = Field(alias="qaPairCount")
    task_success_rate: float = Field(alias="taskSuccessRate")
    task_failure_rate: float = Field(alias="taskFailureRate")
    api_call_count: int = Field(alias="apiCallCount")


class IngestionHealthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success_rate: float = Field(alias="successRate")
    failure_rate: float = Field(alias="failureRate")
    stages: list[dict]
    trend: list[dict]


class QaHealthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query_count: int = Field(alias="queryCount")
    citation_coverage_rate: float = Field(alias="citationCoverageRate")
    refusal_rate: float = Field(alias="refusalRate")
    hit_rate: float = Field(alias="hitRate")
    first_token_latency_ms: int = Field(alias="firstTokenLatencyMs")


class DashboardSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    metrics: DashboardMetricResponse
    ingestion_health: IngestionHealthResponse = Field(alias="ingestionHealth")
    qa_health: QaHealthResponse = Field(alias="qaHealth")
    recent_tasks: list[dict] = Field(alias="recentTasks")
    risk_events: list[dict] = Field(alias="riskEvents")
