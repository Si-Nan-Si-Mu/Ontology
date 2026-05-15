<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { apiFetch, apiUrl } from '@/api/http.js'
import { downloadPersonaExport } from '@/api/personaExport.js'

const graphPage = ref(1)
const graphPageSize = ref(15)
const graphTotal = ref(0)
const graphItems = ref([])
const graphLoading = ref(false)
const graphError = ref('')
const graphExportError = ref('')

const totalPages = computed(() =>
  Math.max(1, Math.ceil(graphTotal.value / graphPageSize.value) || 1),
)

function isPersonRow(row) {
  return Array.isArray(row?.labels) && row.labels.includes('Person') && row.properties?.subject_id
}

async function onGraphExportPersona(subjectId, format) {
  graphExportError.value = ''
  try {
    await downloadPersonaExport(subjectId, format)
  } catch (e) {
    graphExportError.value = e instanceof Error ? e.message : String(e)
  }
}

function truncateJson(obj, max = 160) {
  try {
    const s = JSON.stringify(obj)
    return s.length > max ? `${s.slice(0, max)}…` : s
  } catch {
    return String(obj)
  }
}

async function loadGraph() {
  graphError.value = ''
  graphExportError.value = ''
  graphLoading.value = true
  try {
    const q = new URLSearchParams({
      page: String(graphPage.value),
      page_size: String(graphPageSize.value),
    })
    const data = await apiFetch(`/api/v1/graph/nodes?${q}`)
    graphTotal.value = data.total ?? 0
    graphItems.value = data.items ?? []
  } catch (e) {
    graphItems.value = []
    graphTotal.value = 0
    graphError.value = e instanceof Error ? e.message : String(e)
  } finally {
    graphLoading.value = false
  }
}

function prevPage() {
  if (graphPage.value > 1) graphPage.value -= 1
}

function nextPage() {
  if (graphPage.value < totalPages.value) graphPage.value += 1
}

function resetGraphPage() {
  graphPage.value = 1
}

const rangeText = computed(() => {
  if (!graphTotal.value) return '无数据'
  const start = (graphPage.value - 1) * graphPageSize.value + 1
  const end = Math.min(graphPage.value * graphPageSize.value, graphTotal.value)
  return `第 ${start}–${end} 条，共 ${graphTotal.value} 节点`
})

onMounted(() => {
  loadGraph()
})

watch([graphPage, graphPageSize], () => {
  loadGraph()
})
</script>

<template>
  <div class="po-page graph">
    <section class="stats">
      <div class="stat po-card">
        <span class="stat-label">节点总数</span>
        <strong class="stat-value">{{ graphTotal }}</strong>
        <span class="stat-hint">MATCH (n) RETURN count(n)</span>
      </div>
      <div class="stat po-card">
        <span class="stat-label">当前页</span>
        <strong class="stat-value">{{ graphPage }} / {{ totalPages }}</strong>
        <span class="stat-hint">{{ rangeText }}</span>
      </div>
      <div class="stat po-card">
        <span class="stat-label">接口</span>
        <code class="stat-code po-mono">{{ apiUrl('/api/v1/graph/nodes') }}</code>
        <span class="stat-hint">分页参数 page, page_size</span>
      </div>
    </section>

    <section class="po-card panel">
      <div class="panel-head">
        <div>
          <h2>节点浏览</h2>
          <p class="muted">
            展示 Neo4j 中已有节点的 <code>elementId</code>、<code>labels</code> 与
            <code>properties</code>。后续可切换为子图查询或可视化画布。
          </p>
        </div>
        <div class="toolbar">
          <label class="inline">
            每页
            <select v-model.number="graphPageSize" class="page-size" @change="resetGraphPage">
              <option :value="10">10</option>
              <option :value="15">15</option>
              <option :value="20">20</option>
              <option :value="50">50</option>
            </select>
            条
          </label>
          <button type="button" class="po-btn" :disabled="graphLoading" @click="loadGraph">刷新</button>
        </div>
      </div>

      <p v-if="graphError" class="error">{{ graphError }}</p>
      <p v-if="graphExportError" class="error export-err">{{ graphExportError }}</p>

      <div class="table-wrap">
        <table v-if="graphItems.length">
          <thead>
            <tr>
              <th>element_id</th>
              <th>labels</th>
              <th>properties</th>
              <th class="col-actions">导出人格</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in graphItems" :key="row.element_id">
              <td class="po-mono cell-id">{{ row.element_id }}</td>
              <td class="cell-tags">
                <span v-for="lb in row.labels" :key="lb" class="tag">{{ lb }}</span>
              </td>
              <td class="po-mono cell-props">{{ truncateJson(row.properties) }}</td>
              <td class="cell-actions">
                <template v-if="isPersonRow(row)">
                  <button
                    type="button"
                    class="po-btn po-btn--ghost po-btn--sm"
                    @click="onGraphExportPersona(row.properties.subject_id, 'json')"
                  >
                    JSON
                  </button>
                  <button
                    type="button"
                    class="po-btn po-btn--ghost po-btn--sm"
                    @click="onGraphExportPersona(row.properties.subject_id, 'text')"
                  >
                    TXT
                  </button>
                </template>
                <span v-else class="muted dash">—</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="!graphLoading" class="empty muted">暂无节点：空库或连接失败。可先往 Neo4j 写入示例数据再刷新。</p>
        <p v-if="graphLoading" class="loading muted">加载中…</p>
      </div>

      <div class="pager">
        <button type="button" class="po-btn" :disabled="graphPage <= 1 || graphLoading" @click="prevPage">
          上一页
        </button>
        <span class="muted">{{ rangeText }}</span>
        <button
          type="button"
          class="po-btn"
          :disabled="graphPage >= totalPages || graphLoading"
          @click="nextPage"
        >
          下一页
        </button>
      </div>
    </section>

    <section class="po-card hint-card">
      <h3>图建模提示</h3>
      <p>
        本体字段与关系类型见仓库 <code>ontology/ONTOLOGY.yaml</code>。导入管线就绪后，本页可接「按
        <code>subject_id</code> 拉子图」等查询模板。
      </p>
    </section>
  </div>
