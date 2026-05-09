<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
  cancelJob,
  createProject,
  createImportJob,
  createReindexJob,
  deleteDocument,
  deleteProject,
  getEmbeddingHealth,
  getJob,
  getProjectIndexStats,
  getProviderHealth,
  listJobs,
  listDocuments,
  listProjects,
  searchKnowledge,
  retryJob,
  updateProject,
  type DocumentItem,
  type EmbeddingHealth,
  type JobItem,
  type ProjectIndexStats,
  type ProjectItem,
  type ProviderHealth,
  type ReindexResult,
  type SearchResponse,
  type UploadResult,
} from './services/api';

type ViewKey = 'projects' | 'documents' | 'search' | 'jobs';

const projects = ref<ProjectItem[]>([]);
const activeProjectId = ref(1);
const currentView = ref<ViewKey>('search');
const documents = ref<DocumentItem[]>([]);
const jobs = ref<JobItem[]>([]);
const jobsPageSize = 10;
const jobsPage = ref(1);
const jobsTotal = ref(0);
const jobsBusy = ref(false);
const jobsError = ref('');
const lastCreatedJobId = ref<number | null>(null);
const selectedJobId = ref<number | null>(null);
let selectedJobTimer: number | null = null;
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
  { key: 'jobs', label: '任务中心', description: '导入/重建的进度与历史' },
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

const jobsTotalPages = computed(() => Math.max(1, Math.ceil(jobsTotal.value / jobsPageSize)));

const selectedJob = computed(() => {
  if (selectedJobId.value == null) return jobs.value[0] ?? null;
  return jobs.value.find((job) => job.id === selectedJobId.value) ?? jobs.value[0] ?? null;
});

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
}

function goTo(view: ViewKey) {
  currentView.value = view;
}

async function onProjectSelect(event: Event) {
  const select = event.target as HTMLSelectElement;
  await switchProject(Number(select.value));
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

async function refreshJobs() {
  jobsBusy.value = true;
  jobsError.value = '';
  try {
    const offset = (jobsPage.value - 1) * jobsPageSize;
    const response = await listJobs(activeProjectId.value, jobsPageSize, offset);
    jobs.value = response.items;
    jobsTotal.value = response.total;
    if (jobs.value.length && !jobs.value.some((job) => job.id === selectedJobId.value)) {
      selectedJobId.value = jobs.value[0].id;
    }
    if (!jobs.value.length) {
      selectedJobId.value = null;
    }
    if (lastCreatedJobId.value != null && !jobs.value.some((job) => job.id === lastCreatedJobId.value)) {
      lastCreatedJobId.value = null;
    }
  } catch (err) {
    jobsError.value = err instanceof Error ? err.message : '读取任务失败';
  } finally {
    jobsBusy.value = false;
  }
}

async function switchProject(projectId: number) {
  activeProjectId.value = projectId;
  uploadResult.value = null;
  result.value = null;
  editingProject.value = false;
  jobsPage.value = 1;
  selectedJobId.value = null;
  documents.value = await listDocuments(projectId);
  indexStats.value = await getProjectIndexStats(projectId);
  if (currentView.value === 'jobs') {
    await refreshJobs();
  }
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
    currentView.value = 'projects';
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建项目失败';
  } finally {
    creatingProject.value = false;
  }
}

