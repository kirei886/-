import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/plan',
      name: 'route-plan',
      component: () => import('@/views/RoutePlanView.vue'),
    },
  ],
})

export default router
