import type { ChatSession } from '../types';

type Props = {
  sessions: ChatSession[];
  activeSessionId: string | null;
  isLoading: boolean;
  onCreate: () => void;
  onSelect: (sessionId: string) => void;
};

export function ChatSessionList({ sessions, activeSessionId, isLoading, onCreate, onSelect }: Props) {
  return (
    <aside className="chat-sessions panel">
      <div className="toolbar-row compact">
        <h3>会话</h3>
        <button type="button" onClick={onCreate}>
          新建
        </button>
      </div>
      <div className="chat-session-list">
        {isLoading ? <p className="muted">加载会话中...</p> : null}
        {!isLoading && sessions.length === 0 ? (
          <div className="empty-state">
            <strong>暂无会话</strong>
            <p>新建会话后即可开始提问。</p>
          </div>
        ) : null}
        {sessions.map((session) => (
          <button
            className={`chat-session-item ${activeSessionId === session.id ? 'active' : ''}`}
            key={session.id}
            onClick={() => onSelect(session.id)}
            type="button"
          >
            <strong>{session.title || '新会话'}</strong>
            <span>{new Date(session.updatedAt || session.createdAt).toLocaleString()}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
