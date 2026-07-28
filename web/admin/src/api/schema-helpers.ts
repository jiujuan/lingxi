/**
 * Typed access to the backend API contract.
 *
 * `schema.d.ts` is auto-generated from the backend OpenAPI schema — do not edit
 * it by hand. Regenerate after backend schema changes:
 *
 *   1. python -m server.scripts.export_openapi   # writes web/admin/openapi.json
 *   2. npm run gen:api                            # regenerates src/api/schema.d.ts
 *
 * Prefer these generated types over hand-written interfaces so the frontend
 * cannot silently drift from the API. Add aliases here as features adopt them.
 */
import type { components, paths } from './schema';

export type Schemas = components['schemas'];
export type ApiPaths = paths;

export type TokenResponse = Schemas['TokenResponse'];
export type UserResponse = Schemas['UserResponse'];
export type ChatSessionResponse = Schemas['ChatSessionResponse'];
export type ChatMessageResponse = Schemas['ChatMessageResponse'];
export type DashboardSummaryResponse = Schemas['DashboardSummaryResponse'];
export type ApiKeyResponse = Schemas['ApiKeyResponse'];
export type ModelProviderResponse = Schemas['ModelProviderResponse'];
export type ModelConfigResponse = Schemas['ModelConfigResponse'];
export type SystemSettingsResponse = Schemas['SystemSettingsResponse'];
export type DocumentClassificationResponse = Schemas['DocumentClassificationResponse'];
export type DocumentClassificationUpdateRequest = Schemas['DocumentClassificationUpdateRequest'];
export type ImportClassificationRequest = Schemas['ImportClassificationRequest'];
export type ImportJobCreateRequest = Schemas['ImportJobCreateRequest'];
export type KnowledgeSpaceResponse = Schemas['KnowledgeSpaceResponse'];
export type KnowledgeSpaceCreateRequest = Schemas['KnowledgeSpaceCreateRequest'];
export type KnowledgeSpaceUpdateRequest = Schemas['KnowledgeSpaceUpdateRequest'];
export type KnowledgeCategoryResponse = Schemas['KnowledgeCategoryResponse'];
export type KnowledgeCategoryCreateRequest = Schemas['KnowledgeCategoryCreateRequest'];
export type KnowledgeCategoryUpdateRequest = Schemas['KnowledgeCategoryUpdateRequest'];
