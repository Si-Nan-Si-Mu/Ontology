<script setup>
import { ref, watch, computed } from 'vue'

import { apiFetch } from '@/api/http.js'
import { downloadPersonaExport } from '@/api/personaExport.js'

/** 与 `wx export <chat>` 对齐：优先 chat，否则尝试上游返回的其它字段 */
function sessionExportChat(s) {
  if (!s || typeof s !== 'object') return ''
  const keys = ['chat', 'name', 'title', 'username']
  for (const k of keys) {
    const v = s[k]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  return ''
}

const steps = [
  { n: 1, t: '声明本体对象', d: '微信：预分析后从说话人里选 Person 与「我」；其它来源可手填 subject_id' },
  { n: 2, t: '选择来源并粘贴', d: '纯文本等；微信可本机选会话或粘贴 JSON' },
  { n: 3, t: '提交校验', d: '后端校验后返回受理信息' },
]

const sourceType = ref('plain_text')
const rawText = ref('')
const subjectId = ref('')
const subjectDisplayName = ref('')
const profiledSpeakerLabel = ref('')
const wxMeSpeakerLabel = ref('(空 sender)')
const note = ref('')
const ingestResult = ref(null)
const ingestError = ref('')
const personaExportError = ref('')
const ingestLoading = ref(false)

const wxStatus = ref(null)
const wxStatusLoading = ref(false)
const wxStatusError = ref('')
const sessions = ref([])
const sessionsLoading = ref(false)
const sessionsError = ref('')
const selectedChat = ref('')
const wxImportLimit = ref(500)
const wxImportLoading = ref(false)

/** 预解析：{ label, count, suggested_subject_id }[] */
const speakerRows = ref([])
const speakerMeta = ref({
  chat: '',
  message_count: 0,
  is_group: false,
  messages_probed_for_senders: 0,
})
const previewLoading = ref(false)
const previewError = ref('')
const selectedSubjectLabel = ref('')
const selectedProfiledLabel = ref('')
const selectedMeLabel = ref('(空 sender)')
const speakerRoleHint = ref('')
const useManualWxFields = ref(false)
const analyzeLoading = ref(false)
const jsonFile = ref(null)
const jsonFileName = ref('')
const jsonDragOver = ref(false)
const isChatJson = computed(
  () => sourceType.value === 'wechat_export' || sourceType.value === 'chat_json',
)

/** 最近一次成功写入 Neo4j 的 Person.subject_id（用于导出） */
const exportSubjectId = computed(() => {
  const r = ingestResult.value
  if (!r || typeof r !== 'object') return ''
  const sid = r.wx_cli?.person_subject_id || r.ontology_subject?.subject_id
  return typeof sid === 'string' ? sid.trim() : ''
})

const canExportPersona = computed(
  () => exportSubjectId.value && ingestResult.value?.status === 'done' && ingestResult.value?.wx_cli,
)

async function onDownloadPersonaExport(format) {
  personaExportError.value = ''
  try {
    await downloadPersonaExport(exportSubjectId.value, format)
  } catch (e) {
    personaExportError.value = e instanceof Error ? e.message : String(e)
  }
}

const PLACEHOLDER_CHAT_JSON =
  '可选：粘贴一小段 JSON（含 messages）用于补充探针；大文件请只用顶部上传，勿整包粘贴。'
const PLACEHOLDER_PLAIN_TEXT =
  '示例：\n2024-01-01 对方：最近压力有点大。\n我：要不要先把目标拆小一点？'

const rawTextPlaceholder = computed(() =>
  isChatJson.value ? PLACEHOLDER_CHAT_JSON : PLACEHOLDER_PLAIN_TEXT,
)

/** 选择会话后预分析 wx export（防抖）；AbortController 避免并发 wx 调用 */
let previewChatTimer = null
let previewAbort = null
let previewSeq = 0

/** 从 wx-cli 一键导入：需已选会话，且（预解析后选好说话人）或勾选手动填写 */
const wxImportBlocked = computed(() => {
  if (!selectedChat.value.trim()) return true
  if (wxImportLoading.value) return true
  if (useManualWxFields.value) {
    return !subjectId.value.trim() || !profiledSpeakerLabel.value.trim()
  }
  if (previewLoading.value) return true
  if (!speakerRows.value.length) return true
  return !selectedSubjectLabel.value || !selectedProfiledLabel.value
})

const sourceCards = [
  {
    value: 'plain_text',
    title: '纯文本',
    body: '直接粘贴对话、自述或脱敏样例。最适合演示与快速联调。',
  },
  {
    value: 'wechat_export',
    title: '聊天 JSON',
    body: '上传 .json 或粘贴 wx-cli / 通用 messages 结构；选择被分析对象与本机 sender 后导入 Neo4j。',
  },
  {
    value: 'other',
    title: '其他',
    body: '自定义来源占位；后续可在 ingest 中扩展 source_type。',
  },
]

function resolvedSuggestedSubjectId() {
  const row = speakerRows.value.find((r) => r.label === selectedSubjectLabel.value)
  return row?.suggested_subject_id || ''
}

function resolvedProfiledFromPick() {
  return selectedProfiledLabel.value || ''
}

function resolvedMeFromPick() {
  return selectedMeLabel.value || '(空 sender)'
}

function applySpeakerPickDefaults(data) {
  speakerRows.value = Array.isArray(data.senders) ? data.senders : []
  speakerMeta.value = {
    chat: data.chat || '',
    message_count: data.message_count || 0,
    is_group: !!data.is_group,
    messages_probed_for_senders: data.messages_probed_for_senders ?? data.message_count ?? 0,
  }
  speakerRoleHint.value = data.hint || ''
  const chatRow = speakerRows.value.find((r) => r.is_session_alias)
  if (chatRow) {
    selectedSubjectLabel.value = chatRow.label
    if (!subjectDisplayName.value.trim()) {
      subjectDisplayName.value = chatRow.label
    }
  } else if (speakerRows.value.length === 1) {
    selectedSubjectLabel.value = speakerRows.value[0].label
  } else {
    selectedSubjectLabel.value = ''
  }
  if (data.suggested_profiled_speaker_label) {
    selectedProfiledLabel.value = data.suggested_profiled_speaker_label
  } else if (speakerRows.value.length === 1) {
    selectedProfiledLabel.value = speakerRows.value[0].label
  } else {
    selectedProfiledLabel.value = ''
  }
  selectedMeLabel.value = data.suggested_wx_me_sender_label || '(空 sender)'
}

const jsonFileInputRef = ref(null)

function isChatJsonSource() {
  return isChatJson.value
}

const PROBE_MESSAGE_LIMIT = 800

async function loadJsonFile(file) {
  if (!file) return
  const name = (file.name || '').toLowerCase()
  if (!name.endsWith('.json')) {
    previewError.value = '请选择 .json 文件'
    return
  }
  previewError.value = ''
  jsonFile.value = file
  jsonFileName.value = file.name
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('probe_message_limit', String(PROBE_MESSAGE_LIMIT))
    const data = await apiFetch('/api/v1/wechat/analyze-json-file', {
      method: 'POST',
      body: fd,
    })
    applySpeakerPickDefaults(data)
    rawText.value = ''
  } catch (e) {
    jsonFile.value = null
    jsonFileName.value = ''
    previewError.value = e instanceof Error ? e.message : String(e)
  }
}

