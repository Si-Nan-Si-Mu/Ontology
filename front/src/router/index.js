import { createRouter, createWebHistory } from 'vue-router'

import MainLayout from '@/layouts/MainLayout.vue'
import ApiDocsView from '@/views/ApiDocsView.vue'
import GraphView from '@/views/GraphView.vue'
import ImportView from '@/views/ImportView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: MainLayout,
      redirect: '/import',
      children: [
        {
          path: 'import',
          name: 'import',
          component: ImportView,
        },
        {
          path: 'graph',
          name: 'graph',
          component: GraphView,
        },
        {
          path: 'api',
          name: 'api',
          component: ApiDocsView,
        },
      ],
    },
  ],
})

export default router
