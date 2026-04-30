<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import {
  createProject,
  deleteDocument,
  deleteProject,
  getEmbeddingHealth,
  getProjectIndexStats,
  getProviderHealth,
  listDocuments,
  listProjects,
  reindexProject,
  searchKnowledge,
  updateProject,
  uploadDocument,
  type DocumentItem,
  type EmbeddingHealth,
  type ProjectIndexStats,
  type ProjectItem,
  type ProviderHealth,
  type ReindexResult,
  type SearchResponse,
  type UploadResult,
} from './services/api';

type ViewKey = 'projects' | 'documents' | 'search';

const projects = ref<ProjectItem[]>([]);
const activeProjectId = ref(1);
const currentView = ref<ViewKey>('search');
const documents = ref<DocumentItem[]>([]);
const provider = ref<ProviderHealth | null>(null);
const embedding = ref<EmbeddingHealth | null>(null);
const indexStats = ref<ProjectIndexStats | null>(null);
const selectedFile = ref<File | null>(null);
const uploadResult = ref<UploadResult | null>(null);
const reindexResult = ref<ReindexResult | null>(null);
const newProjectName = ref('');
const newProjectDescription = ref('');
const editingProject = ref(false);
const editProjectName = ref('');
const editProjectDescription = ref('');
const query = ref('');
const mode = ref<'search' | 'rag'>('search');
const result = ref<SearchResponse | null>(null);
const loading = ref(false);
const uploading = ref(false);
const creatingProject = ref(false);
const savingProject = ref(false);
const deletingProject = ref(false);
const deletingDocumentId = ref<number | null>(null);
const reindexing = ref(false);
const error = ref('');

const menuItems: Array<{ key: ViewKey; label: string; description: string }> = [
  { key: 'search', label: '检索问答', description: '搜索、RAG 与来源调试' },
  { key: 'documents', label: '文档管理', description: '上传、查看和删除文档' },
  { key: 'projects', label: '项目空间', description: '创建、编辑和切换项目' },
];

const activeProject = computed(() =>
  projects.value.find((project) => project.id === activeProjectId.value) ?? null,
);

const activeViewTitle = computed(
  () => menuItems.find((item) => item.key === currentView.value)?.label ?? '知识库',
);

const stats = computed(() => ({
  project: activeProject.value?.name ?? '默认项目',
  documents: documents.value.length,
  provider: provider.value?.ok ? '已连接' : '未连接',
  embedding: embedding.value?.semantic_enabled ? '语义检索' : 'Hash 检索',
  mode: mode.value === 'rag' ? 'RAG 问答' : '纯检索',
}));

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
}

function goTo(view: ViewKey) {
  currentView.value = view;
}

async function refresh() {
  projects.value = await listProjects();
  if (!projects.value.some((project) => project.id === activeProjectId.value)) {
    activeProjectId.value = projects.value[0]?.id ?? 1;
  }
  documents.value = await listDocuments(activeProjectId.value);
  indexStats.value = await getProjectIndexStats(activeProjectId.value);
  provider.value = await getProviderHealth();
  embedding.value = await getEmbeddingHealth();
}

async function switchProject(projectId: number) {
  activeProjectId.value = projectId;
  uploadResult.value = null;
  result.value = null;
  editingProject.value = false;
  documents.value = await listDocuments(projectId);
  indexStats.value = await getProjectIndexStats(projectId);
}

async function submitProject() {
  if (!newProjectName.value.trim()) return;
  creatingProject.value = true;
  error.value = '';
  try {
    const project = await createProject(
      newProjectName.value.trim(),
      newProjectDescription.value.trim(),
    );
    newProjectName.value = '';
    newProjectDescription.value = '';
    await refresh();
    await switchProject(project.id);
    currentView.value = 'documents';
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建项目失败';
  } finally {
    creatingProject.value = false;
  }
}

function startEditProject() {
  if (!activeProject.value) return;
  editProjectName.value = activeProject.value.name;
  editProjectDescription.value = activeProject.value.description;
  editingProject.value = true;
}

async function submitProjectEdit() {
  if (!activeProject.value || !editProjectName.value.trim()) return;
  savingProject.value = true;
  error.value = '';
  try {
    const updated = await updateProject(
      activeProject.value.id,
      editProjectName.value.trim(),
      editProjectDescription.value.trim(),
    );
    await refresh();
    activeProjectId.value = updated.id;
    editingProject.value = false;
  } catch (err) {
    error.value = err instanceof Error ? err.message : '更新项目失败';
  } finally {
    savingProject.value = false;
  }
}

