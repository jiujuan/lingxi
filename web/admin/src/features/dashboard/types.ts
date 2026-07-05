export type DashboardSummary = {
  metrics: {
    documentCount: number;
    qaPairCount: number;
    taskSuccessRate: number;
    taskFailureRate: number;
    apiCallCount: number;
  };
  ingestionHealth: {
    successRate: number;
    failureRate: number;
    stages: Array<{
      stage: string;
      successCount: number;
      failureCount: number;
      totalCount: number;
    }>;
    trend: Array<Record<string, unknown>>;
  };
  qaHealth: {
    queryCount: number;
    citationCoverageRate: number;
    refusalRate: number;
    hitRate: number;
    firstTokenLatencyMs: number;
  };
  recentTasks: Array<{
    id: string;
    taskType: string;
    status: string;
    stage: string | null;
    requestId: string | null;
    createdAt: string;
  }>;
  riskEvents: Array<{
    type: string;
    severity: string;
    message: string;
    requestId: string | null;
    createdAt: string;
  }>;
};