function startEditProject(project = activeProject.value) {
  if (!project) return;
  activeProjectId.value = project.id;
  editProjectName.value = project.name;
  editProjectDescription.value = project.description;
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

async function removeProject(project = activeProject.value) {
  if (!project || project.id === 1) return;
  const confirmed = window.confirm(`确认删除项目“${project.name}”及其全部文档和索引吗？`);
  if (!confirmed) return;

  deletingProject.value = true;
  error.value = '';
  try {
    await deleteProject(project.id);
    if (activeProjectId.value === project.id) {
      activeProjectId.value = 1;
    }
    uploadResult.value = null;
    result.value = null;
    editingProject.value = false;
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
    const res = await createReindexJob(activeProject.value.id);
    lastCreatedJobId.value = res.job_id;
    reindexResult.value = null;
    result.value = null;
    currentView.value = 'jobs';
    jobsPage.value = 1;
    await refreshJobs();
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建重建索引任务失败';
  } finally {
    reindexing.value = false;
  }
}

async function submitUpload() {
  if (!selectedFile.value) return;
  uploading.value = true;
  error.value = '';
  try {
    const res = await createImportJob(selectedFile.value, activeProjectId.value);
    lastCreatedJobId.value = res.job_id;
    selectedFile.value = null;
    uploadResult.value = null;
    currentView.value = 'jobs';
    jobsPage.value = 1;
    await refreshJobs();
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建导入任务失败';
  } finally {
    uploading.value = false;
  }
}

function jobBadge(job: JobItem) {
  if (job.status === 'queued') return '排队中';
  if (job.status === 'running') return '执行中';
  if (job.status === 'succeeded') return '已完成';
  if (job.status === 'failed') return '失败';
  if (job.status === 'cancelled') return '已取消';
  return job.status;
}

async function cancel(job: JobItem) {
  if (job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled') return;
  try {
    await cancelJob(job.id);
    await refreshJobs();
  } catch (err) {
    jobsError.value = err instanceof Error ? err.message : '取消失败';
  }
}

async function retry(job: JobItem) {
  if (job.status !== 'failed') return;
  try {
    const res = await retryJob(job.id);
    lastCreatedJobId.value = res.job_id;
    await refreshJobs();
  } catch (err) {
    jobsError.value = err instanceof Error ? err.message : '重试失败';
  }
}

function formatProgress(job: JobItem) {
  if (job.progress_current == null || job.progress_total == null) return '';
  return `${job.progress_current}/${job.progress_total}`;
}

function progressPercent(job: JobItem) {
  if (!job.progress_total || job.progress_current == null) return 0;
  return Math.min(100, Math.round((job.progress_current / job.progress_total) * 100));
}

function jobTypeLabel(job: JobItem) {
  if (job.type === 'import_document') return '文档导入';
  if (job.type === 'reindex_project') return '重建索引';
  return job.type;
}

function jobPrimaryText(job: JobItem) {
  if (job.type === 'import_document') {
    return job.target_name ? `导入：${job.target_name}` : '文档导入';
  }
  return jobTypeLabel(job);
}

function jobSecondaryText(job: JobItem) {
  if (job.status === 'failed') {
    return job.error || '执行失败';
  }
  if (job.type === 'import_document') {
    if (job.status === 'succeeded') return '导入完成';
    if (job.status === 'queued') return '等待执行…';
    if (job.status === 'running') return job.message || '执行中…';
  }
  if (job.type === 'reindex_project') {
    if (job.status === 'succeeded') return '重建完成';
    if (job.status === 'queued') return '等待执行…';
    if (job.status === 'running') return job.message || '执行中…';
  }
  if (job.message && !['执行失败', '导入完成', '重建完成'].includes(job.message)) return job.message;
  return '';
}

function statusClass(job: JobItem) {
  return `status-${job.status}`;
}

function selectJob(job: JobItem) {
  selectedJobId.value = job.id;
  if (lastCreatedJobId.value === job.id) {
    lastCreatedJobId.value = null;
  }
}

function jobSeq(job: JobItem) {
  const index = jobs.value.findIndex((item) => item.id === job.id);
  if (index < 0) return null;
  return (jobsPage.value - 1) * jobsPageSize + index + 1;
}

function upsertJob(job: JobItem) {
  const index = jobs.value.findIndex((item) => item.id === job.id);
  if (index >= 0) {
    jobs.value.splice(index, 1, job);
  }
}

async function refreshSelectedJob() {
  if (selectedJobId.value == null) return;
  try {
    const job = await getJob(selectedJobId.value);
    upsertJob(job);
  } catch (err) {
    jobsError.value = err instanceof Error ? err.message : '刷新任务进度失败';
  }
}

function stopSelectedJobAutoRefresh() {
  if (selectedJobTimer != null) {
    window.clearInterval(selectedJobTimer);
    selectedJobTimer = null;
  }
}

function syncSelectedJobAutoRefresh() {
  const job = selectedJob.value;
  const shouldAutoRefresh =
    currentView.value === 'jobs' && job && (job.status === 'queued' || job.status === 'running');

  if (!shouldAutoRefresh) {
    stopSelectedJobAutoRefresh();
    return;
  }

  if (selectedJobTimer != null) return;
  selectedJobTimer = window.setInterval(() => {
    refreshSelectedJob().catch(() => undefined);
  }, 1500);
}

async function goJobsPage(nextPage: number) {
  const page = Math.min(Math.max(nextPage, 1), jobsTotalPages.value);
  if (page === jobsPage.value) return;
  jobsPage.value = page;
  selectedJobId.value = null;
  await refreshJobs();
}

function tryParseResult(job: JobItem): any | null {
  if (!job.result_json) return null;
  try {
    return JSON.parse(job.result_json);
  } catch {
    return null;
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

watch(
  () => currentView.value,
  (view) => {
    if (view === 'jobs') {
      refreshJobs().catch(() => undefined);
    } else {
      stopSelectedJobAutoRefresh();
    }
  },
);

watch(
  () => jobs.value,
  (newJobs, oldJobs) => {
    const hadBusy = (oldJobs ?? []).some((j) => j.status === 'queued' || j.status === 'running');
    const hasBusy = (newJobs ?? []).some((j) => j.status === 'queued' || j.status === 'running');
    if (hadBusy && !hasBusy) {
      refresh().catch(() => undefined);
    }
  },
  { deep: true },
);

watch(
  () => [currentView.value, selectedJob.value?.id, selectedJob.value?.status],
  () => {
    syncSelectedJobAutoRefresh();
  },
);

onBeforeUnmount(() => {
  stopSelectedJobAutoRefresh();
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
        <div class="topbar-title">
          <p class="eyebrow">{{ activeViewTitle }}</p>
          <h2>{{ stats.project }}</h2>
        </div>
        <label class="project-switcher">
          <span>当前项目</span>
          <select :value="activeProjectId" @change="onProjectSelect">
            <option v-for="project in projects" :key="project.id" :value="project.id">
              {{ project.name }}
            </option>
          </select>
        </label>
        <div class="stats-strip">
          <span>文档 {{ stats.documents }}</span>
          <span>模型 {{ stats.provider }}</span>
          <span>{{ stats.embedding }}</span>
          <span>{{ stats.mode }}</span>
        </div>
      </header>

      <p v-if="error" class="error">{{ error }}</p>

      <section v-if="currentView === 'projects'" class="page-grid projects-page">
        <article class="panel page-card project-directory-card">
          <div class="section-heading">
            <div>
              <h2>项目列表</h2>
              <p class="muted">项目是知识库的隔离边界。点击“设为当前”后，检索问答、文档和任务都会切换到该项目。</p>
            </div>
          </div>

          <div class="project-table">
            <article
              v-for="project in projects"
              :key="project.id"
              class="project-row"
              :class="{ active: project.id === activeProjectId }"
            >
              <div>
                <strong>{{ project.name }}</strong>
                <p>{{ project.description || '暂无简介' }}</p>
              </div>
              <div class="project-row-actions">
                <button class="ghost-button small-button" :disabled="project.id === activeProjectId" @click="switchProject(project.id)">
                  {{ project.id === activeProjectId ? '当前项目' : '设为当前' }}
                </button>
                <button class="ghost-button small-button" @click="startEditProject(project)">编辑</button>
                <button
                  class="danger-button small-button"
                  :disabled="project.id === 1 || deletingProject"
                  :title="project.id === 1 ? '默认项目不可删除' : ''"
                  @click="removeProject(project)"
                >
                  删除
                </button>
              </div>
            </article>
          </div>
        </article>

        <article class="panel page-card project-editor-card">
          <div class="section-heading">
            <div>
              <h2>当前项目</h2>
              <p class="muted">这里展示全局当前项目。你也可以在页面顶部随时切换项目。</p>
            </div>
          </div>

          <div v-if="activeProject" class="project-profile">
            <div>
              <strong>{{ activeProject.name }}</strong>
              <p>{{ activeProject.description || '暂无简介' }}</p>
            </div>
            <div class="project-profile-meta">
              <span>文档 {{ indexStats?.document_count ?? documents.length }}</span>
              <span>章节 {{ indexStats?.section_count ?? '-' }}</span>
              <span>Embeddings {{ indexStats?.embedding_count ?? '-' }}</span>
            </div>
            <div class="action-row">
              <button type="button" class="ghost-button" @click="startEditProject()">编辑当前项目</button>
              <button
                type="button"
                class="danger-button"
                :disabled="activeProject.id === 1 || deletingProject"
                :title="activeProject.id === 1 ? '默认项目不可删除' : ''"
                @click="removeProject()"
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

        <article class="panel page-card create-project-card">
          <div class="section-heading">
            <div>
              <h2>新增项目</h2>
              <p class="muted">例如：财务、法律、产品资料、学习笔记。创建后会自动设为当前项目。</p>
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

        <article class="panel page-card project-index-card">
          <div class="section-heading">
            <div>
              <h2>当前项目索引</h2>
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
            <p class="muted" style="margin: 0">
              当前配置版本：{{ indexStats.embedding_version || '-' }}
              <template v-if="indexStats.dominant_embedding_version">
                · 库内主版本：{{ indexStats.dominant_embedding_version }}
              </template>
              <template v-if="indexStats.matches_current_config"> · 版本匹配</template>
              <template v-else> · 版本不匹配</template>
            </p>
            <div class="index-stats-grid">
              <span>文档</span><b>{{ indexStats.document_count }}</b>
              <span>章节</span><b>{{ indexStats.section_count }}</b>
              <span>段落</span><b>{{ indexStats.paragraph_count }}</b>
              <span>切片</span><b>{{ indexStats.chunk_count }}</b>
              <span>Embeddings(当前版本)</span><b>{{ indexStats.embedding_count }}</b>
            </div>
            <p class="muted" style="margin: 0">
              Embeddings(总计)：{{ indexStats.embedding_count_total }}
              · provider：{{ indexStats.embedding_provider || '-' }}
              · model：{{ indexStats.embedding_model || '-' }}
              · dim：{{ indexStats.embedding_dimension || '-' }}
            </p>
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

      <section v-else-if="currentView === 'jobs'" class="page-grid jobs-page">
        <article class="panel page-card">
          <div class="section-heading">
            <div>
              <h2>任务中心</h2>
              <p class="muted">当前项目：{{ activeProject?.name }}。列表手动刷新；选中的执行中任务会自动更新进度。</p>
            </div>
            <button class="ghost-button compact-button" :disabled="jobsBusy" @click="refreshJobs">
              {{ jobsBusy ? '刷新中...' : '刷新任务' }}
            </button>
          </div>

          <p v-if="jobsError" class="error">{{ jobsError }}</p>

          <div class="jobs-board">
            <section class="jobs-list-card">
              <div class="jobs-list-head">
                <span>共 {{ jobsTotal }} 个任务</span>
                <span>第 {{ jobsPage }} / {{ jobsTotalPages }} 页</span>
              </div>

              <button
                v-for="job in jobs"
                :key="job.id"
                type="button"
                class="job-row"
                :class="{
                  active: selectedJob?.id === job.id,
                  highlight: lastCreatedJobId === job.id,
                }"
                @click="selectJob(job)"
              >
                <span class="job-row-main">
                  <strong>No.{{ jobSeq(job) ?? '-' }} · {{ jobPrimaryText(job) }}</strong>
                  <small>{{ jobSecondaryText(job) || '—' }}</small>
                </span>
                <span class="job-row-side">
                  <b class="status-pill" :class="statusClass(job)">{{ jobBadge(job) }}</b>
                  <small>{{ formatProgress(job) || '-' }}</small>
                </span>
              </button>

              <p v-if="!jobs.length" class="empty-state">当前项目还没有任务记录。去“文档管理”上传或去“项目空间”触发重建索引。</p>

              <div v-if="jobsTotal > jobsPageSize" class="pagination-bar">
                <button class="ghost-button small-button" :disabled="jobsPage <= 1" @click="goJobsPage(jobsPage - 1)">
                  上一页
                </button>
                <span class="muted">{{ (jobsPage - 1) * jobsPageSize + 1 }} - {{ Math.min(jobsPage * jobsPageSize, jobsTotal) }} / {{ jobsTotal }}</span>
                <button class="ghost-button small-button" :disabled="jobsPage >= jobsTotalPages" @click="goJobsPage(jobsPage + 1)">
                  下一页
                </button>
              </div>
            </section>

            <aside v-if="selectedJob" class="job-detail-card">
              <div class="document-head">
                <div>
                  <span class="muted">任务详情</span>
                  <h3>No.{{ jobSeq(selectedJob) ?? '-' }} · {{ jobPrimaryText(selectedJob) }}</h3>
                  <small class="muted">ID {{ selectedJob.id }}</small>
                </div>
                <b class="status-pill" :class="statusClass(selectedJob)">{{ jobBadge(selectedJob) }}</b>
              </div>

              <p class="muted">{{ jobSecondaryText(selectedJob) || selectedJob.message || '—' }}</p>
              <div class="progress-track">
                <span :style="{ width: `${progressPercent(selectedJob)}%` }"></span>
              </div>
              <div class="score-grid">
                <span>进度</span><strong>{{ formatProgress(selectedJob) || '-' }}</strong>
                <span>创建时间</span><strong>{{ selectedJob.created_at }}</strong>
                <span>更新时间</span><strong>{{ selectedJob.updated_at }}</strong>
                <span>重试次数</span><strong>{{ selectedJob.retry_count }}</strong>
              </div>

              <details v-if="selectedJob.error || selectedJob.result_json" class="debug-panel">
                <summary>查看结果 / 错误</summary>
                <pre v-if="selectedJob.error" class="error result-block">{{ selectedJob.error }}</pre>
                <pre v-else class="muted result-block">{{
                  tryParseResult(selectedJob) ? JSON.stringify(tryParseResult(selectedJob), null, 2) : selectedJob.result_json
                }}</pre>
              </details>

              <div class="action-row">
                <button
                  class="ghost-button"
                  :disabled="selectedJob.status !== 'queued' && selectedJob.status !== 'running'"
                  @click="cancel(selectedJob)"
                >
                  取消
                </button>
                <button
                  class="ghost-button"
                  :disabled="selectedJob.status !== 'failed'"
                  @click="retry(selectedJob)"
                >
                  重试
                </button>
              </div>
            </aside>
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
