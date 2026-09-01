import type { Component } from 'vue'
import {
  createRouter,
  createWebHistory,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'
import SharedItineraryPage from '../../pages/SharedItineraryPage.vue'
import WorkspacePage from '../../workspace/WorkspacePage.vue'

const RouteMarker: Component = {
  render: () => null,
}

const routes: RouteRecordRaw[] = [
  { path: '/share/:shareToken', name: 'shared-itinerary', component: SharedItineraryPage },
  // TripPilot Planning Intelligence：AI Agent Workspace（新产品入口）。
  { path: '/workspace', name: 'workspace', component: WorkspacePage },
  { path: '/workspace/trips/:tripId', name: 'workspace-trip', component: WorkspacePage },
  // 根路径重定向到 workspace
  { path: '/', redirect: { name: 'workspace' } },
  { path: '/:pathMatch(.*)*', name: 'not-found', redirect: { name: 'workspace' } },
]

export function createTripPilotRouter(history: RouterHistory = createWebHistory(import.meta.env.BASE_URL)) {
  return createRouter({ history, routes })
}