</template>

<style scoped>
.graph {
  padding-top: 0.25rem;
}

.stats {
  display: grid;
  gap: 0.65rem;
  margin-bottom: 1rem;
}

@media (min-width: 720px) {
  .stats {
    grid-template-columns: repeat(3, 1fr);
  }
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.stat-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #94a3b8;
}

.stat-value {
  font-size: 1.35rem;
  font-weight: 750;
  color: #0f172a;
}

.stat-hint {
  font-size: 0.74rem;
  color: var(--po-muted, #64748b);
}

.stat-code {
  font-size: 0.68rem;
  word-break: break-all;
  color: #334155;
}

.panel h2 {
  margin: 0 0 0.35rem;
  font-size: 1.05rem;
}

.panel .muted {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.45;
  color: var(--po-muted, #64748b);
}

.panel .muted code {
  font-size: 0.76rem;
  background: #f1f5f9;
  padding: 0.05rem 0.25rem;
  border-radius: 4px;
}

.panel-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.inline {
  font-size: 0.82rem;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.page-size {
  padding: 0.25rem 0.4rem;
  border-radius: 6px;
  border: 1px solid var(--po-border, #e2e8f0);
}

.error {
  color: #b91c1c;
  font-size: 0.85rem;
  margin: 0 0 0.5rem;
}

.export-err {
  margin-top: -0.25rem;
}

.col-actions {
  white-space: nowrap;
  width: 1%;
}

.cell-actions {
  white-space: nowrap;
}

.cell-actions .po-btn {
  margin-right: 0.25rem;
}

.cell-actions .po-btn:last-of-type {
  margin-right: 0;
}

.dash {
  color: #94a3b8;
  font-size: 0.85rem;
}

.table-wrap {
  border: 1px solid var(--po-border, #e2e8f0);
  border-radius: 8px;
  overflow: auto;
  max-height: min(58vh, 480px);
  background: #fafafa;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;
}

th,
td {
  padding: 0.5rem 0.6rem;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
  vertical-align: top;
}

th {
  background: #f1f5f9;
  font-weight: 600;
  color: #475569;
  position: sticky;
  top: 0;
}

.cell-id {
  max-width: 8rem;
  word-break: break-all;
}

.cell-props {
  color: #334155;
}

.tag {
  display: inline-block;
  margin: 0 0.2rem 0.2rem 0;
  padding: 0.1rem 0.4rem;
  background: #e0e7ff;
  color: #3730a3;
  border-radius: 4px;
  font-size: 0.72rem;
}

.empty,
.loading {
  padding: 1.25rem;
  margin: 0;
}

.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 0.85rem;
}

.hint-card {
  margin-top: 1rem;
}

.hint-card h3 {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
}

.hint-card p {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.55;
  color: #475569;
}

.hint-card code {
  font-size: 0.78rem;
  background: #f1f5f9;
  padding: 0.05rem 0.25rem;
  border-radius: 4px;
}
</style>
