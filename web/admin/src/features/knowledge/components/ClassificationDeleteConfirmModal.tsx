type Props = {
  itemName: string;
  description: string;
  pending: boolean;
  onClose: () => void;
  onConfirm: () => void;
};

export function ClassificationDeleteConfirmModal({
  itemName,
  description,
  pending,
  onClose,
  onConfirm,
}: Props) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section
        aria-label="删除确认"
        aria-modal="true"
        className="modal-panel classification-delete-modal"
        role="dialog"
      >
        <header className="classification-modal-header">
          <h3>删除确认</h3>
          <button
            aria-label="关闭"
            className="icon-button"
            disabled={pending}
            onClick={onClose}
            type="button"
          >
            <CloseIcon />
          </button>
        </header>
        <div aria-hidden="true" className="delete-warning-icon">
          <WarningIcon />
        </div>
        <p className="delete-question">确定删除「{itemName}」吗？</p>
        <p className="delete-description">{description}</p>
        <footer className="classification-modal-actions delete-modal-actions">
          <button className="secondary-button" disabled={pending} onClick={onClose} type="button">
            取消
          </button>
          <button className="danger-button" disabled={pending} onClick={onConfirm} type="button">
            <TrashIcon />
            {pending ? '删除中…' : '确认删除'}
          </button>
        </footer>
      </section>
    </div>
  );
}

function CloseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="m7 7 10 10M17 7 7 17" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 8v5m0 3h.01M10.3 3.9 2.5 17.4A2 2 0 0 0 4.2 20h15.6a2 2 0 0 0 1.7-2.6L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M4 7h16M10 11v5m4-5v5M9 7l1-3h4l1 3m-9 0 1 13h10l1-13" />
    </svg>
  );
}
