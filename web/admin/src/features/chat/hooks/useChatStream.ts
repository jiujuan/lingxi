import { useCallback, useEffect, useRef, useState } from 'react';

import { errorMessage } from '../../../api/client';
import { streamChatMessage } from '../api/chatApi';
import type { ChatCitation } from '../types';

type StartHandlers = {
  onCompleted: () => Promise<void> | void;
  onAborted: () => Promise<void> | void;
  onError: (message: string) => void;
};

/**
 * Owns the chat streaming concern: the in-flight AbortController, the streaming
 * text buffer, citations and current run id. Extracted from ChatPage so the page
 * container is not responsible for the SSE plumbing.
 */
export function useChatStream() {
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [citations, setCitations] = useState<ChatCitation[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  // Cancel any in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setCitations([]);
    setCurrentRunId(null);
    setStreamingText('');
  }, []);

  const start = useCallback(async (sessionId: string, content: string, handlers: StartHandlers) => {
    setStreamingText('');
    setCitations([]);
    setIsStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamChatMessage(
        sessionId,
        content,
        {
          onEvent: (event) => {
            if (event.type === 'run_started') {
              setCurrentRunId(String(event.data.runId || ''));
            }
            if (event.type === 'delta') {
              setStreamingText((current) => current + String(event.data.content ?? ''));
            }
            if (event.type === 'error') {
              handlers.onError(
                `${String(event.data.message ?? '模型调用失败')} (${String(event.data.requestId ?? '')})`,
              );
            }
          },
          onCitation: (citation) => setCitations((current) => [...current, citation]),
        },
        { signal: controller.signal },
      );
      await handlers.onCompleted();
    } catch (err) {
      if ((err as Error)?.name === 'AbortError') {
        await handlers.onAborted();
      } else {
        handlers.onError(errorMessage(err, '发送失败，请稍后重试'));
      }
    } finally {
      abortRef.current = null;
      setIsStreaming(false);
      setStreamingText('');
    }
  }, []);

  return {
    streamingText,
    isStreaming,
    currentRunId,
    citations,
    setCitations,
    start,
    stop,
    reset,
  };
}
