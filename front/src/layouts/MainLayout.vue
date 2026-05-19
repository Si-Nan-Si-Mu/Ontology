<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import AppNavLinks from '@/components/AppNavLinks.vue'

const route = useRoute()

const items = [
  {
    to: '/import',
    name: 'import',
    title: '数据导入',
    subtitle: '文本 / 预留文件',
  },
  {
    to: '/graph',
    name: 'graph',
    title: '图数据',
    subtitle: 'Person 子图可视化',
  },
  {
    to: '/simulate',
    name: 'simulate',
    title: '风格模拟',
    subtitle: '图约束第一人称对话',
  },
  {
    to: '/api',
    name: 'api',
    title: '开放接口',
    subtitle: '文档与联调',
  },
]

const currentTitle = computed(() => {
  const hit = items.find((x) => route.path === x.to || route.name === x.name)
  return hit?.title ?? 'POG'
})

const drawerOpen = ref(false)
let mq
let mqListener

function closeDrawer() {
  drawerOpen.value = false
}

function toggleDrawer() {
  drawerOpen.value = !drawerOpen.value
}

function onNavClick() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    closeDrawer()
    return
  }
  if (window.matchMedia('(max-width: 959px)').matches) {
    closeDrawer()
  }
}

watch(
  () => route.path,
  () => {
    closeDrawer()
  },
)

watch(drawerOpen, (open) => {
  if (typeof document === 'undefined') return
  document.body.style.overflow = open ? 'hidden' : ''
})

onMounted(() => {
  if (typeof window.matchMedia !== 'function') return
  mq = window.matchMedia('(min-width: 960px)')
  mqListener = () => {
    if (mq.matches) closeDrawer()
  }
  mq.addEventListener('change', mqListener)
})

onUnmounted(() => {
  if (mq && mqListener) {
    mq.removeEventListener('change', mqListener)
  }
  document.body.style.overflow = ''
})
</script>

<template>
  <div class="layout">
    <!-- 移动端遮罩 -->
    <Transition name="fade">
      <button
        v-show="drawerOpen"
        type="button"
        class="scrim"
        aria-label="关闭菜单"
        @click="closeDrawer"
      />
    </Transition>

    <!-- 左侧栏：桌面常驻；小屏为抽屉 -->
    <aside
      class="sidebar"
      :class="{ 'sidebar--open': drawerOpen }"
      :aria-hidden="false"
      aria-label="侧栏导航"
    >
      <RouterLink
        to="/import"
        class="side-brand"
        aria-label="POG 人格本体图控制台，返回首页"
        @click="onNavClick"
      >
        <div class="brand-row">
          <img
            src="/pog-mark.svg"
            alt=""
            width="40"
            height="40"
            class="brand-logo"
            decoding="async"
            aria-hidden="true"
          />
          <div class="brand-titles">
            <span class="brand-wordmark">POG</span>
            <span class="brand-text">人格本体图控制台</span>
          </div>
        </div>
      </RouterLink>

      <AppNavLinks :items="items" :current-path="route.path" @after-navigate="onNavClick" />
    </aside>

    <div class="column">
      <!-- 顶栏：小屏显示菜单按钮；桌面可略窄占位 -->
      <header class="topbar">
        <div class="topbar-inner">
          <button
            type="button"
            class="menu-btn"
            aria-label="打开侧栏菜单"
            :aria-expanded="drawerOpen"
            @click="toggleDrawer"
          >
            <svg class="menu-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z"
              />
            </svg>
          </button>
          <RouterLink
            to="/import"
            class="top-brand"
            aria-label="返回首页，当前栏目：{{ currentTitle }}"
            @click="closeDrawer"
          >
            <img
              src="/pog-mark.svg"
              alt=""
              width="28"
              height="28"
              class="brand-logo brand-logo--top"
              decoding="async"
              aria-hidden="true"
            />
            <span class="brand-wordmark brand-wordmark--top" aria-hidden="true">POG</span>
            <span class="top-brand-title">{{ currentTitle }}</span>
          </RouterLink>
        </div>
      </header>

      <div class="subbar">
        <div class="subbar-inner">
          <h1 class="page-title">{{ currentTitle }}</h1>
          <p class="page-crumb muted">当前路径 {{ route.path }}</p>
        </div>
      </div>

      <main class="main">
        <RouterView />
      </main>

      <footer class="foot">
        <span>POG 原型 · 侧栏导航 · 小屏抽屉</span>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  color: var(--po-text, #1e293b);
  font-family:
    'Segoe UI',
    system-ui,
    -apple-system,
    sans-serif;
}

