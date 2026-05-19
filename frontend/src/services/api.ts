export type ProjectItem = {
  id: number;
  name: string;
  description: string;
  created_at: string;
};

export type DocumentItem = {
  id: number;
  project_id: number;
  filename: string;
  file_type: string;
  summary: string;
  created_at: string;
  tags?: string[];
  ocr_meta?: string;
};

export type UploadDedupMode = 'ignore' | 'overwrite' | 'keep';

export type UploadResult = {
  document: DocumentItem;
  section_count: number;
  paragraph_count: number;
  chunk_count: number;
  dedup_action?: 'imported' | 'skipped_duplicate' | 'replaced';
};

export type EmbeddingHealth = {
  provider: string;
  model: string;
  dimension: number;
  semantic_enabled: boolean;
  ok: boolean;
  message: string;
};

export type OcrHealth = {
  enabled: boolean;
  ok: boolean;
  engine: string;
  message: string;
};

export type ReindexResult = {
  project_id: number;
  section_count: number;
  paragraph_count: number;
  chunk_count: number;
  embedding_count: number;
};

export type ProjectIndexStats = {
  project_id: number;
  document_count: number;
  section_count: number;
  paragraph_count: number;
  chunk_count: number;
  embedding_count: number;
  embedding_count_total: number;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimension: number;
  embedding_version: string;
  dominant_embedding_version: string;
  matches_current_config: boolean;
  indexed: boolean;
};

export type SearchHit = {
  project_id: number;
  project_name: string;
  document_id: number;
  document_name: string;
  section_title: string | null;
  text: string;
  score: number;
  rank_score: number;
  vector_score: number;
  keyword_score: number;
  bm25_score: number;
  match_type: string;
  source_id: number;
  location_label?: string | null;
};

export type SourceSummary = {
  project_id: number;
  project_name: string;
  document_id: number;
  document_name: string;
  section_title: string | null;
  match_type: string;
  score: number;
};

export type SearchResponse = {
  query: string;
  mode: 'search' | 'rag';
  hits: SearchHit[];
  sources: SourceSummary[];
  answer: string | null;
  rag_skipped_reason?: string | null;
};

export type ProviderHealth = {
  configured: boolean;
  ok: boolean;
  message: string;
};

export type CreateJobResponse = {
  job_id: number;
};

export type JobItem = {
  id: number;
  project_id: number;
  type: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  progress_current: number | null;
  progress_total: number | null;
  message: string;
  target_name?: string | null;
  result_json: string;
  error: string;
  retry_count: number;
  cancel_requested: number;
  created_at: string;
  updated_at: string;
};

export type JobListResponse = {
  items: JobItem[];
  total: number;
  limit: number;
  offset: number;
};

export type TagItem = {
  id: number;
  project_id: number;
  name: string;
  created_at: string;
};

export type ChatMessageItem = {
  id: number;
  project_id: number;
  role: string;
  content: string;
  created_at: string;
};

export type ParagraphDetail = {
  id: number;
  order_index: number;
  text: string;
  summary: string;
  chunk_count: number;
};

export type SectionDetail = {
  id: number;
  order_index: number;
  title: string;
  level: number;
  summary: string;
  paragraphs: ParagraphDetail[];
};

export type DocumentDetailResponse = {
  document: DocumentItem;
  sections: SectionDetail[];
  section_count: number;
  paragraph_count: number;
  chunk_count: number;
};

export type SearchKnowledgeOptions = {
  top_k?: number;
  tagIds?: number[];
  fileTypes?: string[];
  createdAfter?: string;
  createdBefore?: string;
  ragUseChatHistory?: boolean;
};

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function listProjects(): Promise<ProjectItem[]> {
  return request<ProjectItem[]>('/api/projects');
}

export function createProject(name: string, description = ''): Promise<ProjectItem> {
  return request<ProjectItem>('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
}

export function updateProject(
  projectId: number,
  name: string,
  description = '',
): Promise<ProjectItem> {
  return request<ProjectItem>(`/api/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
}

export function deleteProject(projectId: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/projects/${projectId}`, {
    method: 'DELETE',
  });
}

export function listDocuments(projectId: number): Promise<DocumentItem[]> {
  return request<DocumentItem[]>(`/api/documents?project_id=${projectId}`);
}

export function uploadDocument(
  file: File,
  projectId: number,
  importDedupMode?: UploadDedupMode,
): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('project_id', String(projectId));
  if (importDedupMode) {
    form.append('import_dedup_mode', importDedupMode);
  }
  return request<UploadResult>('/api/documents', {
    method: 'POST',
    body: form,
  });
}

