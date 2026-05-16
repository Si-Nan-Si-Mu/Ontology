<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { apiFetch, apiUrl } from '@/api/http.js'

const route = useRoute()
const router = useRouter()

/** 主标签 -> 节点配色（与 Neo4j facet 标签对齐） */
const LABEL_COLORS = {
  PersonaSummary: '#2563eb',
  ExpressionStyleTrait: '#0891b2',
  VerbalTicObservation: '#ca8a04',
  EmotionDimensionObservation: '#db2777',
  SocialRelationSketchFacet: '#059669',
  EnneagramHypothesisFacet: '#7c3aed',
  BigFiveTraitFacet: '#4f46e5',
  BigFiveSketchFacet: '#6366f1',
  MbtiHypothesisFacet: '#0d9488',
  PersonaAnalysisMeta: '#64748b',
  DialogueExemplar: '#ea580c',
  SalientTraitObservation: '#be185d',
  default: '#475569',
}

const persons = ref([])
const personsLoading = ref(false)
const personsError = ref('')
const selectedSubjectId = ref('')

const subgraph = ref(null)
const subgraphLoading = ref(false)
const subgraphError = ref('')

const viewTab = ref('ontology')

const graphPage = ref(1)
const graphPageSize = ref(15)
const graphTotal = ref(0)
const graphItems = ref([])
const graphLoading = ref(false)
const graphError = ref('')

/** 子图交互：平移、缩放、节点拖拽（相对布局坐标） */
const panX = ref(0)
const panY = ref(0)
const zoomScale = ref(1)
const personOffset = ref({ dx: 0, dy: 0 })
/** facet 位移，key 为 target_element_id 或 idx-n */
const facetOffsets = ref({})
let dragState = null

function resetGraphViewTransform() {
  panX.value = 0
  panY.value = 0
  zoomScale.value = 1
  personOffset.value = { dx: 0, dy: 0 }
  facetOffsets.value = {}
}

function facetDragKey(node, idx) {
  const id = node?.target_element_id
  return id != null && String(id) !== '' ? String(id) : `idx-${idx}`
}

const paintLayout = computed(() => {
  const L = layout.value
  const cx0 = L?.cx ?? 450
  const cy0 = L?.cy ?? 260
  const cx = cx0 + personOffset.value.dx
  const cy = cy0 + personOffset.value.dy
  const nodes = (L?.nodes || []).map((n, idx) => {
    const k = facetDragKey(n, idx)
    const off = facetOffsets.value[k] || { dx: 0, dy: 0 }
    const x = n.x + off.dx
    const y = n.y + off.dy
    return {
      ...n,
      _dragKey: k,
      x,
      y,
      midX: (cx + x) / 2,
      midY: (cy + y) / 2,
    }
  })
  return {
    ...L,
    cx,
    cy,
    nodes,
    person: L?.person,
  }
})

const shellTransform = computed(() => {
  const { cx, cy } = paintLayout.value
  const z = zoomScale.value
  const px = panX.value
  const py = panY.value
  return `translate(${px},${py}) translate(${cx},${cy}) scale(${z}) translate(${-cx},${-cy})`
})

function onWheelSvg(e) {
  e.preventDefault()
  const z0 = zoomScale.value
  const factor = Math.exp(-e.deltaY * 0.0012)
  zoomScale.value = Math.min(3.2, Math.max(0.22, z0 * factor))
}

function zoomIn() {
  zoomScale.value = Math.min(3.2, zoomScale.value * 1.18)
}

function zoomOut() {
  zoomScale.value = Math.max(0.22, zoomScale.value / 1.18)
}

function onWindowPointerMove(e) {
  if (!dragState) return
  if (dragState.type === 'pan') {
    panX.value = dragState.pan0x + (e.clientX - dragState.sx)
    panY.value = dragState.pan0y + (e.clientY - dragState.sy)
    return
  }
  const inv = 1 / zoomScale.value
  const dx = (e.clientX - dragState.lastX) * inv
  const dy = (e.clientY - dragState.lastY) * inv
  dragState.lastX = e.clientX
  dragState.lastY = e.clientY
  if (dragState.type === 'person') {
    personOffset.value = {
      dx: personOffset.value.dx + dx,
      dy: personOffset.value.dy + dy,
    }
    return
  }
  if (dragState.type === 'facet') {
    const k = dragState.key
    const cur = facetOffsets.value[k] || { dx: 0, dy: 0 }
    facetOffsets.value = {
      ...facetOffsets.value,
      [k]: { dx: cur.dx + dx, dy: cur.dy + dy },
    }
  }
}

