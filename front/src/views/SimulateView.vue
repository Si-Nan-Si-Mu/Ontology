<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { apiFetch } from '@/api/http.js'
import PoLoading from '@/components/PoLoading.vue'
import PoLoadingOverlay from '@/components/PoLoadingOverlay.vue'

const route = useRoute()
const router = useRouter()

const persons = ref([])
const personsLoading = ref(false)
const personsError = ref('')
const selectedSubjectId = ref('')
const deepseekOk = ref(null)

const scenario = ref('')
const inputText = ref('')
const sending = ref(false)
const sendError = ref('')

/** @type {import('vue').Ref<Array<{role:'user'|'assistant', content:string, meta?:object}>>} */
const turns = ref([])

const canSend = computed(
  () =>
    selectedSubjectId.value.trim() &&
    inputText.value.trim() &&
    deepseekOk.value === true &&
    !sending.value,
)

async function loadPersons() {
  personsLoading.value = true
  personsError.value = ''
  try {
    const data = await apiFetch('/api/v1/persons')
    persons.value = Array.isArray(data.items) ? data.items : []
    const q = (route.query.subject_id || '').trim()
    if (q && persons.value.some((p) => p.subject_id === q)) {
      selectedSubjectId.value = q
    } else if (!selectedSubjectId.value && persons.value.length === 1) {
      selectedSubjectId.value = persons.value[0].subject_id
    }
  } catch (e) {
    persons.value = []
    personsError.value = e instanceof Error ? e.message : String(e)
  } finally {
    personsLoading.value = false
  }
}

async function loadStatus() {
  try {
    const data = await apiFetch('/api/v1/simulate/status')
    deepseekOk.value = !!data.deepseek_configured
  } catch {
    deepseekOk.value = false
  }
}

function onPersonChange() {
  turns.value = []
  sendError.value = ''
  const sid = selectedSubjectId.value.trim()
  if (sid) {
    router.replace({ query: { ...route.query, subject_id: sid } })
  }
}

