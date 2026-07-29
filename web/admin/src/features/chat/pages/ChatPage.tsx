import { useEffect, useState } from 'react';

import {
  createChatSession,
  listChatMessages,
  listChatSessions,
  sendFeedback,
} from '../api/chatApi';
import { getCitationSource, getRetrievalExplanation } from '../api/citationApi';
import { ChatComposer } from '../components/ChatComposer';
import { ChatMessageList } from '../components/ChatMessageList';
import { ChatSessionList } from '../components/ChatSessionList';
import { CitationPanel } from '../components/CitationPanel';
import { CitationSourceDrawer } from '../components/CitationSourceDrawer';
import { RetrievalExplanationPanel } from '../components/RetrievalExplanationPanel';
import { useChatStream } from '../hooks/useChatStream';
import type {
  ChatMessage,
  ChatRetrievalScope,
  ChatSession,
  CitationSource,
  RetrievalExplanation,
} from '../types';

export function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [source, setSource] = useState<CitationSource | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<RetrievalExplanation | null>(null);
  const [isExplanationLoading, setIsExplanationLoading] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { streamingText, isStreaming, currentRunId, citations, setCitations, start, stop, reset } =
    useChatStream();

  useEffect(() => {
    void refreshSessions();
  }, []);

  useEffect(() => {
    // Switching sessions cancels a stream still running for the previous one.
    reset();
    if (activeSessionId) {
      void refreshMessages(activeSessionId);
    }
  }, [activeSessionId]);

  async function refreshSessions() {
    setIsLoading(true);
    try {
      const result = await listChatSessions();
      setSessions(result.data);
      setActiveSessionId((current) => current || result.data[0]?.id || null);
    } catch {
      setError('会话加载失败');
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshMessages(sessionId: string, preserveCitations = false) {
    try {
      const result = await listChatMessages(sessionId);
      setMessages(result.data);
      if (!preserveCitations) {
        setCitations([]);
        setExplanation(null);
      }
      setError(null);
    } catch {
      setError('消息加载失败');
    }
  }

  async function createSession() {
    const session = await createChatSession('新会话');
    setSessions((current) => [session, ...current]);
    setActiveSessionId(session.id);
    setMessages([]);
    reset();
  }

  async function submitMessage(content: string, retrievalScope: ChatRetrievalScope | null) {
    let sessionId = activeSessionId;
    if (!sessionId) {
      const session = await createChatSession(content.slice(0, 24));
      setSessions((current) => [session, ...current]);
      setActiveSessionId(session.id);
      sessionId = session.id;
    }
    const targetSessionId = sessionId;

    const localUserMessage: ChatMessage = {
      id: `local-${Date.now()}`,
      sessionId: targetSessionId,
      role: 'USER',
      content,
      status: 'CREATED',
      requestId: null,
      createdAt: new Date().toISOString(),
    };
    setMessages((current) => [...current, localUserMessage]);
    setError(null);

    await start(targetSessionId, content, retrievalScope, {
      onCompleted: async () => {
        await refreshMessages(targetSessionId, true);
        await refreshSessions();
      },
      onAborted: async () => {
        // User stopped generation — sync whatever the server persisted.
        await refreshMessages(targetSessionId, true);
      },
      onError: setError,
    });
  }

  async function copyMessage(content: string) {
    await navigator.clipboard.writeText(content);
  }

  async function feedback(messageId: string, value: 'up' | 'down') {
    await sendFeedback(messageId, value);
    if (activeSessionId) {
      await refreshMessages(activeSessionId, true);
    }
  }

  async function openSource(citationId: string) {
    try {
      setSourceError(null);
      setSource(await getCitationSource(citationId));
    } catch {
      setSource(null);
      setSourceError('当前无权查看原文详情或引用不存在');
    }
  }

  async function loadExplanation() {
    if (!currentRunId) {
      setError('暂无可查看的 run_id');
      return;
    }
    setIsExplanationLoading(true);
    try {
      setExplanation(await getRetrievalExplanation(currentRunId));
    } catch {
      setError('检索解释加载失败');
    } finally {
      setIsExplanationLoading(false);
    }
  }

  return (
    <div className="page-stack chat-page">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">Web Chat</p>
          <h2>知识库问答</h2>
        </div>
        {error ? <span className="error">{error}</span> : null}
      </section>
      <section className="chat-layout">
        <ChatSessionList
          activeSessionId={activeSessionId}
          isLoading={isLoading}
          onCreate={() => void createSession()}
          onSelect={setActiveSessionId}
          sessions={sessions}
        />
        <div className="chat-main">
          <ChatMessageList
            isStreaming={isStreaming}
            messages={messages}
            onCopy={(content) => void copyMessage(content)}
            onFeedback={(messageId, value) => void feedback(messageId, value)}
            streamingText={streamingText}
          />
          <ChatComposer
            disabled={isStreaming}
            isStreaming={isStreaming}
            onStop={stop}
            onSubmit={submitMessage}
          />
        </div>
        <div className="chat-side-stack">
          <CitationPanel
            citations={citations}
            onOpenSource={(citationId) => void openSource(citationId)}
          />
          <RetrievalExplanationPanel
            explanation={explanation}
            isLoading={isExplanationLoading}
            onLoad={() => void loadExplanation()}
          />
        </div>
      </section>
      <CitationSourceDrawer
        error={sourceError}
        onClose={() => {
          setSource(null);
          setSourceError(null);
        }}
        source={source}
      />
    </div>
  );
}
