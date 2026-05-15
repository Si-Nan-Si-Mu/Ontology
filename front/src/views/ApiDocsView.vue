<script setup>
import { computed, ref } from 'vue'

import { publicApiBase } from '@/api/http.js'

const base = computed(() => publicApiBase())

const endpoints = computed(() => {
  const b = base.value
  return [
    { name: '健康检查', method: 'GET', path: '/health' },
    { name: 'Neo4j 探活', method: 'GET', path: '/health/neo4j' },
    { name: '导入', method: 'POST', path: '/api/v1/ingest' },
    { name: '微信 wx-cli 状态', method: 'GET', path: '/api/v1/wechat/status' },
    { name: '微信会话列表（需 WX_CLI_ENABLED）', method: 'GET', path: '/api/v1/wechat/sessions?limit=30' },
    { name: '微信按会话导出并导入', method: 'POST', path: '/api/v1/wechat/import-from-session' },
    { name: '微信预分析会话说话人', method: 'POST', path: '/api/v1/wechat/preview-export' },
    { name: '微信解析 JSON 说话人', method: 'POST', path: '/api/v1/wechat/analyze-json' },
    { name: '图节点分页', method: 'GET', path: '/api/v1/graph/nodes?page=1&page_size=20' },
  ].map((e) => ({ ...e, href: `${b}${e.path}` }))
})

const copyTip = ref('')

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    copyTip.value = '已复制'
    setTimeout(() => {
      copyTip.value = ''
    }, 1800)
  } catch {
    copyTip.value = '复制失败'
  }
}

const curlIngest = computed(
  () =>
    `curl -sS -X POST "${base.value}/api/v1/ingest" \\\n  -H "Content-Type: application/json" \\\n  -d '{"subject_id":"demo-user-001","source_type":"plain_text","raw_text":"你好"}'`,
)

const curlGraph = computed(
  () => `curl -sS "${base.value}/api/v1/graph/nodes?page=1&page_size=10"`,
)
</script>

