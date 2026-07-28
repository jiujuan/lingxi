import type { Schemas } from '../../../api/schema-helpers';

export type KnowledgeSpace = Schemas['KnowledgeSpaceResponse'];
export type KnowledgeCategory = Schemas['KnowledgeCategoryResponse'];
export type KnowledgeCategoryType = Schemas['KnowledgeCategoryType'];

export type KnowledgeClassificationPath = {
  spaceId: string | null;
  spaceName: string | null;
  /** Department selected for classification; kept distinct from document permission departments. */
  departmentId: string | null;
  departmentName: string | null;
  /** Alias used by document list filters and table fields. */
  classificationDepartmentId: string | null;
  classificationDepartmentName: string | null;
  categoryId: string | null;
  categoryName: string | null;
};

export type KnowledgeCategoryFilters = {
  spaceId?: string | null;
  departmentId?: string | null;
};

export type CreateKnowledgeSpacePayload = Schemas['KnowledgeSpaceCreateRequest'];
export type UpdateKnowledgeSpacePayload = Schemas['KnowledgeSpaceUpdateRequest'];
export type CreateKnowledgeCategoryPayload = Schemas['KnowledgeCategoryCreateRequest'];
export type UpdateKnowledgeCategoryPayload = Schemas['KnowledgeCategoryUpdateRequest'];
export type UpdateDocumentClassificationPayload = Schemas['DocumentClassificationUpdateRequest'];
export type ImportClassificationPayload = Schemas['ImportClassificationRequest'];