async function removeProject() {
  if (!activeProject.value || activeProject.value.id === 1) return;
  const confirmed = window.confirm(`确认删除项目“${activeProject.value.name}”及其全部文档和索引吗？`);
  if (!confirmed) return;

  deletingProject.value = true;
  error.value = '';
  try {
    await deleteProject(activeProject.value.id);
    activeProjectId.value = 1;
    uploadResult.value = null;
    result.value = null;
    await refresh();
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除项目失败';
  } finally {
    deletingProject.value = false;
  }
}

async function rebuildCurrentProjectIndex() {
  if (!activeProject.value) return;
  reindexing.value = true;
  error.value = '';
  try {
    reindexResult.value = await reindexProject(activeProject.value.id);
    result.value = null;
    indexStats.value = await getProjectIndexStats(activeProject.value.id);
    embedding.value = await getEmbeddingHealth();
  } catch (err) {
    error.value = err instanceof Error ? err.message : '重建索引失败';
  } finally {
    reindexing.value = false;
  }
}

async function submitUpload() {
  if (!selectedFile.value) return;
  uploading.value = true;
  error.value = '';
  try {
    uploadResult.value = await uploadDocument(selectedFile.value, activeProjectId.value);
    selectedFile.value = null;
    await refresh();
  } catch (err) {
    error.value = err instanceof Error ? err.message : '上传失败';
  } finally {
    uploading.value = false;
  }
}

async function removeDocument(document: DocumentItem) {
  const confirmed = window.confirm(`确认删除文档“${document.filename}”及其索引吗？`);
  if (!confirmed) return;

  deletingDocumentId.value = document.id;
  error.value = '';
  try {
    await deleteDocument(document.id, activeProjectId.value);
    result.value = null;
    uploadResult.value = null;
    documents.value = await listDocuments(activeProjectId.value);
    indexStats.value = await getProjectIndexStats(activeProjectId.value);
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除文档失败';
  } finally {
    deletingDocumentId.value = null;
  }
}

async function submitSearch() {
  if (!query.value.trim()) return;
  loading.value = true;
  error.value = '';
  try {
    result.value = await searchKnowledge(query.value.trim(), mode.value, activeProjectId.value);
  } catch (err) {
    error.value = err instanceof Error ? err.message : '检索失败';
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  refresh().catch((err) => {
    error.value = err instanceof Error ? err.message : '初始化失败';
  });
});
</script>