function onJsonFileChange(ev) {
  const file = ev.target?.files?.[0]
  loadJsonFile(file)
  if (ev.target) ev.target.value = ''
}

function onJsonDrop(ev) {
  ev.preventDefault()
  jsonDragOver.value = false
  const file = ev.dataTransfer?.files?.[0]
  loadJsonFile(file)
}

function onJsonDragOver(ev) {
  ev.preventDefault()
  jsonDragOver.value = true
}

function onJsonDragLeave() {
  jsonDragOver.value = false
}

function pickJsonFile() {
  jsonFileInputRef.value?.click()
}

function clearJsonFile() {
  jsonFile.value = null
  jsonFileName.value = ''
}

async function submitIngest() {
  ingestError.value = ''
  personaExportError.value = ''
  ingestResult.value = null
  const isWx = isChatJsonSource()
  const manual = isWx && useManualWxFields.value
  const sid = isWx ? (manual ? subjectId.value.trim() : resolvedSuggestedSubjectId()) : subjectId.value.trim()
  const profiledL = isWx
    ? manual
      ? profiledSpeakerLabel.value.trim()
      : resolvedProfiledFromPick()
    : profiledSpeakerLabel.value.trim() || null
  const meL = isWx
    ? manual
      ? wxMeSpeakerLabel.value.trim() || '(空 sender)'
      : resolvedMeFromPick()
    : null
  if (!sid) {
    ingestError.value = isWx
      ? manual
        ? '请填写「本体化对象」的 subject_id（被建模的 Person 主键）。'
        : '请在本体化 Person 下拉框中选择一个说话人，或勾选「手动填写」。'
      : '请填写「本体化对象」的 subject_id（被建模的 Person 主键）。'
    return
  }
  if (isWx) {
    if (!profiledL) {
      ingestError.value = manual
        ? '微信导入须填写「被分析对象 sender」，其消息将用于人格画像。'
        : '请在「被分析对象」中选择一个说话人，或勾选「手动填写」。'
      return
    }
    const raw = rawText.value.trim()
    if (!raw && !jsonFile.value) {
      ingestError.value = '请上传 .json 聊天文件，或在正文粘贴一小段 JSON 做探针后再解析。'
      return
    }
    if (raw && !raw.startsWith('{') && !raw.startsWith('[')) {
      ingestError.value = '聊天 JSON 须以 { 或 [ 开头。'
      return
    }
  }
  ingestLoading.value = true
  try {
    if (isWx && jsonFile.value) {
      const fd = new FormData()
      fd.append('file', jsonFile.value)
      fd.append('subject_id', sid)
      fd.append('profiled_speaker_label', profiledL)
      fd.append('wx_me_sender_label', meL || '(空 sender)')
      const dn = subjectDisplayName.value.trim()
      if (dn) fd.append('subject_display_name', dn)
      const nt = note.value.trim()
      if (nt) fd.append('note', nt)
      ingestResult.value = await apiFetch('/api/v1/ingest/chat-json', {
        method: 'POST',
        body: fd,
      })
      return
    }
    ingestResult.value = await apiFetch('/api/v1/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subject_id: sid,
        subject_display_name: subjectDisplayName.value.trim() || null,
        profiled_speaker_label: profiledL,
        wx_me_sender_label: meL,
        self_speaker_label: profiledL,
        source_type: isWx ? 'chat_json' : sourceType.value,
        raw_text: rawText.value || null,
        note: note.value.trim() || null,
      }),
    })
  } catch (e) {
    ingestError.value = e instanceof Error ? e.message : String(e)
  } finally {
    ingestLoading.value = false
  }
}

