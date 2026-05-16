<script setup>
import { ref, watch, computed } from 'vue'

import { apiFetch } from '@/api/http.js'

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
  { n: 1, t: '声明本体对象', d: '微信：预分析后选择本体 Person 与客体 sender；其它来源可手填 subject_id' },
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
const ingestLoading = ref(false)

const wxStatus = ref(null)
const wxStatusLoading = ref(false)
const wxStatusError = ref('')
const sessions = ref([])
const sessionsLoading = ref(false)
const sessionsError = ref('')
const selectedChat = ref('')
const wxImportLimit = ref(500)

/** 预解析：{ label, count, suggested_subject_id }[] */
const speakerRows = ref([])
const speakerMeta = ref({
  chat: '',
  message_count: 0,
  is_group: false,
  messages_probed_for_senders: 0,
  messages_raw_in_export: null,
  messages_dropped_no_body: null,
})
const previewLoading = ref(false)
const previewError = ref('')
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

/** 无上传/正文时，仅靠 wx-cli 会话入库：须已选会话且预分析完成（与底部「导入聊天 JSON」共用条件） */
const wxImportBlocked = computed(() => {
  if (!selectedChat.value.trim()) return true
  if (useManualWxFields.value) {
    return !subjectId.value.trim() || !profiledSpeakerLabel.value.trim()
  }
  if (previewLoading.value) return true
  if (!speakerRows.value.length) return true
  return !selectedProfiledLabel.value || !selectedMeLabel.value
})

/** 聊天 JSON 来源：无文件且无正文时，仅当 wx 会话路径就绪才可点「导入聊天 JSON」 */
const chatJsonPrimaryBlocked = computed(() => {
  if (!isChatJson.value) return false
  if (rawText.value.trim() || jsonFile.value) return false
  if (!selectedChat.value.trim() || !wxStatus.value?.wx_cli_enabled || !wxStatus.value?.executable_resolves) {
    return true
  }
  return wxImportBlocked.value
})

const speakerRowsForPick = computed(() => speakerRows.value.filter((r) => !r.is_session_alias))

const sourceCards = [
  {
    value: 'plain_text',
    title: '纯文本',
    body: '直接粘贴对话、自述或脱敏样例。最适合演示与快速联调。',
  },
  {
    value: 'wechat_export',
    title: '聊天 JSON',
    body: '上传 .json 或粘贴 wx-cli / 通用 messages 结构；选择本体 Person 与客体 sender 后导入 Neo4j。',
  },
  {
    value: 'other',
    title: '其他',
    body: '自定义来源占位；后续可在 ingest 中扩展 source_type。',
  },
]

function resolvedSuggestedSubjectId() {
  const row = speakerRows.value.find((r) => r.label === selectedProfiledLabel.value)
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
    messages_raw_in_export: data.messages_raw_in_export ?? null,
    messages_dropped_no_body: data.messages_dropped_no_body ?? null,
  }
  speakerRoleHint.value = data.hint || ''
  const nonAlias = speakerRows.value.filter((r) => !r.is_session_alias)
  if (data.suggested_profiled_speaker_label) {
    selectedProfiledLabel.value = data.suggested_profiled_speaker_label
  } else if (nonAlias.length === 1) {
    selectedProfiledLabel.value = nonAlias[0].label
  } else {
    selectedProfiledLabel.value = ''
  }
  selectedMeLabel.value = data.suggested_wx_me_sender_label || '(空 sender)'
  if (!subjectDisplayName.value.trim() && selectedProfiledLabel.value) {
    subjectDisplayName.value = selectedProfiledLabel.value
  }
}

const jsonFileInputRef = ref(null)

function isChatJsonSource() {
  return isChatJson.value
}

