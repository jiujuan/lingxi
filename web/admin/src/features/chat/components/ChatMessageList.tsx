import type { ChatMessage } from '../types';

type Props = {
  messages: ChatMessage[];
  streamingText: string;
  isStreaming: boolean;
  onCopy: (content: string) => void;
  onFeedback: (messageId: string, feedback: 'up' | 'down') => void;
};

export function ChatMessageList({
  messages,
  streamingText,
  isStreaming,
  onCopy,
  onFeedback,
}: Props) {
  return (
    <section className="chat-messages panel" aria-live="polite">
      {messages.length === 0 && !isStreaming ? (
        <div className="chat-empty">
          <h2>Chat</h2>
          <p>围绕已入库并授权的知识提问，回答会优先给出可追溯引用。</p>
        </div>
      ) : null}
      {messages.map((message) => (
        <article className={`chat-message ${message.role.toLowerCase()}`} key={message.id}>
          <div className="chat-message-meta">
            <span>{message.role === 'USER' ? '我' : 'Lingxi'}</span>
            {message.requestId ? (
              <a href={`#logs?requestId=${message.requestId}`}>
                <code>{message.requestId}</code>
              </a>
            ) : null}
          </div>
          <p>{message.content}</p>
          {message.role === 'ASSISTANT' ? (
            <div className="button-row chat-message-actions">
              <button
                className="secondary-button"
                onClick={() => onCopy(message.content)}
                type="button"
              >
                复制
              </button>
              <button
                className="secondary-button"
                onClick={() => onFeedback(message.id, 'up')}
                type="button"
              >
                赞
              </button>
              <button
                className="secondary-button"
                onClick={() => onFeedback(message.id, 'down')}
                type="button"
              >
                踩
              </button>
            </div>
          ) : null}
        </article>
      ))}
      {isStreaming ? (
        <article className="chat-message assistant streaming">
          <div className="chat-message-meta">
            <span>Lingxi</span>
            <span>生成中</span>
          </div>
          <p>{streamingText || '正在检索知识库...'}</p>
        </article>
      ) : null}
    </section>
  );
}
