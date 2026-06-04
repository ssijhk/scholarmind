<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <h2>文渊 · ScholarMind</h2>
      </div>
      <nav class="nav-menu">
        <router-link to="/library" class="nav-item">
          <span class="icon">📚</span> 论文文献库
        </router-link>
        <router-link to="/chat" class="nav-item">
          <span class="icon">💬</span> 文献对话调研
        </router-link>
        <router-link to="/observability" class="nav-item active">
          <span class="icon">📊</span> 系统可观测页
        </router-link>
        <router-link to="/settings" class="nav-item">
          <span class="icon">⚙️</span> 系统配置中心
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <button class="logout-btn" @click="handleLogout">退出登录</button>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="main-content">
      <header class="content-header">
        <h1>系统可观测数据</h1>
      </header>

      <div class="content-body">
        <!-- Overview Stats Grid -->
        <div class="metrics-grid">
          <div class="metric-card">
            <span class="metric-title">📁 知识库文档数</span>
            <div class="metric-val">{{ stats.paper_count }} <span class="sub">篇</span></div>
          </div>
          <div class="metric-card">
            <span class="metric-title">🧩 已构建向量分块</span>
            <div class="metric-val">{{ stats.chunk_count.toLocaleString() }} <span class="sub">个</span></div>
          </div>
          <div class="metric-card">
            <span class="metric-title">⚡ 平均问答延迟</span>
            <div class="metric-val">{{ Math.round(stats.average_latency_ms) }} <span class="sub">ms</span></div>
          </div>
          <div class="metric-card">
            <span class="metric-title">📊 历史查询总数</span>
            <div class="metric-val">{{ stats.total_queries.toLocaleString() }} <span class="sub">次</span></div>
          </div>
        </div>

        <!-- Ingestion Pipeline Progress -->
        <div class="observability-section">
          <h3>⏳ 文档解析与入库流水线 (RQ Worker 状态)</h3>
          <div class="tasks-container">
            <div v-for="task in activeTasks" :key="task.id" class="task-progress-card">
              <div class="task-meta">
                <span class="task-name">📄 {{ task.file_name }}</span>
                <span :class="['stage-tag', task.stage]">{{ stageMap[task.stage] }}</span>
              </div>
              <div class="progress-bar-wrapper">
                <div class="progress-bar-fill" :style="{ width: task.progress + '%' }"></div>
              </div>
              <div class="task-foot">
                <span class="progress-text">{{ task.progress }}% 已完成</span>
                <span v-if="task.error_msg" class="task-error">⚠️ 错误: {{ task.error_msg }}</span>
                <span class="task-time">开始于: {{ task.started_at }}</span>
              </div>
            </div>
            <div v-if="activeTasks.length === 0" class="empty-list">
              目前没有正在处理的入库任务。
            </div>
          </div>
        </div>

        <!-- Query Logs -->
        <div class="observability-section">
          <h3>📜 问答检索日志 (Query Logs)</h3>
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th>提问</th>
                  <th>改写查询 (Rewritten)</th>
                  <th>检索延迟 (ms)</th>
                  <th>Token 消耗 (输入/输出)</th>
                  <th>命中 Chunks</th>
                  <th>用户反馈</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="queryLogs.length === 0">
                  <td colspan="6" class="empty-list" style="padding: 40px;">
                    暂无语问检索日志。请先在「文献对话调研」中提问，系统将自动记录。
                  </td>
                </tr>
                <tr v-for="log in queryLogs" :key="log.id">
                  <td class="question-text">{{ log.question }}</td>
                  <td class="rewritten-text">{{ log.rewritten_query || '无改写' }}</td>
                  <td class="num-col">{{ log.latency_ms !== null ? log.latency_ms + ' ms' : '-' }}</td>
                  <td class="num-col">{{ log.prompt_tokens !== null ? log.prompt_tokens + ' / ' + log.completion_tokens : '-' }}</td>
                  <td>
                    <template v-if="(log.retrieved_chunk_ids || []).filter(c => c).length > 0">
                      <span v-for="cid in log.retrieved_chunk_ids.filter(c => c)" :key="cid" class="chunk-badge">
                        #{{ cid }}
                      </span>
                    </template>
                    <span v-else class="fb-tag none">-</span>
                  </td>
                  <td>
                    <span v-if="log.feedback === 1" class="fb-tag up">👍 赞</span>
                    <span v-else-if="log.feedback === -1" class="fb-tag down">👎 踩</span>
                    <span v-else class="fb-tag none">-</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import api from '../api';

const router = useRouter();
const authStore = useAuthStore();

interface Stats { paper_count: number; chunk_count: number; total_queries: number; average_latency_ms: number }
interface Task { id: string; file_name: string; stage: string; progress: number; error_msg: string | null; started_at: string | null }
interface QueryLog { id: string; question: string; rewritten_query: string | null; latency_ms: number | null; prompt_tokens: number | null; completion_tokens: number | null; retrieved_chunk_ids: string[] | null; feedback: number | null }

