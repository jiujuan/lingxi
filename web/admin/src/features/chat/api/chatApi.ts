import { apiRequest } from '../../../api/client';
import type { ChatCitation, ChatMessage, ChatSession, StreamEvent } from '../types';

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
  content: string,
  handlers: {
    onEvent: (event: StreamEvent) => void;
    onCitation: (citation: ChatCitation) => void;
  },
) {
  const token = localStorage.getItem('lingxi_access_token');
  const response = await fetch(`${API_BASE_URL}/api/v1/chat/sessions/${sessionId}/message-runs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content }),
  });

  if (!response.ok || !response.body) {
    throw await response.json();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';
    blocks.forEach((block) => {
      const parsed = parseSseBlock(block);
      if (!parsed) {
        return;
      }
      handlers.onEvent(parsed);
      if (parsed.type === 'citation') {
        handlers.onCitation(parsed.data as ChatCitation);
      }
    });
  }
}

function parseSseBlock(block: string): StreamEvent | null {
  const eventLine = block.split('\n').find((line) => line.startsWith('event: '));
  const dataLine = block.split('\n').find((line) => line.startsWith('data: '));
  if (!eventLine || !dataLine) {
    return null;
  }
  return {
    type: eventLine.replace('event: ', '').trim(),
    data: JSON.parse(dataLine.replace('data: ', '')),
  };
}