function endDrag() {
  dragState = null
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onWindowPointerUp)
  window.removeEventListener('pointercancel', onWindowPointerUp)
}

function onWindowPointerUp() {
  endDrag()
}

function onPanBgDown(e) {
  if (e.button !== 0) return
  dragState = {
    type: 'pan',
    sx: e.clientX,
    sy: e.clientY,
    pan0x: panX.value,
    pan0y: panY.value,
  }
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onWindowPointerUp)
  window.addEventListener('pointercancel', onWindowPointerUp)
  try {
    e.target?.setPointerCapture?.(e.pointerId)
  } catch {
    /* ignore */
  }
}

function onPersonPointerDown(e) {
  if (e.button !== 0) return
  e.stopPropagation()
  dragState = {
    type: 'person',
    lastX: e.clientX,
    lastY: e.clientY,
  }
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onWindowPointerUp)
  window.addEventListener('pointercancel', onWindowPointerUp)
}

function onFacetPointerDown(e, node, idx) {
  if (e.button !== 0) return
  e.stopPropagation()
  const key = facetDragKey(node, idx)
  dragState = {
    type: 'facet',
    key,
    lastX: e.clientX,
    lastY: e.clientY,
  }
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onWindowPointerUp)
  window.addEventListener('pointercancel', onWindowPointerUp)
}

onUnmounted(() => {
  endDrag()
})

watch(
  () => subgraph.value?.subject_id,
  () => {
    resetGraphViewTransform()
  },
)

const totalPages = computed(() =>
  Math.max(1, Math.ceil(graphTotal.value / graphPageSize.value) || 1),
)

const layout = computed(() => {
  const data = subgraph.value
  if (!data?.edges?.length) {
    return {
      cx: 450,
      cy: 260,
      r: 0,
      nodes: [],
      person: data?.person || null,
    }
  }
  const cx = 450
  const cy = 260
  const R = 210
  const n = data.edges.length
  const nodes = data.edges.map((edge, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2
    return {
      ...edge,
      x: cx + R * Math.cos(angle),
      y: cy + R * Math.sin(angle),
      midX: cx + (R * 0.55) * Math.cos(angle),
      midY: cy + (R * 0.55) * Math.sin(angle),
    }
  })
  return { cx, cy, R, nodes, person: data.person }
})

function colorForLabels(labels) {
  if (!Array.isArray(labels)) return LABEL_COLORS.default
  for (const lb of labels) {
    if (LABEL_COLORS[lb]) return LABEL_COLORS[lb]
  }
  return LABEL_COLORS.default
}

function facetCaption(edge) {
  const p = edge.target_properties || {}
  const keys = [
    'label',
    'pattern_label',
    'trait_key',
    'dimension',
    'type_code',
    'text',
    'description',
  ]
  for (const k of keys) {
    const v = p[k]
    if (typeof v === 'string' && v.trim()) return v.trim().slice(0, 42)
  }
  const lbs = edge.target_labels || []
  return lbs[0] || '节点'
}

function truncateJson(obj, max = 140) {
  try {
    const s = JSON.stringify(obj)
    return s.length > max ? `${s.slice(0, max)}…` : s
  } catch {
    return String(obj)
  }
}

async function loadPersons() {
  personsError.value = ''
  personsLoading.value = true
  try {
    const data = await apiFetch('/api/v1/persons')
    persons.value = Array.isArray(data.items) ? data.items : []
  } catch (e) {
    persons.value = []
    personsError.value = e instanceof Error ? e.message : String(e)
  } finally {
    personsLoading.value = false
  }
}

async function loadSubgraph() {
  subgraph.value = null
  subgraphError.value = ''
  const sid = selectedSubjectId.value.trim()
  if (!sid) return
  subgraphLoading.value = true
  try {
    subgraph.value = await apiFetch(`/api/v1/person/${encodeURIComponent(sid)}/subgraph`)
  } catch (e) {
    subgraph.value = null
    subgraphError.value = e instanceof Error ? e.message : String(e)
  } finally {
    subgraphLoading.value = false
  }
}

function syncQueryFromSelection() {
  const sid = selectedSubjectId.value.trim()
  router.replace({ query: sid ? { subject: sid } : {} })
}