watch(
  () => sourceType.value,
  (t) => {
    if (t === 'wechat_export' || t === 'chat_json') {
      loadWxStatus()
    } else {
      speakerRows.value = []
      speakerMeta.value = { chat: '', message_count: 0, is_group: false, messages_probed_for_senders: 0 }
      selectedSubjectLabel.value = ''
      selectedProfiledLabel.value = ''
      selectedMeLabel.value = '(空 sender)'
      speakerRoleHint.value = ''
      previewError.value = ''
      useManualWxFields.value = false
    }
  },
  { immediate: true },
)

watch(
  () => [
    sourceType.value,
    selectedChat.value,
    wxStatus.value?.wx_cli_enabled,
    wxStatus.value?.executable_resolves,
  ],
  () => {
    clearTimeout(previewChatTimer)
    previewAbort?.abort()
    const st = sourceType.value
    const chat = selectedChat.value
    const en = wxStatus.value?.wx_cli_enabled
    const ok = wxStatus.value?.executable_resolves
    speakerRows.value = []
    selectedSubjectLabel.value = ''
    selectedProfiledLabel.value = ''
    selectedMeLabel.value = '(空 sender)'
    speakerRoleHint.value = ''
    previewError.value = ''
    speakerMeta.value = { chat: '', message_count: 0, is_group: false, messages_probed_for_senders: 0 }
    if ((st !== 'wechat_export' && st !== 'chat_json') || !chat || !en || !ok) return
    previewSeq += 1
    const scheduledAt = previewSeq
    previewChatTimer = setTimeout(() => runPreviewExport(chat, scheduledAt), 550)
  },
)

watch(selectedSubjectLabel, (lab) => {
  if ((sourceType.value !== 'wechat_export' && sourceType.value !== 'chat_json') || useManualWxFields.value) return
  if (lab && !subjectDisplayName.value.trim()) {
    subjectDisplayName.value = lab
  }
})

async function runPreviewExport(chat, scheduledAt) {
  if (scheduledAt !== previewSeq) return
  previewAbort?.abort()
  const ac = new AbortController()
  previewAbort = ac
  previewLoading.value = true
  previewError.value = ''
  try {
    const data = await apiFetch('/api/v1/wechat/preview-export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat, probe_limit: 500 }),
      signal: ac.signal,
    })
    if (scheduledAt !== previewSeq) return
    applySpeakerPickDefaults(data)
  } catch (e) {
    const aborted =
      (typeof DOMException !== 'undefined' && e instanceof DOMException && e.name === 'AbortError') ||
      (e instanceof Error && e.name === 'AbortError')
    if (aborted) return
    if (scheduledAt !== previewSeq) return
    speakerRows.value = []
    previewError.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (scheduledAt === previewSeq) {
      previewLoading.value = false
    }
  }
}

async function analyzeJsonSpeakers() {
  let raw = rawText.value.trim()
  if (!raw) {
    if (jsonFile.value) {
      await loadJsonFile(jsonFile.value)
      return
    }
    previewError.value = '请粘贴一小段聊天 JSON（含 messages），或先上传 .json 文件完成探针。'
    return
  }
  if (!raw.startsWith('{') && !raw.startsWith('[')) {
    previewError.value = '请粘贴以 { 或 [ 开头的聊天 JSON。'
    return
  }
  analyzeLoading.value = true
  previewError.value = ''
  try {
    const data = await apiFetch('/api/v1/wechat/analyze-json', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_text: raw, probe_message_limit: PROBE_MESSAGE_LIMIT }),
    })
    applySpeakerPickDefaults(data)
  } catch (e) {
    speakerRows.value = []
    previewError.value = e instanceof Error ? e.message : String(e)
  } finally {
    analyzeLoading.value = false
  }
}


async function loadWxStatus() {
  wxStatusError.value = ''
  wxStatusLoading.value = true
  try {
    wxStatus.value = await apiFetch('/api/v1/wechat/status')
  } catch (e) {
    wxStatus.value = null
    wxStatusError.value = e instanceof Error ? e.message : String(e)
  } finally {
    wxStatusLoading.value = false
  }
}

