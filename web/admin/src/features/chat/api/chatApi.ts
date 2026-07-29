import { ApiError, apiRequest, toApiError } from '../../../api/client';
import { getToken, redirectToLogin } from '../../../auth/authStore';
import type {
  ChatCitation,
  ChatMessage,
  ChatRetrievalScope,
  ChatSession,
  SendMessagePayload,
  StreamEvent,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export function listChatSessions() {
  return apiRequest<{ data: ChatSession[] }>('/api/v1/chat/sessions');
}

export function createChatSession(title?: string) {
  return apiRequest<ChatSession>('/api/v1/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
}

export function listChatMessages(sessionId: string) {
  return apiRequest<{ data: ChatMessage[] }>(`/api/v1/chat/sessions/${sessionId}/messages`);
}

export function sendFeedback(messageId: string, feedback: 'up' | 'down') {
  return apiRequest<{ id: string; status: string }>(`/api/v1/chat/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ feedback }),
  });
}

export async function streamChatMessage(
  sessionId: string,
  payload: SendMessagePayload,
  handlers: {
    onEvent: (event: StreamEvent) => void;
    onCitation: (citation: ChatCitation) => void;
  },
  options: { signal?: AbortSignal } = {},
) {
  const token = getToken();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/chat/sessions/${sessionId}/message-runs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(toMessageRunBody(payload)),
      signal: options.signal,
    });
  } catch (cause) {
    if ((cause as Error)?.name === 'AbortError') {
      throw cause; // user stopped / navigated away — caller ignores
    }
    throw new ApiError(0, 'NETWORK_ERROR', '网络异常，请检查连接后重试');
  }

  if (!response.ok || !response.body) {
    const error = await toApiError(response);
    if (response.status === 401 && token) {
      redirectToLogin();
    }
    throw error;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  // Idle watchdog: the server sends heartbeat comments (~15s), so a long total
  // silence means the connection is dead. Abort with a clear message.
  const IDLE_TIMEOUT_MS = 60_000;
  const readChunk = () =>
    new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new ApiError(0, 'STREAM_TIMEOUT', '响应超时，连接可能已断开')),
        IDLE_TIMEOUT_MS,
      );
      reader.read().then(
        (result) => {
          clearTimeout(timer);
          resolve(result);
        },
        (cause) => {
          clearTimeout(timer);
          reject(cause);
        },
      );
    });

  try {
    while (true) {
      const { value, done } = await readChunk();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let separator = buffer.indexOf('\n\n');
      while (separator !== -1) {
        const block = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        dispatchBlock(block, handlers);
        separator = buffer.indexOf('\n\n');
      }
    }
    // Flush any trailing complete block left without a terminating blank line.
    if (buffer.trim()) {
      dispatchBlock(buffer, handlers);
    }
  } finally {
    // Ensure the underlying connection is released on stop/error.
    reader.cancel().catch(() => undefined);
  }
}

function toMessageRunBody(payload: SendMessagePayload): SendMessagePayload {
  const retrievalScope = normalizeRetrievalScope(payload.retrievalScope);
  return retrievalScope
    ? { content: payload.content, retrievalScope }
    : { content: payload.content };
}

function normalizeRetrievalScope(
  retrievalScope: ChatRetrievalScope | null | undefined,
): ChatRetrievalScope | null {
  if (!retrievalScope) {
    return null;
  }
  const direct: ChatRetrievalScope = {
    spaceId: normalizeScopeId(retrievalScope.spaceId),
    classificationDepartmentId: normalizeScopeId(retrievalScope.classificationDepartmentId),
    categoryId: normalizeScopeId(retrievalScope.categoryId),
  };
  if (direct.spaceId || direct.classificationDepartmentId || direct.categoryId) {
    return direct;
  }

  const nested = retrievalScope.classification
    ? {
        spaceId: normalizeScopeId(retrievalScope.classification.spaceId),
        classificationDepartmentId: normalizeScopeId(
          retrievalScope.classification.classificationDepartmentId,
        ),
        categoryId: normalizeScopeId(retrievalScope.classification.categoryId),
      }
    : null;
  return nested?.spaceId || nested?.classificationDepartmentId || nested?.categoryId
    ? { classification: nested }
    : null;
}

function normalizeScopeId(value: string | null | undefined) {
  const trimmed = value?.trim();
  return trimmed || null;
}

function dispatchBlock(
  block: string,
  handlers: {
    onEvent: (event: StreamEvent) => void;
    onCitation: (citation: ChatCitation) => void;
  },
) {
  const parsed = parseSseBlock(block);
  if (!parsed) {
    return;
  }
  handlers.onEvent(parsed);
  if (parsed.type === 'citation') {
    handlers.onCitation(parsed.data as ChatCitation);
  }
}

function parseSseBlock(block: string): StreamEvent | null {
  let eventName: string | null = null;
  const dataLines: string[] = [];

  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (line.startsWith(':')) {
      continue; // SSE comment (e.g. heartbeat)
    }
    if (line.startsWith('event:')) {
      eventName = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      // SSE allows multiple data: lines; they are joined with newlines.
      dataLines.push(line.slice('data:'.length).replace(/^ /, ''));
    }
  }

  if (!eventName || dataLines.length === 0) {
    return null;
  }

  const raw = dataLines.join('\n');
  try {
    return { type: eventName, data: JSON.parse(raw) };
  } catch {
    // A malformed/partial frame must not crash the whole stream.
    return null;
  }
}