const stats = ref<Stats>({ paper_count: 0, chunk_count: 0, total_queries: 0, average_latency_ms: 0 });
const activeTasks = ref<Task[]>([]);
const queryLogs = ref<QueryLog[]>([]);

const stageMap: Record<string, string> = {
  queued: '排队中', parsing: '版面解析中 (MinerU/GROBID)', indexing: '向量索引构建中',
  pending: '排队中', done: '处理完毕', failed: '任务失败',
};

onMounted(async () => {
  try { const r = await api.get('/api/stats/overview'); stats.value = r.data; } catch (e) { console.error('stats/overview error:', e) }
  try { const r = await api.get('/api/tasks'); activeTasks.value = r.data; } catch (e) { console.error('tasks error:', e) }
  try { const r = await api.get('/api/logs/queries'); queryLogs.value = r.data; } catch (e) { console.error('logs/queries error:', e) }
});

function handleLogout() {
  authStore.clearAuth();
  router.push('/login');
}
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  background-color: #f7f9f8;
  font-family: 'Inter', sans-serif;
  color: #1a3322;
}

/* Sidebar */
.sidebar {
  width: 260px;
  background-color: #0f3d24;
  color: #ffffff;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 30px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.sidebar-header h2 {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  background: linear-gradient(135deg, #a2f26d 0%, #ffffff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.nav-menu {
  flex: 1;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  color: rgba(255, 255, 255, 0.75);
  text-decoration: none;
  font-weight: 600;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.nav-item:hover, .nav-item.active {
  color: #ffffff;
  background-color: rgba(255, 255, 255, 0.12);
}

.sidebar-footer {
  padding: 24px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.logout-btn {
  width: 100%;
  padding: 10px;
  background-color: transparent;
  color: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.logout-btn:hover {
  color: #ffffff;
  border-color: #ffffff;
  background-color: rgba(255, 255, 255, 0.05);
}

/* Main */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow-y: auto;
}

.content-header {
  padding: 20px 40px;
  background-color: #ffffff;
  border-bottom: 1px solid #e1e6e3;
}

.content-header h1 {
  font-size: 24px;
  font-weight: 700;
  margin: 0;
  color: #0f3d24;
}

.content-body {
  padding: 40px;
  display: flex;
  flex-direction: column;
  gap: 40px;
}

/* Metrics stats grid */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.metric-card {
  background: #ffffff;
  padding: 20px;
  border-radius: 12px;
  border: 1px solid #e1e6e3;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
}

.metric-title {
  display: block;
  font-size: 13px;
  color: #667e6e;
  font-weight: 600;
  margin-bottom: 10px;
}

.metric-val {
  font-size: 24px;
  font-weight: 700;
  color: #0f3d24;
}

.metric-val .sub {
  font-size: 13px;
  font-weight: normal;
  color: #667e6e;
}

.observability-section {
  background: #ffffff;
  padding: 24px;
  border-radius: 12px;
  border: 1px solid #e1e6e3;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
}

.observability-section h3 {
  margin: 0 0 20px 0;
  font-size: 16px;
  font-weight: 700;
  color: #0f3d24;
}

/* Ingestion Tasks */
.tasks-container {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.task-progress-card {
  background-color: #f8faf9;
  border: 1px solid #e1e6e3;
  border-radius: 8px;
  padding: 16px;
}

.task-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}

.task-name {
  font-weight: 600;
  font-size: 14px;
}

.stage-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}

.stage-tag.parsing {
  background-color: #fffaf0;
  color: #b35900;
  border: 1px solid #ffe8cc;
}

.stage-tag.queued {
  background-color: #f7fafc;
  color: #4a5568;
  border: 1px solid #e2e8f0;
}

.progress-bar-wrapper {
  height: 8px;
  background-color: #e2ece7;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 10px;
}

.progress-bar-fill {
  height: 100%;
  background-color: #1c7243;
  border-radius: 4px;
  transition: width 0.5s ease;
}

.task-foot {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #667e6e;
}

.task-error {
  color: #a71d24;
  font-weight: bold;
}

.empty-list {
  text-align: center;
  color: #667e6e;
  padding: 20px;
}

/* Query logs table */
.table-container {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

th {
  padding: 12px;
  border-bottom: 2px solid #e1e6e3;
  color: #556c5c;
  font-size: 13px;
  font-weight: 600;
}

td {
  padding: 14px 12px;
  border-bottom: 1px solid #f0f3f1;
  font-size: 13px;
}

.question-text {
  font-weight: 600;
  max-width: 250px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rewritten-text {
  color: #486551;
  max-width: 250px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.num-col {
  font-family: monospace;
}

.chunk-badge {
  display: inline-block;
  padding: 2px 6px;
  background-color: #e2ece7;
  border: 1px solid #c2cdc6;
  color: #0f3d24;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  margin-right: 4px;
}

.fb-tag {
  font-size: 12px;
  font-weight: 600;
}

.fb-tag.up {
  color: #2f855a;
}

.fb-tag.down {
  color: #c53030;
}

.fb-tag.none {
  color: #a0aec0;
}
</style>