const PROBE_MESSAGE_LIMIT = 800
/** 选 wx-cli 会话后 preview-export 单次拉取条数上限（仅用于说话人预统计，与「正式导出条数」无关） */
const WX_SESSION_PREVIEW_PROBE = 500

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
        : '请在本体 Person 下拉框中选择一个说话人，或勾选「手动填写」。'
      : '请填写「本体化对象」的 subject_id（被建模的 Person 主键）。'
    return
  }
  if (isWx) {
    if (!profiledL) {
      ingestError.value = manual
        ? '请填写「本体 Person」对应的 sender（人格画像来源）。'
        : '请选择「本体 Person」（其消息用于人格画像，并决定 subject_id）。'
      return
    }
    if (!manual) {
      const nonAlias = speakerRows.value.filter((r) => !r.is_session_alias)
      if (nonAlias.length >= 2 && profiledL === meL) {
        ingestError.value = '本体 Person 与 客体 sender 须为不同说话人（私聊双方各选其一）。'
        return
      }
    }
    const raw = rawText.value.trim()
    if (!raw && !jsonFile.value) {
      const canWxSession =
        selectedChat.value.trim() &&
        wxStatus.value?.wx_cli_enabled &&
        wxStatus.value?.executable_resolves &&
        !wxImportBlocked.value
      if (canWxSession) {
        ingestLoading.value = true
        try {
          await runWxSessionIngest()
        } catch (e) {
          ingestError.value = e instanceof Error ? e.message : String(e)
        } finally {
          ingestLoading.value = false
        }
        return
      }
      let msg = '请上传 .json 聊天文件，或在正文粘贴一小段 JSON 后再点「导入聊天 JSON」。'
      if (
        selectedChat.value.trim() &&
        wxStatus.value?.wx_cli_enabled &&
        wxStatus.value?.executable_resolves &&
        wxImportBlocked.value
      ) {
        msg +=
          ' 你已选择本机 wx-cli 会话：请等待预分析完成并选定「本体 Person / 客体 sender」，或勾选「手动填写」填齐必填项。'
      }
      ingestError.value = msg
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
      speakerMeta.value = { chat: '', message_count: 0, is_group: false, messages_probed_for_senders: 0, messages_raw_in_export: null, messages_dropped_no_body: null }
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
    selectedProfiledLabel.value = ''
    selectedMeLabel.value = '(空 sender)'
    speakerRoleHint.value = ''
    previewError.value = ''
    speakerMeta.value = { chat: '', message_count: 0, is_group: false, messages_probed_for_senders: 0, messages_raw_in_export: null, messages_dropped_no_body: null }
    if ((st !== 'wechat_export' && st !== 'chat_json') || !chat || !en || !ok) return
    previewSeq += 1
    const scheduledAt = previewSeq
    previewChatTimer = setTimeout(() => runPreviewExport(chat, scheduledAt), 550)
  },
)

