type Props = {
  title: string;
  payload: unknown;
  onClose: () => void;
};

export function LogDetailDrawer({ title, payload, onClose }: Props) {
  if (!payload) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-modal="true" className="modal-panel log-detail-drawer" role="dialog">
        <div className="toolbar-row compact">
          <h3>{title}</h3>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        <pre>{JSON.stringify(payload, null, 2)}</pre>
      </section>
    </div>
  );
}