async function loadSessions() {
  sessionsError.value = ''
  sessionsLoading.value = true
  try {
    const data = await apiFetch('/api/v1/wechat/sessions?limit=50')
    sessions.value = Array.isArray(data.sessions) ? data.sessions : []
    selectedChat.value = ''
  } catch (e) {
    sessions.value = []
    selectedChat.value = ''
    sessionsError.value = e instanceof Error ? e.message : String(e)
  } finally {
    sessionsLoading.value = false
  }
}

async function submitWxImport() {
  ingestError.value = ''
  personaExportError.value = ''
  ingestResult.value = null
  const manual = useManualWxFields.value
  const sid = manual ? subjectId.value.trim() : resolvedSuggestedSubjectId()
  const profiledL = manual ? profiledSpeakerLabel.value.trim() : resolvedProfiledFromPick()
  const meL = manual ? wxMeSpeakerLabel.value.trim() || '(空 sender)' : resolvedMeFromPick()
  if (!sid) {
    ingestError.value = manual
      ? '请填写「本体化对象」的 subject_id。'
      : '请在本体化 Person 下拉框中选择一个说话人，或勾选「手动填写」。'
    return
  }
  if (!profiledL) {
    ingestError.value = manual
      ? '请填写「被分析对象 sender」。'
      : '请在「被分析对象」中选择一个说话人，或勾选「手动填写」。'
    return
  }
  const chat = (selectedChat.value || '').trim()
  if (!chat) {
    ingestError.value = '请先在会话列表中选择一个会话（或改用手动粘贴 JSON）。'
    return
  }
  let lim = Number(wxImportLimit.value)
  if (!Number.isFinite(lim) || lim < 1) lim = 500
  lim = Math.min(8000, Math.floor(lim))
  wxImportLoading.value = true
  try {
    ingestResult.value = await apiFetch('/api/v1/wechat/import-from-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subject_id: sid,
        subject_display_name: subjectDisplayName.value.trim() || null,
        profiled_speaker_label: profiledL,
        wx_me_sender_label: meL,
        self_speaker_label: profiledL,
        chat,
        limit: lim,
        note: note.value.trim() || null,
      }),
    })
  } catch (e) {
    ingestError.value = e instanceof Error ? e.message : String(e)
  } finally {
    wxImportLoading.value = false
  }
}

function clearDraft() {
  rawText.value = ''
  subjectId.value = ''
  subjectDisplayName.value = ''
  jsonFile.value = null
  jsonFileName.value = ''
  jsonDragOver.value = false
  profiledSpeakerLabel.value = ''
  wxMeSpeakerLabel.value = '(空 sender)'
  note.value = ''
  ingestResult.value = null
  ingestError.value = ''
  personaExportError.value = ''
  sessions.value = []
  sessionsError.value = ''
  selectedChat.value = ''
  speakerRows.value = []
  speakerMeta.value = { chat: '', message_count: 0, is_group: false }
  selectedSubjectLabel.value = ''
  selectedProfiledLabel.value = ''
  selectedMeLabel.value = '(空 sender)'
  speakerRoleHint.value = ''
  previewError.value = ''
  useManualWxFields.value = false
}
</script>