<template>
  <main class="app-shell">
    <aside class="app-sidebar panel">
      <div class="brand-block">
        <p class="eyebrow">Local Knowledge Base</p>
        <h1>本地知识库</h1>
        <p>按项目隔离文档，让检索和回答只发生在当前知识空间。</p>
      </div>

      <nav class="main-menu" aria-label="主菜单">
        <button
          v-for="item in menuItems"
          :key="item.key"
          :class="{ active: currentView === item.key }"
          @click="goTo(item.key)"
        >
          <strong>{{ item.label }}</strong>
          <span>{{ item.description }}</span>
        </button>
      </nav>

      <div class="sidebar-project">
        <span>当前项目</span>
        <strong>{{ stats.project }}</strong>
        <small>{{ stats.documents }} 个文档 · 模型{{ stats.provider }}</small>
        <small>检索：{{ stats.embedding }}</small>
      </div>
    </aside>

    <section class="app-main">
      <header class="topbar panel">
        <div>
          <p class="eyebrow">{{ activeViewTitle }}</p>
          <h2>{{ stats.project }}</h2>
        </div>
        <div class="stats-strip">
          <span>文档 {{ stats.documents }}</span>
          <span>模型 {{ stats.provider }}</span>
          <span>{{ stats.embedding }}</span>
          <span>{{ stats.mode }}</span>
        </div>
      </header>

      <p v-if="error" class="error">{{ error }}</p>

      <section v-if="currentView === 'projects'" class="page-grid projects-page">
        <article class="panel page-card">
          <div class="section-heading">
            <div>
              <h2>项目列表</h2>
              <p class="muted">切换项目后，文档列表、检索和 RAG 上下文都会同步切换。</p>
            </div>
          </div>

          <div class="project-list spacious">
            <button
              v-for="project in projects"
              :key="project.id"
              :class="{ active: project.id === activeProjectId }"
              @click="switchProject(project.id)"
            >
              {{ project.name }}
            </button>
          </div>
        </article>

        <article class="panel page-card">
          <div class="section-heading">
            <div>
              <h2>当前项目</h2>
              <p class="muted">默认项目不可删除，其他项目删除时会同步删除全部文档和索引。</p>
            </div>
          </div>

          <div v-if="activeProject" class="project-actions large-card">
            <div>
              <strong>{{ activeProject.name }}</strong>
              <p>{{ activeProject.description || '暂无简介' }}</p>
            </div>
            <div class="action-row">
              <button type="button" class="ghost-button" @click="startEditProject">编辑</button>
              <button
                type="button"
                class="danger-button"
                :disabled="activeProject.id === 1 || deletingProject"
                :title="activeProject.id === 1 ? '默认项目不可删除' : ''"
                @click="removeProject"
              >
                {{ deletingProject ? '删除中...' : '删除项目' }}
              </button>
            </div>
          </div>

          <form v-if="editingProject" class="project-form compact" @submit.prevent="submitProjectEdit">
            <input v-model="editProjectName" placeholder="项目名称" />
            <input v-model="editProjectDescription" placeholder="项目简介" />
            <div class="action-row">
              <button :disabled="savingProject || !editProjectName.trim()">
                {{ savingProject ? '保存中...' : '保存项目' }}
              </button>
              <button type="button" class="ghost-button" @click="editingProject = false">取消</button>
            </div>
          </form>
        </article>

        <article class="panel page-card">
          <div class="section-heading">
            <div>
              <h2>Embedding 索引</h2>
              <p class="muted">
                当前 provider：{{ embedding?.provider || '-' }}；
                模型：{{ embedding?.model || '-' }}；
                维度：{{ embedding?.dimension || '-' }}
              </p>
            </div>
          </div>

          <div class="embedding-status" :class="{ warning: !embedding?.semantic_enabled }">
            <strong>{{ embedding?.ok ? 'Embedding 服务可用' : 'Embedding 服务异常' }}</strong>
            <p>{{ embedding?.message || '正在读取 embedding 状态...' }}</p>
          </div>

          <div v-if="indexStats" class="index-stats-card" :class="{ warning: !indexStats.indexed }">
            <strong>{{ indexStats.indexed ? '当前项目索引完整' : '当前项目索引需要重建' }}</strong>
            <div class="index-stats-grid">
              <span>文档</span><b>{{ indexStats.document_count }}</b>
              <span>章节</span><b>{{ indexStats.section_count }}</b>
              <span>段落</span><b>{{ indexStats.paragraph_count }}</b>
              <span>切片</span><b>{{ indexStats.chunk_count }}</b>
              <span>Embeddings</span><b>{{ indexStats.embedding_count }}</b>
            </div>
          </div>

          <button :disabled="reindexing || !activeProject" @click="rebuildCurrentProjectIndex">
            {{ reindexing ? '正在重建索引...' : '重建当前项目索引' }}
          </button>

          <div v-if="reindexResult" class="upload-result">
            <strong>重建完成：{{ reindexResult.embedding_count }} 条 embedding</strong>
            <span>
              {{ reindexResult.section_count }} 个章节 ·
              {{ reindexResult.paragraph_count }} 个段落 ·
              {{ reindexResult.chunk_count }} 个切片
            </span>
          </div>
        </article>

        <article class="panel page-card create-project-card">
          <div class="section-heading">
            <div>
              <h2>创建项目</h2>
              <p class="muted">例如：财务、法律、产品资料、学习笔记。</p>
            </div>
          </div>

          <form class="project-form clean" @submit.prevent="submitProject">
            <input v-model="newProjectName" placeholder="新项目名，如：财务" />
            <input v-model="newProjectDescription" placeholder="简介，可选" />
            <button :disabled="creatingProject || !newProjectName.trim()">
              {{ creatingProject ? '创建中...' : '创建项目' }}
            </button>
          </form>
        </article>
      </section>

      <section v-else-if="currentView === 'documents'" class="page-grid documents-page">
        <article class="panel page-card upload-card">
          <div class="section-heading">
            <div>
              <h2>导入文档</h2>
              <p class="muted">当前项目：{{ activeProject?.name }}。第一阶段支持 md、txt、docx、pdf。</p>
            </div>
          </div>

          <label class="dropzone">
            <input type="file" accept=".md,.txt,.docx,.pdf" @change="onFileChange" />
            <span>{{ selectedFile?.name || '选择一个知识文件' }}</span>
          </label>
          <button :disabled="!selectedFile || uploading" @click="submitUpload">
            {{ uploading ? '正在预处理...' : '上传并建立索引' }}
          </button>

          <div v-if="uploadResult" class="upload-result">
            <strong>{{ uploadResult.document.filename }}</strong>
            <span>
              {{ uploadResult.section_count }} 个章节 ·
              {{ uploadResult.paragraph_count }} 个段落 ·
              {{ uploadResult.chunk_count }} 个切片
            </span>
          </div>
        </article>

        <article class="panel page-card document-page-card">
          <div class="section-heading">
            <div>
              <h2>{{ activeProject?.name }} 的文档</h2>
              <p class="muted">删除文档会同步清理章节、段落、切片和 embedding。</p>
            </div>
          </div>

          <div class="document-grid">
            <article v-for="doc in documents" :key="doc.id" class="document-item">
              <div class="document-head">
                <strong>{{ doc.filename }}</strong>
                <button
                  class="danger-button small-button"
                  :disabled="deletingDocumentId === doc.id"
                  @click="removeDocument(doc)"
                >
                  {{ deletingDocumentId === doc.id ? '删除中' : '删除' }}
                </button>
              </div>
              <span>{{ doc.file_type }} · {{ doc.created_at }}</span>
              <p>{{ doc.summary || '暂无简介' }}</p>
            </article>
            <p v-if="!documents.length" class="empty-state">当前项目还没有文档，先上传一份资料建立索引。</p>
          </div>
        </article>
      </section>

      <section v-else class="search-layout">
        <article class="panel page-card search-page-card">
          <div class="search-header">
            <div>
              <h2>检索 / 问答</h2>
              <p class="muted">
                当前只检索“{{ activeProject?.name }}”项目。纯检索返回片段；RAG 会把片段交给模型生成答案。
              </p>
              <p class="muted embedding-hint">
                {{ embedding?.semantic_enabled ? '语义检索已启用。' : '当前仍是 hash 开发检索模式，建议在项目页启用语义模型后重建索引。' }}
              </p>
            </div>
            <div class="mode-switch">
              <button :class="{ active: mode === 'search' }" @click="mode = 'search'">纯检索</button>
              <button :class="{ active: mode === 'rag' }" @click="mode = 'rag'">RAG 问答</button>
            </div>
          </div>

          <form class="query-box" @submit.prevent="submitSearch">
            <textarea v-model="query" placeholder="例如：项目里关于本地模型 API 的设计是什么？" />
            <button :disabled="loading || !query.trim()">
              {{ loading ? '检索中...' : '开始检索' }}
            </button>
          </form>
        </article>

        <article v-if="result?.answer" class="answer-card panel">
          <span>模型回答</span>
          <p>{{ result.answer }}</p>
          <div v-if="result.sources.length" class="source-list">
            <strong>本次回答引用来源</strong>
            <div v-for="source in result.sources" :key="`${source.document_id}-${source.section_title}-${source.match_type}`">
              {{ source.document_name }}
              <template v-if="source.section_title"> / {{ source.section_title }}</template>
              · {{ source.match_type }} · {{ source.score }}
            </div>
          </div>
        </article>

        <div v-if="result" class="hits panel page-card">
          <div class="section-heading">
            <div>
              <h2>命中结果</h2>
              <p class="muted">展开调试信息可以查看总分、向量分和关键词分。</p>
            </div>
          </div>

          <article v-for="hit in result.hits" :key="`${hit.match_type}-${hit.source_id}`" class="hit-card">
            <div class="hit-meta">
              <span>{{ hit.match_type }}</span>
              <span>score {{ hit.rank_score }}</span>
            </div>
            <h4>{{ hit.document_name }}</h4>
            <p v-if="hit.section_title" class="section-title">{{ hit.section_title }}</p>
            <p>{{ hit.text }}</p>
            <details class="debug-panel">
              <summary>查看检索调试信息</summary>
              <div class="score-grid">
                <span>项目</span><strong>{{ hit.project_name }}</strong>
                <span>总分</span><strong>{{ hit.rank_score }}</strong>
                <span>向量分</span><strong>{{ hit.vector_score }}</strong>
                <span>关键词分</span><strong>{{ hit.keyword_score }}</strong>
              </div>
            </details>
          </article>
          <p v-if="!result.hits.length" class="empty-state">没有找到相关内容。</p>
        </div>
      </section>
    </section>
  </main>
</template>