watch(selectedProfiledLabel, (lab) => {
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
      body: JSON.stringify({ chat, probe_limit: WX_SESSION_PREVIEW_PROBE }),
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
    if (
      selectedChat.value.trim() &&
      wxStatus.value?.wx_cli_enabled &&
      wxStatus.value?.executable_resolves &&
      speakerRows.value.length
    ) {
      previewError.value =
        '当前说话人已由 wx-cli 会话预分析得到，无需再点此按钮。若要改用粘贴 JSON，请在正文粘贴后再解析。'
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

const wxImportCap = computed(() => {
  const m = Number(wxStatus.value?.wx_chat_import_max_messages)
  if (Number.isFinite(m) && m > 0) return Math.min(500_000, Math.floor(m))
  return 100_000
})

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

/** 本机 wx-cli 选中会话 → POST /wechat/import-from-session（仅由 submitIngest 在无文件/正文时调用） */
async function runWxSessionIngest() {
  const manual = useManualWxFields.value
  const sid = manual ? subjectId.value.trim() : resolvedSuggestedSubjectId()
  const profiledL = manual ? profiledSpeakerLabel.value.trim() : resolvedProfiledFromPick()
  const meL = manual ? wxMeSpeakerLabel.value.trim() || '(空 sender)' : resolvedMeFromPick()
  if (!sid) {
    ingestError.value = manual
      ? '请填写「本体化对象」的 subject_id。'
      : '请在本体 Person 下拉框中选择一个说话人，或勾选「手动填写」。'
    return
  }
  if (!profiledL) {
    ingestError.value = manual
      ? '请填写「本体 Person」对应的 sender（人格画像来源）。'
      : '请选择「本体 Person」（写入 Person 与画像来源 sender）。'
    return
  }
  const chat = (selectedChat.value || '').trim()
  if (!chat) {
    ingestError.value = '请先在会话列表中选择一个会话（或改用手动粘贴 JSON）。'
    return
  }
  let lim = Number(wxImportLimit.value)
  if (!Number.isFinite(lim) || lim < 1) lim = 500
  lim = Math.min(wxImportCap.value, Math.floor(lim))
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
  sessions.value = []
  sessionsError.value = ''
  selectedChat.value = ''
  speakerRows.value = []
  speakerMeta.value = { chat: '', message_count: 0, is_group: false, messages_probed_for_senders: 0, messages_raw_in_export: null, messages_dropped_no_body: null }
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
          <strong>微信</strong>：选择会话或粘贴 JSON 后会<strong>预解析说话人</strong>；选择<strong>本体 Person</strong>与<strong>客体 sender</strong>，系统自动对齐
          <code>subject_id</code>、<code>profiled_speaker_label</code> 与 <code>wx_me_sender_label</code>。需要自定义主键时可勾选「手动填写」。
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
          填好下方「本体 Person / 客体 sender」后，点底部「导入聊天 JSON」上传全文入库。
          若已启用本机 wx-cli、在下方展开区选好会话并完成预分析，也可<strong>不上传文件、不粘贴正文</strong>，直接点底部「导入聊天 JSON」。
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
        <summary class="wx-cli-details__summary">本机 wx-cli（选会话预分析，入库用底部「导入聊天 JSON」）</summary>
        <section class="wx-panel wx-panel--nested">
        <h4 class="wx-h">本机 wx-cli：加载会话并预分析</h4>
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
              <span>正式导出条数 <code>wx export -n</code>（≤{{ wxImportCap }}，与底部「导入聊天 JSON」一致）</span>
              <div class="wx-limit-row">
                <input v-model.number="wxImportLimit" type="number" min="1" :max="wxImportCap" step="50" />
                <button
                  v-if="speakerMeta.message_count > 0"
                  type="button"
                  class="po-btn po-btn--ghost po-btn--sm"
                  @click="wxImportLimit = Math.min(wxImportCap, Math.max(1, Math.floor(speakerMeta.message_count)))"
                >
                  与当前预分析样本条数对齐
                </button>
              </div>
              <p class="muted small wx-limit-hint">
                与上方说话人统计里的「共 {{ speakerMeta.message_count }} 条」<strong>不是同一概念</strong>：那里是当前预解析 JSON
                里的消息数（选会话时后端单次最多向 wx 拉 {{ WX_SESSION_PREVIEW_PROBE }} 条做样本）；此处为<strong>正式入库</strong>时再导出多少条。若希望与当前样本量一致，可点右侧按钮；若要更长对话画像，可增大（不超过会话实际存量与当前上限 {{ wxImportCap }}）。超大会话可在 backend/.env 提高 <code>WX_CHAT_IMPORT_MAX_MESSAGES</code> 并适当增大 <code>WX_CLI_TIMEOUT_SEC</code>。
              </p>
            </label>
          </template>
        </template>

        <hr class="wx-hr" />
        <p class="muted small">
          选会话并填好下方说话人后，点页面底部「导入聊天 JSON」入库；或把 <code>wx export … --format json</code> 的完整结果粘贴到「JSON 正文」再导入。
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
          <span>手动填写 subject_id 与 sender 角色</span>
        </label>

        <fieldset v-if="!useManualWxFields && speakerRows.length > 0" class="subject-fieldset subject-fieldset--pick">
          <legend>本体 Person 与客体 sender（已由 JSON 预解析）</legend>
          <p v-if="speakerMeta.messages_raw_in_export != null" class="muted small wx-raw-count">
            本次预解析 JSON：<strong>原始</strong> {{ speakerMeta.messages_raw_in_export }} 条（wx-cli 导出对象里的消息条数）；
            <strong>规范化后</strong> {{ speakerMeta.message_count }} 条可参与统计（无正文如纯图片/空泡等已丢弃
            {{ speakerMeta.messages_dropped_no_body ?? 0 }} 条）。
          </p>
          <p class="muted small">
            会话「{{ speakerMeta.chat || '?' }}」在当前<strong>预解析样本</strong>中共
            {{ speakerMeta.message_count }} 条规范化消息；说话人分布统计使用前 {{ speakerMeta.messages_probed_for_senders }} 条。
            该数字表示<strong>用于说话人统计的 JSON 片段规模</strong>；若使用本机 wx-cli，展开区内的<strong>正式导出 <code>-n</code></strong>是另一参数，决定点击「导入聊天 JSON」时再向 wx 拉取多少条入库。
            <strong>本体 Person</strong>：写入 Neo4j 的 Person 锚点（<code>subject_id</code>）与其消息用于人格画像（<code>profiled_speaker_label</code>）；
            <strong>客体 sender</strong>：对话另一方在 JSON 中的 <code>sender</code>（<code>wx_me_sender_label</code>，私聊常见为「(空 sender)」）。
          </p>
          <p v-if="speakerRoleHint" class="muted small wx-hint">{{ speakerRoleHint }}</p>
          <label class="field">
            <span>本体 Person<em class="req">*</em></span>
            <select v-model="selectedProfiledLabel" class="select-input">
              <option disabled value="">请选择</option>
              <option v-for="r in speakerRowsForPick" :key="'ont-' + r.label" :value="r.label">
                {{ r.label }}（{{ r.count }} 条） — {{ r.suggested_subject_id }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>客体 sender<em class="req">*</em></span>
            <select v-model="selectedMeLabel" class="select-input">
              <option disabled value="">请选择</option>
              <option v-for="r in speakerRowsForPick" :key="'obj-' + r.label" :value="r.label">
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
            <span>本体 Person（sender，人格画像来源）</span>
            <input
              v-model="profiledSpeakerLabel"
              type="text"
              placeholder="如 (空 sender) 或对方昵称；其消息用于人格画像"
            />
          </label>
          <label class="field">
            <span>客体 sender（对话另一方在 JSON 中的标签）</span>
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
        <button
          type="button"
          class="po-btn po-btn--primary"
          :disabled="ingestLoading || (isChatJson && chatJsonPrimaryBlocked)"
          @click="submitIngest"
        >
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
        <pre class="po-mono json">{{ JSON.stringify(ingestResult, null, 2) }}</pre>
        <p v-if="ingestResult.wx_cli" class="muted small wx-ingest-counts">
          条数说明（与微信客户端「聊天信息」统计未必一致）：wx-cli 导出 JSON 内<strong>原始</strong>
          {{ ingestResult.wx_cli.messages_raw_in_export ?? '—' }} 条 → <strong>规范化后</strong>
          {{ ingestResult.wx_cli.messages_normalized_in_export ?? ingestResult.wx_cli.messages_in_file }} 条（去掉无正文
          {{ ingestResult.wx_cli.messages_dropped_no_body ?? 0 }} 条）；人格摘要管线约使用
          {{ ingestResult.wx_cli.messages_used_for_digest ?? '—' }} 条。<code>-n</code> 仅为上限，实际条数还受会话存量与
          wx-cli 行为影响。
        </p>
      </div>
    </section>

    <section v-if="isChatJson" class="po-card aside muted">
      <h3>导入说明</h3>
      <p class="small">
        入口在表单顶部「上传或粘贴」区域；填好本体 Person 与客体 sender 后，滚动到底部点「导入聊天 JSON」。
        仅使用 wx-cli 时，选好会话并预分析完成后也可不贴 JSON，直接点底部「导入聊天 JSON」。
        若出现 <code>502</code>，多为后端未启动或代理未连上 <code>127.0.0.1:8000</code>，不影响文件/粘贴导入。
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
  max-width: 100%;
}

.wx-limit-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.35rem;
}

.wx-limit-row input[type='number'] {
  max-width: 8rem;
}

.wx-limit-hint {
  margin: 0.45rem 0 0;
  line-height: 1.45;
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
