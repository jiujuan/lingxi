import { useState } from 'react';

import { KnowledgeClassificationSelect } from '../../knowledge/components/KnowledgeClassificationSelect';
import type { KnowledgeClassificationValue } from '../../knowledge/types/classification';
import type { ChatRetrievalScope } from '../types';

type Props = {
  disabled: boolean;
  isStreaming?: boolean;
  onStop?: () => void;
  onSubmit: (content: string, retrievalScope: ChatRetrievalScope | null) => Promise<void>;
};

export function ChatComposer({ disabled, isStreaming = false, onStop, onSubmit }: Props) {
  const [content, setContent] = useState('');
  const [retrievalScope, setRetrievalScope] = useState<ChatRetrievalScope | null>(null);

  async function submit() {
    const trimmed = content.trim();
    if (!trimmed || disabled) {
      return;
    }
    setContent('');
    await onSubmit(trimmed, retrievalScope);
  }

  return (
    <form
      className="chat-composer"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <KnowledgeClassificationSelect
        allowUnclassified
        disabled={disabled}
        idPrefix="chat-retrieval-scope"
        legend="检索范围"
        onChange={(value) => setRetrievalScope(toChatRetrievalScope(value))}
        required={false}
        showValidation={false}
      />
      <textarea
        aria-label="输入问题"
        disabled={disabled}
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            void submit();
          }
        }}
        placeholder={disabled ? '正在生成回答...' : '输入问题，Enter 发送，Shift+Enter 换行'}
        value={content}
      />
      {isStreaming && onStop ? (
        <button className="secondary-button" onClick={onStop} type="button">
          停止生成
        </button>
      ) : (
        <button disabled={disabled || !content.trim()} type="submit">
          发送
        </button>
      )}
    </form>
  );
}

function toChatRetrievalScope(value: KnowledgeClassificationValue): ChatRetrievalScope | null {
  const scope = {
    spaceId: normalizeScopeId(value.spaceId),
    classificationDepartmentId: normalizeScopeId(value.departmentId),
    categoryId: normalizeScopeId(value.categoryId),
  };
  return scope.spaceId || scope.classificationDepartmentId || scope.categoryId ? scope : null;
}

function normalizeScopeId(value: string | null | undefined) {
  const trimmed = value?.trim();
  return trimmed || null;
}