/* —— 侧栏：默认（小屏）抽屉 —— */
.sidebar {
  position: fixed;
  z-index: 120;
  top: 0;
  left: 0;
  bottom: 0;
  width: min(86vw, 280px);
  box-sizing: border-box;
  background: #fff;
  border-right: 1px solid var(--po-border, #e2e8f0);
  padding: 1rem 0.85rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  transform: translateX(-105%);
  transition: transform 0.22s ease;
  box-shadow: 4px 0 24px rgb(15 23 42 / 8%);
}

.sidebar--open {
  transform: translateX(0);
}

.scrim {
  position: fixed;
  inset: 0;
  z-index: 110;
  border: none;
  padding: 0;
  margin: 0;
  cursor: pointer;
  background: rgb(15 23 42 / 42%);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.side-brand {
  text-decoration: none;
  color: inherit;
  padding: 0.15rem 0.25rem;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 0.55rem;
}

.brand-logo {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgb(15 23 42 / 12%);
}

.brand-titles {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}

.brand-wordmark {
  font-weight: 800;
  letter-spacing: 0.08em;
  font-size: 1rem;
  color: var(--po-accent, #4338ca);
  line-height: 1.1;
}

.brand-text {
  font-size: 0.72rem;
  color: var(--po-muted, #64748b);
  line-height: 1.35;
}

/* 右侧主列 */
.column {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.topbar {
  background: #fff;
  border-bottom: 1px solid var(--po-border, #e2e8f0);
  position: sticky;
  top: 0;
  z-index: 30;
}

.topbar-inner {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.55rem 1rem;
  max-width: 1100px;
  margin: 0 auto;
}

.menu-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  border: 1px solid var(--po-border, #e2e8f0);
  border-radius: 10px;
  background: #f8fafc;
  color: #334155;
  cursor: pointer;
  flex-shrink: 0;
}

.menu-btn:hover {
  background: #f1f5f9;
}

.menu-icon {
  width: 1.35rem;
  height: 1.35rem;
}

.top-brand {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  text-decoration: none;
  color: inherit;
  min-width: 0;
}

.brand-logo--top {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  flex-shrink: 0;
}

.brand-wordmark--top {
  font-weight: 800;
  letter-spacing: 0.06em;
  font-size: 0.82rem;
  color: var(--po-accent, #4338ca);
  flex-shrink: 0;
}

.top-brand-title {
  font-size: 0.95rem;
  font-weight: 650;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.subbar {
  background: linear-gradient(180deg, #f8fafc 0%, var(--po-bg, #f8fafc) 100%);
  border-bottom: 1px solid #e2e8f0;
}

.subbar-inner {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1rem 1.25rem 0.85rem;
}

.page-title {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.page-crumb {
  margin: 0.35rem 0 0;
  font-size: 0.78rem;
}

.muted {
  color: var(--po-muted, #64748b);
}

.main {
  flex: 1;
  padding-top: 0.5rem;
}

.foot {
  text-align: center;
  font-size: 0.72rem;
  color: #94a3b8;
  padding: 1rem;
  border-top: 1px solid #f1f5f9;
  background: #fff;
}

/* —— 桌面：侧栏固定于视口，主列独立滚动 —— */
@media (min-width: 960px) {
  .layout {
    display: block;
    min-height: 100vh;
  }

  .sidebar {
    position: fixed;
    z-index: 100;
    top: 0;
    left: 0;
    bottom: 0;
    width: 232px;
    transform: none !important;
    flex-shrink: 0;
    box-shadow: none;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
  }

  .sidebar--open {
    transform: none !important;
  }

  .scrim {
    display: none !important;
  }

  .column {
    margin-left: 232px;
    min-width: 0;
    width: auto;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .menu-btn {
    display: none;
  }

  .topbar-inner {
    padding-left: 1.25rem;
  }

  .top-brand {
    pointer-events: none;
  }

  .brand-logo--top {
    width: 24px;
    height: 24px;
    border-radius: 6px;
  }

  .brand-wordmark--top {
    display: none;
  }

  .top-brand-title {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--po-muted, #64748b);
  }
}
</style>