async function sendMessage() {
  const sid = selectedSubjectId.value.trim()
  const msg = inputText.value.trim()
  if (!sid || !msg || sending.value) return

  turns.value.push({ role: 'user', content: msg })
  inputText.value = ''
  sending.value = true
  sendError.value = ''

  const history = turns.value.slice(0, -1).map((t) => ({
    role: t.role,
    content: t.content,
  }))

  try {
    const data = await apiFetch(`/api/v1/person/${encodeURIComponent(sid)}/simulate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_message: msg,
        scenario: scenario.value.trim() || null,
        history,
      }),
    })
    turns.value.push({
      role: 'assistant',
      content: data.reply || '（无回复）',
      meta: {
        style_cues_used: data.style_cues_used,
        graph_facts_used: data.graph_facts_used,
        out_of_graph_note: data.out_of_graph_note,
        confidence_0_1: data.confidence_0_1,
        disclaimer_zh: data.disclaimer_zh,
      },
    })
  } catch (e) {
    sendError.value = e instanceof Error ? e.message : String(e)
    turns.value.pop()
    inputText.value = msg
  } finally {
    sending.value = false
  }
}

function clearChat() {
  turns.value = []
  sendError.value = ''
}

onMounted(() => {
  loadPersons()
  loadStatus()
  const q = (route.query.subject_id || '').trim()
  if (q) selectedSubjectId.value = q
})
</script>

<template>
  <div class="simulate-page">
    <section class="po-card">
      <h2 class="po-h2">第一人称风格模拟</h2>
      <p class="muted small">
        以 Neo4j 中该 Person 的<strong>人格子图</strong>（摘要、口癖、典型对话等）约束语气与立场；
        <strong>不是</strong>真人替身，不编造图谱未收录的具体事实。须配置 DeepSeek（见 backend/.env）。
      </p>

      <p v-if="deepseekOk === false" class="error small">
        DeepSeek 未启用：请设置 <code>DEEPSEEK_ENABLED=true</code> 与 <code>DEEPSEEK_API_KEY</code> 后重启 API。
      </p>

      <label class="field">
        <span>选择 Person</span>
        <PoLoading v-if="personsLoading" label="加载 Person 列表…" size="sm" />
        <select
          v-else
          v-model="selectedSubjectId"
          class="select-input"
          @change="onPersonChange"
        >
          <option disabled value="">请选择</option>
          <option v-for="p in persons" :key="p.subject_id" :value="p.subject_id">
            {{ p.display_name || p.subject_id }} — {{ p.subject_id }}
          </option>
        </select>
        <p v-if="personsError" class="error small">{{ personsError }}</p>
        <p v-if="!personsLoading && !persons.length" class="muted small">
          尚无 Person，请先在「数据导入」写入聊天记录。
        </p>
      </label>

      <label class="field">
        <span>情境（可选）</span>
        <input
          v-model="scenario"
          type="text"
          class="text-input"
          placeholder="如：对方是你很久没见的朋友，在微信上寒暄"
          autocomplete="off"
        />
      </label>
    </section>

    <section class="po-card chat-card">
      <div class="chat-toolbar">
        <span class="muted small">对话（探索性模拟）</span>
        <button type="button" class="po-btn po-btn--ghost po-btn--sm" :disabled="!turns.length" @click="clearChat">
          清空对话
        </button>
      </div>

      <PoLoadingOverlay :show="sending" label="正在生成第一人称回复…" />

      <div v-if="!turns.length" class="chat-empty muted small">输入一句话，模拟该 Person 在图谱约束下的第一人称回复。
      </div>

      <ul v-else class="chat-log">
        <li
          v-for="(t, i) in turns"
          :key="i"
          class="chat-bubble"
          :class="t.role === 'user' ? 'chat-bubble--user' : 'chat-bubble--sim'"
        >
          <span class="chat-role">{{ t.role === 'user' ? '你' : '模拟' }}</span>
          <p class="chat-text">{{ t.content }}</p>
          <template v-if="t.meta && t.role === 'assistant'">
            <p v-if="t.meta.out_of_graph_note" class="chat-meta warn">
              图外说明：{{ t.meta.out_of_graph_note }}
            </p>
            <p v-if="t.meta.graph_facts_used?.length" class="chat-meta muted">
              图谱依据：{{ t.meta.graph_facts_used.join('；') }}
            </p>
            <p v-if="t.meta.confidence_0_1 != null" class="chat-meta muted">
              贴合度（模型自评）：{{ t.meta.confidence_0_1 }}
            </p>
          </template>
        </li>
      </ul>

      <p v-if="sendError" class="error small">{{ sendError }}</p>

      <form class="chat-compose" @submit.prevent="sendMessage">
        <textarea
          v-model="inputText"
          class="chat-input"
          rows="3"
          placeholder="输入你想对 TA 说的话…"
          :disabled="!selectedSubjectId || deepseekOk !== true"
        />
        <button type="submit" class="po-btn po-btn--primary" :disabled="!canSend">发送</button>
      </form>

      <p class="muted small disclaimer">
        免责声明：输出为基于聊天记录推断的探索性模拟，不代表真人真实想法；禁止用于欺诈、冒充或未授权画像。
      </p>
    </section>
  </div>
</template>

<style scoped>
.simulate-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 0 1rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.chat-card {
  position: relative;
  min-height: 320px;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chat-empty {
  padding: 2rem 0;
  text-align: center;
}

.chat-log {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  max-height: 420px;
  overflow-y: auto;
}

.chat-bubble {
  border-radius: 12px;
  padding: 0.55rem 0.75rem;
  max-width: 92%;
}

.chat-bubble--user {
  align-self: flex-end;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.chat-bubble--sim {
  align-self: flex-start;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.chat-role {
  font-size: 0.7rem;
  font-weight: 650;
  color: #64748b;
  display: block;
  margin-bottom: 0.25rem;
}

.chat-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.92rem;
  line-height: 1.45;
}

.chat-meta {
  margin: 0.35rem 0 0;
  font-size: 0.72rem;
  line-height: 1.35;
}

.chat-meta.warn {
  color: #b45309;
}

.chat-compose {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: auto;
}

.chat-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--po-border, #e2e8f0);
  border-radius: 10px;
  padding: 0.55rem 0.65rem;
  font: inherit;
  resize: vertical;
}

.disclaimer {
  margin: 0;
  border-top: 1px solid #f1f5f9;
  padding-top: 0.65rem;
}
</style>