<template>
  <div class="po-page api">
    <section class="quick po-card">
      <h2>文档入口</h2>
      <p class="lead">
        外部工程（脚本、服务、低代码）请优先使用 <strong>OpenAPI</strong> 生成客户端；浏览器联调可直接打开
        Swagger。
      </p>
      <div class="tiles">
        <a class="tile" :href="`${base}/docs`" target="_blank" rel="noopener">
          <span class="tile-k">Swagger UI</span>
          <span class="tile-v po-mono">GET {{ base }}/docs</span>
        </a>
        <a class="tile" :href="`${base}/openapi.json`" target="_blank" rel="noopener">
          <span class="tile-k">OpenAPI JSON</span>
          <span class="tile-v po-mono">GET {{ base }}/openapi.json</span>
        </a>
        <a class="tile" :href="`${base}/redoc`" target="_blank" rel="noopener">
          <span class="tile-k">ReDoc</span>
          <span class="tile-v po-mono">GET {{ base }}/redoc</span>
        </a>
      </div>
    </section>

    <section class="po-card">
      <h3>端点清单</h3>
      <p class="muted small">点击「复制」获得完整 URL，便于粘贴到 Postman / 终端。</p>
      <div class="ep-list">
        <div v-for="ep in endpoints" :key="ep.path" class="ep">
          <div class="ep-main">
            <span class="method">{{ ep.method }}</span>
            <code class="url po-mono">{{ ep.href }}</code>
            <button type="button" class="po-btn po-btn--sm" @click="copyText(ep.href)">复制</button>
          </div>
          <span class="ep-name">{{ ep.name }}</span>
        </div>
      </div>
      <p v-if="copyTip" class="tip">{{ copyTip }}</p>
    </section>

    <section class="po-card">
      <h3>cURL 示例</h3>
      <div class="curl-block">
        <div class="curl-h">导入（JSON）</div>
        <pre class="po-mono curl">{{ curlIngest }}</pre>
        <button type="button" class="po-btn po-btn--sm" @click="copyText(curlIngest)">复制</button>
      </div>
      <div class="curl-block">
        <div class="curl-h">分页读节点</div>
        <pre class="po-mono curl">{{ curlGraph }}</pre>
        <button type="button" class="po-btn po-btn--sm" @click="copyText(curlGraph)">复制</button>
      </div>
    </section>

    <section class="po-card checklist">
      <h3>接入检查表</h3>
      <ol>
        <li>本地：Neo4j + <code>uvicorn app.main:app</code> + <code>npm run dev</code>（Vite 代理同源路径）。</li>
        <li>
          微信：<code>source_type=wechat_export</code> 见仓库
          <code>docs/WECHAT_WX_CLI.md</code>（需本机安装 wx-cli 并导出 JSON）。
        </li>
        <li>生产：前端构建设置 <code>VITE_API_ORIGIN=https://你的 API</code>，并配置 HTTPS 与 CORS。</li>
        <li>鉴权：当前无鉴权；上线前在网关或 FastAPI 依赖中增加 Token / OAuth2。</li>
        <li>限流：对外暴露 <code>/api/v1/*</code> 时建议加 rate limit 与审计日志。</li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.api {
  padding-top: 0.25rem;
}

.quick h2 {
  margin: 0 0 0.5rem;
  font-size: 1.05rem;
}

.lead {
  margin: 0 0 1rem;
  font-size: 0.88rem;
  line-height: 1.55;
  color: #334155;
}

.tiles {
  display: grid;
  gap: 0.5rem;
}

@media (min-width: 720px) {
  .tiles {
    grid-template-columns: repeat(3, 1fr);
  }
}

.tile {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.75rem;
  border-radius: 10px;
  border: 1px solid var(--po-border, #e2e8f0);
  text-decoration: none;
  color: inherit;
  background: #f8fafc;
  transition:
    border-color 0.15s,
    background 0.15s;
}

.tile:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}

.tile-k {
  font-weight: 650;
  font-size: 0.85rem;
  color: #1e293b;
}

.tile-v {
  font-size: 0.7rem;
  color: #64748b;
  word-break: break-all;
}

h3 {
  margin: 0 0 0.35rem;
  font-size: 0.95rem;
}

.muted {
  color: var(--po-muted, #64748b);
}

.small {
  font-size: 0.8rem;
  margin: 0 0 0.75rem;
}

.ep-list {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.ep {
  padding-bottom: 0.65rem;
  border-bottom: 1px solid #f1f5f9;
}

.ep:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.ep-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}

.method {
  font-weight: 700;
  font-size: 0.68rem;
  color: #059669;
  flex-shrink: 0;
}

.url {
  flex: 1;
  min-width: 0;
  font-size: 0.72rem;
  color: #334155;
  word-break: break-all;
}

.ep-name {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.72rem;
  color: #94a3b8;
}

.tip {
  margin: 0.5rem 0 0;
  font-size: 0.8rem;
  color: #059669;
}

.curl-block {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid #f1f5f9;
}

.curl-block:first-of-type {
  margin-top: 0.5rem;
  padding-top: 0;
  border-top: none;
}

.curl-h {
  font-size: 0.78rem;
  font-weight: 600;
  color: #475569;
  margin-bottom: 0.35rem;
}

.curl {
  margin: 0 0 0.4rem;
  padding: 0.65rem 0.75rem;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 0.72rem;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.checklist {
  margin-top: 1rem;
}

.checklist ol {
  margin: 0.5rem 0 0;
  padding-left: 1.15rem;
  font-size: 0.84rem;
  line-height: 1.6;
  color: #475569;
}

.checklist code {
  font-size: 0.78rem;
  background: #f1f5f9;
  padding: 0.05rem 0.25rem;
  border-radius: 4px;
}
</style>
