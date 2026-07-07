import { useEffect, useState } from 'react';

import { getImportJob, type ImportJob } from '../api/importJobApi';
import { DocumentUploadPanel } from '../components/DocumentUploadPanel';
import { ImportJobTimeline } from '../components/ImportJobTimeline';

export function KnowledgePage() {
  const [activeJob, setActiveJob] = useState<ImportJob | null>(null);

  useEffect(() => {
    if (!activeJob || !['PENDING', 'RUNNING'].includes(activeJob.status)) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      getImportJob(activeJob.id)
        .then(setActiveJob)
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeJob]);

  return (
    <div className="page-stack">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">知识库中心</p>
          <h2>文档入库、权限和 QA 结果</h2>
        </div>
        <div className="toolbar-actions">
          <button onClick={() => (window.location.hash = '#documents')} type="button">
            文档列表
          </button>
          <span className="status-pill">V1.1 入库闭环</span>
        </div>
      </section>

      <section className="knowledge-grid">
        <DocumentUploadPanel onUploaded={setActiveJob} />
        <section className="panel">
          <h3>最近任务</h3>
          <ImportJobTimeline job={activeJob} />
        </section>
      </section>
    </div>
  );
}
