export const modelTypeOptions = [
  ['CHAT', '对话模型'],
  ['EMBEDDING', 'Embedding 向量模型'],
  ['RERANK', 'Rerank 重排模型'],
  ['IMAGE', '图片模型'],
  ['MULTIMODAL', '多模态模型'],
  ['VIDEO', '视频模型'],
] as const;

export const modelCapabilityOptions = [
  ['CHAT', '对话模型'],
  ['EMBEDDING', 'Embedding 向量模型'],
  ['RERANK', 'Rerank 重排模型'],
  ['QA_SPLIT', '问答拆分模型'],
  ['IMAGE', '图片模型'],
  ['MULTIMODAL', '多模态模型'],
  ['VIDEO', '视频模型'],
] as const;
