const STAGES = ['CREATED', 'PARSING', 'QA_SPLITTING', 'EMBEDDING', 'INDEXING', 'COMPLETED'];

type TaskProgress = {
  id: string;
  status: string;
  stage: string;
  progress: number;
  errorCode: string | null;
  errorMessage: string | null;
};

type Props = {
  job: TaskProgress | null;
};

export function ImportJobTimeline({ job }: Props) {
  if (!job) {
    return <p className="muted">创建任务后会显示处理进度。</p>;
  }

  return (
    <div className="timeline">
      {STAGES.map((stage) => {
        const active = stage === job.stage;
        const done = STAGES.indexOf(stage) < STAGES.indexOf(job.stage);
        return (
          <div className={active || done ? 'timeline-step active' : 'timeline-step'} key={stage}>
            <span />
            <strong>{stage}</strong>
          </div>
        );
      })}
      <div className="progress-bar">
        <i style={{ width: `${job.progress}%` }} />
      </div>
      <p>
        当前状态：{job.status} · {job.stage} · {job.progress}%
      </p>
      {job.errorMessage ? <p className="error">{job.errorCode} · {job.errorMessage}</p> : null}
    </div>
  );
}
