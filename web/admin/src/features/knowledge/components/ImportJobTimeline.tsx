const PIPELINE_STEPS = [
  { stage: 'PARSING', title: '文档解析', description: '提取原始文档的结构化内容。' },
  { stage: 'QA_SPLITTING', title: '知识切分与 QA 问答生成', description: '切分知识片段并生成可追溯问答。' },
  { stage: 'EMBEDDING', title: '向量化与知识入库', description: '生成向量并写入可检索知识库。' },
  { stage: 'COMPLETED', title: '完成上架，可检索使用', description: '文档已完成处理并可用于问答检索。' },
] as const;

type TaskProgress = {
  id: string;
  status: string;
  stage: string;
  progress: number;
  errorCode: string | null;
  errorMessage: string | null;
  failedStage: string | null;
  retryable: boolean;
};

type Props = {
  job: TaskProgress | null;
  onRetry?: () => void;
};

export function ImportJobTimeline({ job, onRetry }: Props) {
  const isCompleted = job?.status === 'COMPLETED' || job?.stage === 'COMPLETED';
  const isQueued = Boolean(job && ['PENDING', 'CREATED'].includes(job.status));
  const activeIndex = job ? PIPELINE_STEPS.findIndex((step) => step.stage === job.stage) : -1;
  const failedIndex = job
    ? PIPELINE_STEPS.findIndex((step) => step.stage === (job.failedStage || job.stage))
    : -1;

  return (
    <div className="task-pipeline" aria-live="polite">
      {!job ? (
        <p className="task-pipeline-summary">空闲：上传文档并点击一键构建解析任务后开始处理。</p>
      ) : isQueued ? (
        <p className="task-pipeline-summary">任务已创建，正在等待处理资源。</p>
      ) : (
        <p className="task-pipeline-summary">
          当前状态：{job.status} · {job.progress}%
        </p>
      )}

      <ol>
        {PIPELINE_STEPS.map((step, index) => {
          const failed = job?.status === 'FAILED' && index === failedIndex;
          const active = !failed && !isCompleted && !isQueued && index === activeIndex;
          const completed = Boolean(job && (isCompleted || (!failed && activeIndex > index)));
          const state = failed ? 'failed' : active ? 'active' : completed ? 'completed' : 'idle';
          return (
            <li className={`task-pipeline-step ${state}`} key={step.stage}>
              <span aria-hidden="true" className="task-pipeline-marker">
                {completed ? '✓' : failed ? '!' : index + 1}
              </span>
              <div>
                <strong>{step.title}</strong>
                <span>{step.description}</span>
                {active ? <small>正在处理</small> : null}
                {failed ? <small>处理失败</small> : null}
              </div>
            </li>
          );
        })}
      </ol>

      {job ? (
        <div className="task-pipeline-progress">
          <div aria-label={`当前处理进度 ${job.progress}%`} className="progress-bar">
            <i style={{ width: `${job.progress}%` }} />
          </div>
          <span>{job.progress}%</span>
        </div>
      ) : null}
      {job?.errorMessage ? (
        <div className="error-box" role="alert">
          <strong>{job.errorCode || 'PROCESSING_ERROR'}</strong>
          <p>{job.errorMessage}</p>
          {job.retryable && onRetry ? (
            <button onClick={onRetry} type="button">重试当前任务</button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