async function loadGraphBrowse() {
  graphError.value = ''
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

onMounted(async () => {
  await loadPersons()
  const q = route.query.subject
  const qSid = typeof q === 'string' ? q.trim() : ''
  if (qSid && persons.value.some((p) => p.subject_id === qSid)) {
    selectedSubjectId.value = qSid
  } else if (persons.value.length) {
    selectedSubjectId.value = persons.value[0].subject_id
  }
  await loadGraphBrowse()
})

watch(
  () => route.query.subject,
  (q) => {
    const qSid = typeof q === 'string' ? q.trim() : ''
    if (!qSid || qSid === selectedSubjectId.value) return
    if (persons.value.some((p) => p.subject_id === qSid)) {
      selectedSubjectId.value = qSid
    }
  },
)

watch(
  selectedSubjectId,
  () => {
    loadSubgraph()
    syncQueryFromSelection()
  },
  { flush: 'post' },
)

watch([graphPage, graphPageSize], () => {
  loadGraphBrowse()
})
</script>

<template>
  <div class="po-page graph">
    <section class="toolbar-card po-card">
      <div class="toolbar-head">
        <div>
          <h2>本体化图数据</h2>
          <p class="muted lead">
            按 <strong>Person.subject_id</strong> 区分本体对象；下图展示该中心节点经
            <code>HAS_*</code> 连出的人格特质子图（外向子图）。
          </p>
        </div>
        <div class="toolbar-actions">
          <label class="field-inline">
            <span>查阅 Person</span>
            <select
              v-model="selectedSubjectId"
              class="person-select"
              :disabled="personsLoading || !persons.length"
            >
              <option v-if="!persons.length" disabled value="">（暂无 Person 节点）</option>
              <option v-for="p in persons" :key="p.subject_id" :value="p.subject_id">
                {{ p.display_name ? `${p.display_name} · ` : '' }}{{ p.subject_id }}
              </option>
            </select>
          </label>
          <button
            type="button"
            class="po-btn po-btn--ghost"
            :disabled="personsLoading || subgraphLoading || !selectedSubjectId"
            @click="loadSubgraph"
          >
            {{ subgraphLoading ? '加载中…' : '刷新子图' }}
          </button>
        </div>
      </div>
      <p v-if="personsError" class="error">{{ personsError }}</p>
      <p v-if="subgraphError" class="error">{{ subgraphError }}</p>
    </section>

    <section class="tabs po-card">
      <div class="tab-bar" role="tablist">
        <button
          type="button"
          role="tab"
          class="tab"
          :class="{ 'tab--on': viewTab === 'ontology' }"
          :aria-selected="viewTab === 'ontology'"
          @click="viewTab = 'ontology'"
        >
          子图可视化
        </button>
        <button
          type="button"
          role="tab"
          class="tab"
          :class="{ 'tab--on': viewTab === 'browse' }"
          :aria-selected="viewTab === 'browse'"
          @click="viewTab = 'browse'"
        >
          全库节点（调试）
        </button>
      </div>

      <div v-show="viewTab === 'ontology'" class="tab-panel">
        <div v-if="!persons.length && !personsLoading" class="empty-block muted">
          库中尚无 <code>Person</code> 节点。请先在「数据导入」完成微信/聊天 JSON 写入。
        </div>
        <div v-else class="viz-wrap">
          <div class="viz-head">
            <span class="po-mono sid">{{ selectedSubjectId || '—' }}</span>
            <span v-if="subgraph?.stats" class="muted small">
              外向 facet 节点：{{ subgraph.stats.facet_node_count }} 个
            </span>
            <div class="viz-controls">
              <span class="muted small viz-zoom-label">{{ Math.round(zoomScale * 100) }}%</span>
              <button type="button" class="po-btn po-btn--ghost po-btn--sm" @click="zoomOut">缩小</button>
              <button type="button" class="po-btn po-btn--ghost po-btn--sm" @click="zoomIn">放大</button>
              <button type="button" class="po-btn po-btn--ghost po-btn--sm" @click="resetGraphViewTransform">
                重置视图
              </button>
            </div>
          </div>
          <p class="muted small viz-hint">
            滚轮缩放；在空白处按住拖拽平移画布；可拖动 Person 与各 facet 节点微调布局（仅当前会话，不写入图库）。
          </p>
          <div class="svg-scroll">
            <svg
              class="graph-svg"
              viewBox="0 0 900 520"
              xmlns="http://www.w3.org/2000/svg"
              role="img"
              :aria-label="`Person ${selectedSubjectId} 子图`"
              @wheel.prevent="onWheelSvg"
            >
              <defs>
                <marker
                  id="arrowHead"
                  markerWidth="8"
                  markerHeight="8"
                  refX="7"
                  refY="4"
                  orient="auto"
                >
                  <path d="M0,0 L8,4 L0,8 Z" fill="#94a3b8" />
                </marker>
              </defs>
              <rect width="900" height="520" fill="#f8fafc" rx="0" />
              <text x="24" y="36" class="svg-title">Person → 特质子图</text>

              <g :transform="shellTransform">
                <rect
                  width="900"
                  height="520"
                  class="viz-pan-bg"
                  fill="#ffffff"
                  fill-opacity="0"
                  @pointerdown="onPanBgDown"
                />
                <template v-if="paintLayout.person">
                  <line
                    v-for="(node, idx) in paintLayout.nodes"
                    :key="'e-' + idx"
                    pointer-events="none"
                    :x1="paintLayout.cx"
                    :y1="paintLayout.cy"
                    :x2="node.x"
                    :y2="node.y"
                    stroke="#cbd5e1"
                    stroke-width="2"
                    marker-end="url(#arrowHead)"
                  />
                  <text
                    v-for="(node, idx) in paintLayout.nodes"
                    :key="'rel-' + idx"
                    :x="node.midX"
                    :y="node.midY"
                    class="rel-label"
                    text-anchor="middle"
                  >
                    {{ node.relationship.replace('HAS_', '').slice(0, 18) }}
                  </text>

                  <g class="graph-node-person" @pointerdown="onPersonPointerDown">
                    <circle
                      :cx="paintLayout.cx"
                      :cy="paintLayout.cy"
                      r="44"
                      fill="#fef3c7"
                      stroke="#f59e0b"
                      stroke-width="3"
                    />
                    <text :x="paintLayout.cx" :y="paintLayout.cy - 6" class="node-cap" text-anchor="middle">
                      Person
                    </text>
                    <text :x="paintLayout.cx" :y="paintLayout.cy + 14" class="node-sub" text-anchor="middle">
                      {{ (paintLayout.person?.properties?.subject_id || selectedSubjectId || '—').slice(0, 22) }}
                    </text>
                  </g>

                  <g
                    v-for="(node, idx) in paintLayout.nodes"
                    :key="'n-' + idx"
                    class="graph-node-facet"
                    @pointerdown="onFacetPointerDown($event, node, idx)"
                  >
                    <circle
                      :cx="node.x"
                      :cy="node.y"
                      r="36"
                      :fill="colorForLabels(node.target_labels)"
                      stroke="#fff"
                      stroke-width="2"
                    />
                    <text :x="node.x" :y="node.y - 4" class="facet-cap" text-anchor="middle">
                      {{ (node.target_labels && node.target_labels[0]) || 'Node' }}
                    </text>
                    <text :x="node.x" :y="node.y + 12" class="facet-sub" text-anchor="middle">
                      {{ facetCaption(node) }}
                    </text>
                  </g>

                  <text
                    v-if="!paintLayout.nodes.length"
                    :x="paintLayout.cx"
                    :y="paintLayout.cy + 72"
                    class="hint-center"
                    text-anchor="middle"
                  >
                    暂无外向 facet 边（可能未跑过人格导入）
                  </text>
                </template>
              </g>
            </svg>
          </div>

          <div class="legend">
            <span class="legend-title">图例</span>
            <span v-for="(c, lb) in LABEL_COLORS" v-show="lb !== 'default'" :key="lb" class="legend-item">
              <i class="dot" :style="{ background: c }" />
              {{ lb }}
            </span>
          </div>
        </div>
      </div>

      <div v-show="viewTab === 'browse'" class="tab-panel">
        <div class="panel-head inner">
          <p class="muted small">
            分页列出全库任意标签节点（含多 Person 与其它数据）。导出人格包请至「开放接口」页按 Person 下载。
          </p>
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
            <button type="button" class="po-btn" :disabled="graphLoading" @click="loadGraphBrowse">刷新</button>
          </div>
        </div>
        <p v-if="graphError" class="error">{{ graphError }}</p>
        <div class="table-wrap">
          <table v-if="graphItems.length">
            <thead>
              <tr>
                <th>element_id</th>
                <th>labels</th>
                <th>properties</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in graphItems" :key="row.element_id">
                <td class="po-mono cell-id">{{ row.element_id }}</td>
                <td class="cell-tags">
                  <span v-for="lb in row.labels" :key="lb" class="tag">{{ lb }}</span>
                </td>
                <td class="po-mono cell-props">{{ truncateJson(row.properties) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else-if="!graphLoading" class="empty muted">暂无节点</p>
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
        <p class="muted small api-hint">
          全量接口：<code class="po-mono">{{ apiUrl('/api/v1/graph/nodes') }}</code>
        </p>
      </div>
    </section>

    <section class="po-card hint-card">
      <h3>建模提示</h3>
      <p>
        本体字段与关系类型见仓库 <code>backend/ONTOLOGY.yaml</code>。URL 查询参数
        <code>?subject=&lt;subject_id&gt;</code> 可分享当前查阅的 Person。
      </p>
    </section>
  </div>
</template>

<style scoped>
.graph {
  padding-top: 0.25rem;
}

.toolbar-card h2 {
  margin: 0 0 0.35rem;
  font-size: 1.05rem;
}

.lead {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.5;
  color: #475569;
}

.toolbar-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  align-items: flex-end;
}

.field-inline {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.78rem;
  color: #475569;
}

.person-select {
  min-width: min(92vw, 320px);
  font: inherit;
  padding: 0.45rem 0.5rem;
  border-radius: 8px;
  border: 1px solid var(--po-border, #e2e8f0);
  background: #fff;
}

.error {
  color: #b91c1c;
  font-size: 0.85rem;
  margin: 0.5rem 0 0;
}

.tabs {
  margin-top: 1rem;
  padding-top: 0.75rem;
}

.tab-bar {
  display: flex;
  gap: 0.35rem;
  border-bottom: 1px solid #e2e8f0;
  margin: 0 0 0.85rem;
}

.tab {
  font: inherit;
  cursor: pointer;
  padding: 0.45rem 0.85rem;
  border: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: #64748b;
  font-weight: 600;
  font-size: 0.84rem;
}

.tab--on {
  background: #eff6ff;
  color: #1d4ed8;
}

.tab-panel {
  min-height: 200px;
}

.empty-block {
  padding: 1.5rem 0.5rem;
  text-align: center;
  font-size: 0.88rem;
}

.viz-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.viz-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.sid {
  font-size: 0.85rem;
  font-weight: 600;
  color: #0f172a;
}

.viz-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-left: auto;
}

.viz-zoom-label {
  min-width: 3.25rem;
  text-align: right;
}

.viz-hint {
  margin: 0;
  line-height: 1.45;
}

.svg-scroll {
  overflow: auto;
  border: 1px solid var(--po-border, #e2e8f0);
  border-radius: 10px;
  background: #fff;
}

.graph-svg {
  display: block;
  width: 100%;
  min-width: 560px;
  height: auto;
  max-height: min(70vh, 560px);
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
}

.viz-pan-bg {
  cursor: grab;
}

.viz-pan-bg:active {
  cursor: grabbing;
}

.graph-node-person,
.graph-node-facet {
  cursor: move;
}

.svg-title {
  font-size: 15px;
  font-weight: 700;
  fill: #334155;
}

.rel-label {
  font-size: 10px;
  fill: #64748b;
  pointer-events: none;
}

.node-cap {
  font-size: 13px;
  font-weight: 800;
  fill: #92400e;
}

.node-sub {
  font-size: 11px;
  fill: #78350f;
}

.facet-cap {
  font-size: 10px;
  font-weight: 700;
  fill: #fff;
}

.facet-sub {
  font-size: 9px;
  fill: rgb(255 255 255 / 92%);
}

.hint-center {
  font-size: 13px;
  fill: #94a3b8;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.75rem;
  align-items: center;
  font-size: 0.72rem;
  color: #64748b;
}

.legend-title {
  font-weight: 700;
  color: #475569;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  display: inline-block;
}

.panel-head.inner {
  margin-bottom: 0.65rem;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-wrap: wrap;
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

.table-wrap {
  border: 1px solid var(--po-border, #e2e8f0);
  border-radius: 8px;
  overflow: auto;
  max-height: min(50vh, 420px);
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

.tag {
  display: inline-block;
  margin: 0 0.2rem 0.2rem 0;
  padding: 0.1rem 0.4rem;
  background: #e0e7ff;
  color: #3730a3;
  border-radius: 4px;
  font-size: 0.72rem;
}

.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 0.85rem;
}

.api-hint {
  margin: 0.75rem 0 0;
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