export function createImportJob(
  file: File,
  projectId: number,
  importDedupMode?: UploadDedupMode,
): Promise<CreateJobResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('project_id', String(projectId));
  if (importDedupMode) {
    form.append('import_dedup_mode', importDedupMode);
  }
  return request<CreateJobResponse>('/api/jobs/import', {
    method: 'POST',
    body: form,
  });
}

export function createImportUrlJob(
  url: string,
  projectId: number,
  importDedupMode?: UploadDedupMode,
): Promise<CreateJobResponse> {
  const form = new FormData();
  form.append('url', url);
  form.append('project_id', String(projectId));
  if (importDedupMode) {
    form.append('import_dedup_mode', importDedupMode);
  }
  return request<CreateJobResponse>('/api/jobs/import-url', {
    method: 'POST',
    body: form,
  });
}

export function createReindexJob(projectId: number): Promise<CreateJobResponse> {
  return request<CreateJobResponse>('/api/jobs/reindex', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId }),
  });
}

export function listJobs(projectId: number, limit = 10, offset = 0): Promise<JobListResponse> {
  return request<JobListResponse>(`/api/jobs?project_id=${projectId}&limit=${limit}&offset=${offset}`);
}

export function getJob(jobId: number): Promise<JobItem> {
  return request<JobItem>(`/api/jobs/${jobId}`);
}

export function cancelJob(jobId: number): Promise<{ cancelled: boolean }> {
  return request<{ cancelled: boolean }>(`/api/jobs/${jobId}/cancel`, {
    method: 'POST',
  });
}

export function retryJob(jobId: number): Promise<CreateJobResponse> {
  return request<CreateJobResponse>(`/api/jobs/${jobId}/retry`, {
    method: 'POST',
  });
}

export function deleteDocument(
  documentId: number,
  projectId: number,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/documents/${documentId}?project_id=${projectId}`, {
    method: 'DELETE',
  });
}

export function searchKnowledge(
  query: string,
  mode: 'search' | 'rag',
  projectId: number,
  opts?: SearchKnowledgeOptions,
): Promise<SearchResponse> {
  return request<SearchResponse>('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: projectId,
      query,
      mode,
      top_k: opts?.top_k ?? 8,
      tag_ids: opts?.tagIds ?? [],
      file_types: opts?.fileTypes ?? [],
      created_after: opts?.createdAfter ?? null,
      created_before: opts?.createdBefore ?? null,
      rag_use_chat_history: opts?.ragUseChatHistory ?? true,
    }),
  });
}

export function getProviderHealth(): Promise<ProviderHealth> {
  return request<ProviderHealth>('/api/provider/health');
}

export function getEmbeddingHealth(): Promise<EmbeddingHealth> {
  return request<EmbeddingHealth>('/api/embedding/health');
}

export function getOcrHealth(): Promise<OcrHealth> {
  return request<OcrHealth>('/api/ocr/health');
}

export function reindexProject(projectId: number): Promise<ReindexResult> {
  return request<ReindexResult>(`/api/projects/${projectId}/reindex`, {
    method: 'POST',
  });
}

export function getProjectIndexStats(projectId: number): Promise<ProjectIndexStats> {
  return request<ProjectIndexStats>(`/api/projects/${projectId}/index-stats`);
}

export function listTags(projectId: number): Promise<TagItem[]> {
  return request<TagItem[]>(`/api/projects/${projectId}/tags`);
}

export function createTag(projectId: number, name: string): Promise<TagItem> {
  return request<TagItem>(`/api/projects/${projectId}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export function deleteTag(projectId: number, tagId: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/projects/${projectId}/tags/${tagId}`, {
    method: 'DELETE',
  });
}

export function patchDocumentTags(
  documentId: number,
  projectId: number,
  tagIds: number[],
): Promise<DocumentItem> {
  return request<DocumentItem>(`/api/documents/${documentId}/tags?project_id=${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag_ids: tagIds }),
  });
}

export function getDocumentDetail(
  documentId: number,
  projectId: number,
): Promise<DocumentDetailResponse> {
  return request<DocumentDetailResponse>(
    `/api/documents/${documentId}/detail?project_id=${projectId}`,
  );
}

export function listChatMessages(projectId: number, limit = 40): Promise<ChatMessageItem[]> {
  return request<ChatMessageItem[]>(`/api/projects/${projectId}/chat?limit=${limit}`);
}

export function clearChatMessages(projectId: number): Promise<{ cleared: boolean }> {
  return request<{ cleared: boolean }>(`/api/projects/${projectId}/chat`, {
    method: 'DELETE',
  });
}