<template>
  <div class="po-page import">
    <section class="intro po-card">
      <h2>导入流水线（原型）</h2>
      <p>
        本页把<strong>文本 / 微信 wx-cli JSON</strong>送入后端 <code>ingest</code>。<strong>微信导出</strong>会生成
        <strong>Person + 特质子图</strong>（摘要、表达风格、口癖、MBTI 占位、典型对话等节点及关系）；纯文本等其它来源当前仍为占位响应（不落库）。
      </p>
      <ul class="bullets">
        <li>
          <strong>微信</strong>：选择会话或粘贴 JSON 后会<strong>预解析说话人</strong>；从列表中选择「本体化 Person」与「对话中的我」，系统自动对齐
          <code>subject_id</code> 与 <code>sender</code>。需要自定义主键时可勾选「手动填写」。
        </li>
        <li>
          <strong>其它来源</strong>：仍须手填 <code>subject_id</code> 作为 <code>Person</code> 锚点；聊天中的对方将映射为
          <code>Agent</code>。
        </li>
        <li>仅处理本人或已授权数据；演示请使用虚构内容。</li>
        <li>大段文本建议先本地脱敏（手机号、证件号等）。</li>
        <li>本机一键导入需 <code>WX_CLI_ENABLED=true</code>，且勿将 API 暴露在公网（见 docs/WECHAT_WX_CLI.md）。</li>
      </ul>
    </section>

    <section class="steps po-card">
      <h3>推荐流程</h3>
      <ol class="step-list">
        <li v-for="s in steps" :key="s.n">
          <span class="step-n">{{ s.n }}</span>
          <div>
            <strong>{{ s.t }}</strong>
            <p>{{ s.d }}</p>
          </div>
        </li>
      </ol>
    </section>

    <section class="po-card form-block">
      <h3>来源与载荷</h3>
      <div class="cards">
        <button
          v-for="c in sourceCards"
          :key="c.value"
          type="button"
          class="src-card"
          :class="{ 'src-card--on': sourceType === c.value }"
          @click="sourceType = c.value"
        >
          <span class="src-title">{{ c.title }}</span>
          <span class="src-body">{{ c.body }}</span>
        </button>
      </div>

      <!-- 导入入口置顶：避免 wx-cli 502/长表格把「上传 / 导入」顶出首屏 -->
      <div v-if="isChatJson" class="chat-json-entry">
        <h4 class="chat-json-entry__title">导入入口：上传或粘贴聊天 JSON</h4>
        <p class="muted small chat-json-entry__hint">
          选择 <code>.json</code> 或拖拽到下方：仅在服务端读取，用前 {{ PROBE_MESSAGE_LIMIT }} 条消息推断说话人，<strong>不会</strong>把整文件填入正文框。
          填好下方「本体化」与说话人后，点底部「导入聊天 JSON」上传全文入库。
        </p>
        <div class="json-upload">
          <input
            ref="jsonFileInputRef"
            type="file"
            accept=".json,application/json"
            class="json-upload__input"
            @change="onJsonFileChange"
          />
          <div
            class="json-upload__zone"
            :class="{ 'json-upload__zone--over': jsonDragOver }"
            role="button"
            tabindex="0"
            @dragover="onJsonDragOver"
            @dragleave="onJsonDragLeave"
            @drop="onJsonDrop"
            @click="pickJsonFile"
            @keydown.enter.prevent="pickJsonFile"
          >
            <p class="json-upload__title">点击或拖拽上传 <code>.json</code></p>
            <p class="muted small">
              支持 wx-cli、<code>messages</code> 数组；兼容 <code>content</code> / <code>text</code> / <code>sender</code>。
            </p>
            <p v-if="jsonFileName" class="json-upload__name po-mono">{{ jsonFileName }}</p>
            <button
              v-if="jsonFileName"
              type="button"
              class="po-btn po-btn--ghost po-btn--sm"
              @click.stop="clearJsonFile"
            >
              清除文件
            </button>
          </div>
        </div>
      </div>

      <details v-if="isChatJson" class="wx-cli-details">
        <summary class="wx-cli-details__summary">本机 wx-cli 一键导出（可选，需后端开启且本机已装 wx）</summary>
        <section class="wx-panel wx-panel--nested">
        <h4 class="wx-h">本机 wx-cli：选择会话并导入</h4>
        <p v-if="wxStatusLoading" class="muted small">正在检测本机 wx-cli 状态…</p>
        <p v-else-if="wxStatusError" class="error small">{{ wxStatusError }}</p>
        <template v-else-if="wxStatus">
          <p v-if="!wxStatus.wx_cli_enabled" class="muted small">
            后端未开启微信直连（<code>WX_CLI_ENABLED</code>）。可在 <code>backend/.env</code> 设为
            <code>true</code> 后重启 API；或改用手动粘贴 JSON。
          </p>
          <template v-else>
            <p v-if="!wxStatus.executable_resolves" class="error small">
              未在 PATH 找到可执行文件「{{ wxStatus.wx_cli_command }}」。请安装 wx-cli 或设置
              <code>WX_CLI_COMMAND</code> 为绝对路径。
            </p>
            <p v-else class="muted small">
              已启用：命令 <code class="po-mono">{{ wxStatus.wx_cli_command }}</code>，超时
              {{ wxStatus.wx_cli_timeout_sec }}s。请保持微信已登录。
            </p>
            <div class="wx-actions">
              <button
                type="button"
                class="po-btn po-btn--ghost po-btn--sm"
                :disabled="sessionsLoading || !wxStatus.executable_resolves"
                @click="loadSessions"
              >
                {{ sessionsLoading ? '加载中…' : '加载会话列表' }}
              </button>
            </div>
            <p v-if="sessionsError" class="error small">{{ sessionsError }}</p>
            <div v-if="sessions.length" class="wx-table-wrap">
              <table class="wx-table">
                <thead>
                  <tr>
                    <th class="col-radio" />
                    <th>导出用 chat</th>
                    <th>群</th>
                    <th>摘要</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(s, idx) in sessions" :key="`${sessionExportChat(s)}-${idx}`">
                    <td>
                      <input
                        v-model="selectedChat"
                        type="radio"
                        :value="sessionExportChat(s)"
                        :disabled="!sessionExportChat(s)"
                      />
                    </td>
                    <td class="po-mono">{{ sessionExportChat(s) || '—' }}</td>
                    <td>{{ s.is_group ? '是' : '否' }}</td>
                    <td class="wx-sum">{{ typeof s.summary === 'string' ? s.summary : '' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="selectedChat && previewLoading" class="muted small">正在预分析该会话的说话人（样本）…</p>
            <label v-if="sessions.length" class="field wx-limit">
              <span>导出条数（<code>-n</code>，≤8000）</span>
              <input v-model.number="wxImportLimit" type="number" min="1" max="8000" step="50" />
            </label>
            <div v-if="sessions.length" class="actions wx-import-actions">
              <button
                type="button"
                class="po-btn po-btn--primary"
                :disabled="wxImportBlocked"
                @click="submitWxImport"
              >
                {{ wxImportLoading ? '导出并导入中…' : '从 wx-cli 导出并导入' }}
              </button>
            </div>
          </template>
        </template>

        <hr class="wx-hr" />
        <p class="muted small">
          亦可在此展开后选会话导出；或继续用下方「JSON 正文」粘贴 <code>wx export … --format json</code> 的完整结果。
        </p>
        </section>
      </details>

      <template v-if="isChatJson">
        <p v-if="previewLoading || analyzeLoading" class="muted small wx-wait">
          {{ analyzeLoading ? '正在解析正文 JSON…' : '正在预分析会话说话人…' }}
        </p>
        <p v-if="previewError" class="error small">{{ previewError }}</p>

        <label class="field field--row">
          <input v-model="useManualWxFields" type="checkbox" />
          <span>手动填写 subject_id 与被分析 sender</span>
        </label>

        <fieldset v-if="!useManualWxFields && speakerRows.length > 0" class="subject-fieldset subject-fieldset--pick">
          <legend>本体化与说话人（已由 JSON 预解析）</legend>
          <p class="muted small">
            会话「{{ speakerMeta.chat || '?' }}」共 {{ speakerMeta.message_count }} 条有效消息；
            说话人统计使用前 {{ speakerMeta.messages_probed_for_senders }} 条探针样本。
            <strong>被分析对象</strong>的消息用于人格画像；<strong>本机微信</strong>为另一方（wx-cli 私聊多为「(空 sender)」）。
          </p>
          <p v-if="speakerRoleHint" class="muted small wx-hint">{{ speakerRoleHint }}</p>
          <label class="field">
            <span>本体化 Person（subject_id 锚点）<em class="req">*</em></span>
            <select v-model="selectedSubjectLabel" class="select-input">
              <option disabled value="">请选择</option>
              <option v-for="r in speakerRows" :key="'sub-' + r.label" :value="r.label">
                {{ r.is_session_alias ? '会话名：' : '' }}{{ r.label }}（{{ r.count }} 条） — {{ r.suggested_subject_id }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>被分析对象（人格画像，须与 sender 一致）<em class="req">*</em></span>
            <select v-model="selectedProfiledLabel" class="select-input">
              <option disabled value="">请选择</option>
              <option v-for="r in speakerRows.filter((x) => !x.is_session_alias)" :key="'prof-' + r.label" :value="r.label">
                {{ r.label }}（{{ r.count }} 条）
              </option>
            </select>
          </label>
          <label class="field">
            <span>本机微信 sender（通常为 (空 sender)）</span>
            <select v-model="selectedMeLabel" class="select-input">
              <option v-for="r in speakerRows.filter((x) => !x.is_session_alias)" :key="'me-' + r.label" :value="r.label">
                {{ r.label }}（{{ r.count }} 条）
              </option>
            </select>
          </label>
          <p v-if="resolvedSuggestedSubjectId()" class="muted small">
            将使用的 <code>subject_id</code>：<span class="po-mono">{{ resolvedSuggestedSubjectId() }}</span>
          </p>
        </fieldset>

        <fieldset v-else class="subject-fieldset">
          <legend>本体化对象（{{ useManualWxFields ? '手动' : '等待预分析或手动' }}）</legend>
          <p v-if="!useManualWxFields && !speakerRows.length" class="muted small sub-hint">
            上传顶部 JSON 文件或粘贴正文后，点击下方「解析 JSON 中的说话人」。
          </p>
          <label class="field">
            <span>subject_id <em class="req">*</em></span>
            <input
              v-model="subjectId"
              type="text"
              required
              autocomplete="off"
              placeholder="如 uuid 或业务用户 ID，与 Neo4j Person.subject_id 对齐"
            />
          </label>
          <label class="field">
            <span>展示名（可选）</span>
            <input
              v-model="subjectDisplayName"
              type="text"
              placeholder="Person.display_name，如「演示用户 A」"
            />
          </label>
          <label class="field">
            <span>被分析对象 sender（微信必填）</span>
            <input
              v-model="profiledSpeakerLabel"
              type="text"
              placeholder="如 (空 sender) 或对方昵称；其消息用于人格画像"
            />
          </label>
          <label class="field">
            <span>本机微信 sender</span>
            <input
              v-model="wxMeSpeakerLabel"
              type="text"
              placeholder="wx-cli 私聊多为 (空 sender)"
            />
          </label>
        </fieldset>
      </template>

      <fieldset v-else class="subject-fieldset">
        <legend>本体化对象（必填）</legend>
        <label class="field">
          <span>subject_id <em class="req">*</em></span>
          <input
            v-model="subjectId"
            type="text"
            required
            autocomplete="off"
            placeholder="如 uuid 或业务用户 ID，与 Neo4j Person.subject_id 对齐"
          />
        </label>
        <label class="field">
          <span>展示名（可选）</span>
          <input
            v-model="subjectDisplayName"
            type="text"
            placeholder="Person.display_name，如「演示用户 A」"
          />
        </label>
        <label class="field">
          <span>对话中「自己」的标签（可选）</span>
          <input
            v-model="profiledSpeakerLabel"
            type="text"
            placeholder="可选"
          />
        </label>
      </fieldset>

      <label class="field">
        <span>备注（可选）</span>
        <input v-model="note" type="text" placeholder="个案编号、批次说明等" />
      </label>

      <label class="field">
        <span>{{ isChatJson ? 'JSON 正文（上传后可编辑预览；亦可仅用顶部上传区）' : '正文' }}</span>
        <textarea
          v-model="rawText"
          rows="14"
          :placeholder="rawTextPlaceholder"
          spellcheck="false"
        />
      </label>

      <div v-if="isChatJson" class="wx-json-actions">
        <button
          type="button"
          class="po-btn po-btn--ghost po-btn--sm"
          :disabled="analyzeLoading"
          @click="analyzeJsonSpeakers"
        >
          {{ analyzeLoading ? '解析中…' : '解析 JSON 中的说话人' }}
        </button>
      </div>

      <div class="actions" :class="{ 'actions--sticky-chat': isChatJson }">
        <button type="button" class="po-btn po-btn--primary" :disabled="ingestLoading" @click="submitIngest">
          {{
            ingestLoading
              ? '提交中…'
              : isChatJson
                ? '导入聊天 JSON'
                : '提交到 /api/v1/ingest'
          }}
        </button>
        <button type="button" class="po-btn po-btn--ghost" :disabled="ingestLoading" @click="clearDraft">
          清空草稿
        </button>
      </div>

      <p v-if="ingestError" class="error">{{ ingestError }}</p>
      <div v-if="ingestResult" class="result">
        <h4>响应 JSON</h4>
        <div v-if="canExportPersona" class="export-persona">
          <span class="muted small">导出当前 Neo4j 人格子图（非原始聊天 JSON）：</span>
          <button
            type="button"
            class="po-btn po-btn--ghost po-btn--sm"
            @click="onDownloadPersonaExport('json')"
          >
            下载 JSON
          </button>
          <button
            type="button"
            class="po-btn po-btn--ghost po-btn--sm"
            @click="onDownloadPersonaExport('text')"
          >
            下载纯文本
          </button>
        </div>
        <p v-if="personaExportError" class="error small">{{ personaExportError }}</p>
        <pre class="po-mono json">{{ JSON.stringify(ingestResult, null, 2) }}</pre>
      </div>
    </section>

    <section v-if="isChatJson" class="po-card aside muted">
      <h3>导入说明</h3>
      <p class="small">
        入口在表单顶部「上传或粘贴」区域；填好本体化与说话人后，滚动到底部点「导入聊天 JSON」。若出现
        <code>502</code>，多为后端未启动或代理未连上 <code>127.0.0.1:8000</code>，不影响文件/粘贴导入。
      </p>
    </section>

    <section v-else class="po-card aside muted">
      <h3>提示</h3>
      <p class="small">纯文本等来源当前为占位；微信人格导入请选「聊天 JSON」卡片。</p>
    </section>
  </div>
</template>

<style scoped>
.import {
  padding-top: 0.25rem;
}

.intro h2 {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
}

.intro p {
  margin: 0 0 0.75rem;
  line-height: 1.55;
  font-size: 0.9rem;
  color: #334155;
}

.bullets {
  margin: 0;
  padding-left: 1.1rem;
  font-size: 0.84rem;
  color: #475569;
  line-height: 1.55;
}

.steps {
  margin-top: 1rem;
}

.steps h3 {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
}

.step-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.step-list li {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.65rem;
  align-items: start;
  padding: 0.5rem 0;
  border-bottom: 1px solid #f1f5f9;
}

.step-list li:last-child {
  border-bottom: none;
}

.step-n {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: #e0e7ff;
  color: #312e81;
  font-weight: 700;
  font-size: 0.8rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-list strong {
  font-size: 0.88rem;
}

.step-list p {
  margin: 0.2rem 0 0;
  font-size: 0.8rem;
  color: var(--po-muted, #64748b);
}

.chat-json-entry {
  margin: 0 0 1rem;
  padding: 0.85rem 1rem;
  border: 1px solid #bae6fd;
  border-radius: 10px;
  background: #f0f9ff;
}

.chat-json-entry__title {
  margin: 0 0 0.35rem;
  font-size: 0.95rem;
  color: #0c4a6e;
}

.chat-json-entry__hint {
  margin: 0 0 0.65rem;
}

.wx-cli-details {
  margin: 0 0 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}

.wx-cli-details__summary {
  cursor: pointer;
  padding: 0.65rem 0.85rem;
  font-size: 0.88rem;
  font-weight: 600;
  color: #334155;
  list-style: none;
}

.wx-cli-details__summary::-webkit-details-marker {
  display: none;
}

.wx-panel--nested {
  margin: 0;
  padding: 0 0.85rem 0.85rem;
  border: none;
}

.actions--sticky-chat {
  position: sticky;
  bottom: 0;
  z-index: 8;
  margin-top: 0.75rem;
  padding: 0.75rem 0;
  background: linear-gradient(to top, #f8fafc 85%, transparent);
  border-top: 1px solid #e2e8f0;
  box-shadow: 0 -6px 16px rgba(15, 23, 42, 0.06);
}

.form-block {
  margin-top: 1rem;
}

.form-block h3 {
  margin: 0 0 0.85rem;
  font-size: 0.95rem;
}

.cards {
  display: grid;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

@media (min-width: 720px) {
  .cards {
    grid-template-columns: repeat(3, 1fr);
  }
}

.subject-fieldset {
  margin: 0 0 1rem;
  padding: 0.85rem 1rem 0.25rem;
  border: 1px solid #e0e7ff;
  border-radius: 10px;
  background: #fafbff;
}

.subject-fieldset legend {
  font-size: 0.82rem;
  font-weight: 650;
  color: #312e81;
  padding: 0 0.35rem;
}

.req {
  color: #b91c1c;
  font-style: normal;
  font-weight: 700;
}

.src-card {
  text-align: left;
  border: 1px solid var(--po-border, #e2e8f0);
  border-radius: 10px;
  padding: 0.65rem 0.75rem;
  background: #f8fafc;
  cursor: pointer;
  font: inherit;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  transition:
    border-color 0.15s,
    background 0.15s;
}

.src-card:hover {
  border-color: #cbd5e1;
}

.src-card--on {
  border-color: #3b82f6;
  background: #eff6ff;
}

.src-title {
  font-weight: 650;
  font-size: 0.85rem;
  color: #1e293b;
}

.src-body {
  font-size: 0.76rem;
  color: #64748b;
  line-height: 1.45;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-bottom: 0.85rem;
}

.field--row {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
}

.field--row span {
  font-size: 0.82rem;
  color: #475569;
}

.select-input {
  font: inherit;
  border: 1px solid var(--po-border, #e2e8f0);
  border-radius: 8px;
  padding: 0.45rem 0.55rem;
  background: #fff;
  max-width: 100%;
}

.subject-fieldset--pick {
  border-color: #bfdbfe;
  background: #f0f9ff;
}

.sub-hint {
  margin: 0 0 0.5rem;
}

.wx-json-actions {
  margin: -0.25rem 0 0.75rem;
}

.json-upload {
  margin-bottom: 0.85rem;
}

.json-upload__input {
  display: none;
}

.json-upload__zone {
  border: 1px dashed #94a3b8;
  border-radius: 10px;
  padding: 1rem 1.1rem;
  background: #f8fafc;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.json-upload__zone--over {
  border-color: #3b82f6;
  background: #eff6ff;
}

.json-upload__title {
  margin: 0 0 0.35rem;
  font-size: 0.92rem;
  font-weight: 600;
  color: #1e293b;
}

.json-upload__name {
  margin: 0.5rem 0 0;
  font-size: 0.82rem;
  color: #0f172a;
}

.wx-wait {
  margin: 0 0 0.35rem;
}

.field span {
  font-size: 0.82rem;
  font-weight: 500;
  color: #475569;
}

input,
textarea {
  font: inherit;
  border: 1px solid var(--po-border, #e2e8f0);
  border-radius: 8px;
  padding: 0.5rem 0.6rem;
  background: #fff;
}

textarea {
  resize: vertical;
  min-height: 220px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.25rem;
}

.error {
  color: #b91c1c;
  font-size: 0.85rem;
  margin-top: 0.75rem;
}

.result {
  margin-top: 1rem;
}

.result h4 {
  margin: 0 0 0.35rem;
  font-size: 0.82rem;
  color: #475569;
}

.export-persona {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.5rem;
}

.json {
  margin: 0;
  padding: 0.85rem;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 0.78rem;
  overflow: auto;
  max-height: 240px;
}

.aside {
  margin-top: 1rem;
}

.aside h3 {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
}

.aside .muted {
  margin: 0 0 0.65rem;
  font-size: 0.82rem;
  line-height: 1.45;
  color: var(--po-muted, #64748b);
}

.aside code {
  font-size: 0.78rem;
  background: #f1f5f9;
  padding: 0.1rem 0.25rem;
  border-radius: 4px;
}

.file-mock {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  color: #94a3b8;
  font-size: 0.82rem;
}

.muted.small,
.error.small {
  font-size: 0.8rem;
  margin: 0.35rem 0;
}

.wx-panel {
  margin: 0 0 1rem;
  padding: 0.85rem 1rem;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fafc;
}

.wx-h {
  margin: 0 0 0.5rem;
  font-size: 0.88rem;
  color: #1e3a5f;
}

.wx-actions {
  margin: 0.5rem 0 0.25rem;
}

.wx-table-wrap {
  margin-top: 0.65rem;
  max-height: 280px;
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.wx-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;
}

.wx-table th,
.wx-table td {
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid #f1f5f9;
  text-align: left;
  vertical-align: top;
}

.wx-table th {
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
}

.col-radio {
  width: 2rem;
}

.wx-sum {
  color: #64748b;
  max-width: 14rem;
  word-break: break-word;
}

.wx-limit {
  margin-top: 0.75rem;
  max-width: 12rem;
}

.wx-import-actions {
  margin-top: 0.5rem;
}

.wx-hr {
  margin: 0.85rem 0;
  border: none;
  border-top: 1px dashed #cbd5e1;
}

.po-btn--sm {
  font-size: 0.8rem;
  padding: 0.35rem 0.65rem;
}
</style>
