import { apiRequest } from '../../../api/client';
import type { CitationSource, RetrievalExplanation } from '../types';

export function getCitationSource(citationId: string) {
  return apiRequest<CitationSource>(`/api/v1/citations/${citationId}/source`);
}

export function getRetrievalExplanation(runId: string) {
  return apiRequest<RetrievalExplanation>(`/api/v1/query-runs/${runId}/retrieval-explanation`);
}
