import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

import App from '../App.vue'
import MainLayout from '../layouts/MainLayout.vue'
import ApiDocsView from '../views/ApiDocsView.vue'
import GraphView from '../views/GraphView.vue'
import ImportView from '../views/ImportView.vue'

describe('App', () => {
  const origFetch = globalThis.fetch

  beforeEach(() => {
    globalThis.fetch = vi.fn((url) => {
      const u = String(url)
      if (u.includes('/api/v1/graph/nodes')) {
        return Promise.resolve({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: () => Promise.resolve({ total: 0, items: [], page: 1, page_size: 15 }),
        })
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        text: () => Promise.resolve('not found'),
        headers: new Headers(),
      })
    })
  })

  afterEach(() => {
    globalThis.fetch = origFetch
  })

  function makeRouter() {
    return createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/',
          component: MainLayout,
          redirect: '/import',
          children: [
            { path: 'import', name: 'import', component: ImportView },
            { path: 'graph', name: 'graph', component: GraphView },
            { path: 'api', name: 'api', component: ApiDocsView },
          ],
        },
      ],
    })
  }

  it('默认进入导入页且主导航包含三模块', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()

    const wrapper = mount(App, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('数据导入')
    expect(wrapper.text()).toContain('图数据')
    expect(wrapper.text()).toContain('开放接口')
    expect(wrapper.text()).toContain('导入流水线')
  })

  it('可跳转到图数据页', async () => {
    const router = makeRouter()
    await router.push('/graph')
    await router.isReady()

    const wrapper = mount(App, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('节点浏览')
  })
})
