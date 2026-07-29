import type { Schemas } from '../../api/schema-helpers';

export type ChatSession = {
  id: string;
  title: string | null;
  status: string;
  createdAt: string;
  updatedAt: string;
};

export type ChatMessage = {
  id: string;
  sessionId: string;
  role: 'USER' | 'ASSISTANT';
  content: string;
  status: string;
  requestId: string | null;
  createdAt: string;
};

export type ClassificationPath = Schemas['ClassificationPathResponse'];

export type ChatCitation = {
  runId: string;
  citationId: string;
  documentId: string | null;
  qaPairId: string | null;
  title?: string | null;
  pageNo?: number | null;
  quote: string;
  rank: number;
  score?: number;
  classification?: ClassificationPath | null;
};

export type CitationSource = {
  citationId: string;
  documentId: string | null;
  documentTitle: string | null;
  documentDeleted: boolean;
  pageNo: number | null;
  quote: string;
  sourceText: string;
  sourceLocator: Record<string, unknown>;
  classification?: ClassificationPath | null;
};

export type RetrievalExplanation = {
  runId: string;
  question: string;
  stages: Record<string, Array<Record<string, unknown>>>;
  filters: Record<string, unknown>;
  retrievalScope?: ClassificationPath | null;
};

export type StreamEvent = {
  type: string;
  data: Record<string, unknown>;
};

export type ChatRetrievalScope = Schemas['ChatRetrievalScope'];
export type SendMessagePayload = Schemas['ChatMessageRunRequest'];
