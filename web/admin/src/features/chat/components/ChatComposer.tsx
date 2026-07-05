import { useState } from 'react';

type Props = {
  disabled: boolean;
  isStreaming?: boolean;
  onStop?: () => void;
  onSubmit: (content: string) => Promise<void>;
};

export function ChatComposer({ disabled, isStreaming = false, onStop, onSubmit }: Props) {
  const [content, setContent] = useState('');

  async function submit() {
    const trimmed = content.trim();
    if (!trimmed || disabled) {
      return;
    }
    setContent('');
    await onSubmit(trimmed);
  }

  return (
    <form
      className="chat-composer"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
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
