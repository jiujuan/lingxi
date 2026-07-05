export type SystemSettings = {
  filePolicy: {
    maxFileSizeMb: number;
    allowedExtensions: string[];
    defaultParser: string;
    ocrEnabled: boolean;
    fallbackEnabled: boolean;
  };
  retrievalPolicy: {
    vectorTopK: number;
    textTopK: number;
    finalTopK: number;
    lowConfidenceThreshold: number;
  };
  rateLimitPolicy: {
    apiKeyDefaultPerMinute: number;
    chatPerMinute: number;
  };
  storagePolicy: {
    backend: string;
    bucket: string | null;
    prefix: string;
  };
  retentionPolicy: {
    apiCallLogDays: number;
    auditLogDays: number;
    taskRunDays: number;
    softDeleteDays: number;
  };
  effectiveScopes: Record<string, string>;
};
