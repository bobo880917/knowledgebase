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
};

export type UploadResult = {
  document: DocumentItem;
  section_count: number;
  paragraph_count: number;
  chunk_count: number;
};

export type EmbeddingHealth = {
  provider: string;
  model: string;
  dimension: number;
  semantic_enabled: boolean;
  ok: boolean;
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
  match_type: string;
  source_id: number;
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
};

export type ProviderHealth = {
  configured: boolean;
  ok: boolean;
  message: string;
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

export function uploadDocument(file: File, projectId: number): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('project_id', String(projectId));
  return request<UploadResult>('/api/documents', {
    method: 'POST',
    body: form,
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
): Promise<SearchResponse> {
  return request<SearchResponse>('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, query, mode, top_k: 8 }),
  });
}

export function getProviderHealth(): Promise<ProviderHealth> {
  return request<ProviderHealth>('/api/provider/health');
}

export function getEmbeddingHealth(): Promise<EmbeddingHealth> {
  return request<EmbeddingHealth>('/api/embedding/health');
}

export function reindexProject(projectId: number): Promise<ReindexResult> {
  return request<ReindexResult>(`/api/projects/${projectId}/reindex`, {
    method: 'POST',
  });
}

export function getProjectIndexStats(projectId: number): Promise<ProjectIndexStats> {
  return request<ProjectIndexStats>(`/api/projects/${projectId}/index-stats`);
}
