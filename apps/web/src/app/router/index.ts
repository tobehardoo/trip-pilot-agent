import type { Component } from 'vue'
import {
  createRouter,
  createWebHistory,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'
import TripWorkspace from '../../pages/TripWorkspace.vue'
import SharedItineraryPage from '../../pages/SharedItineraryPage.vue'

const RouteMarker: Component = {
  render: () => null,
}

const RouteWorkspace: Component = TripWorkspace

const routes: RouteRecordRaw[] = [
  { path: '/share/:shareToken', name: 'shared-itinerary', component: SharedItineraryPage },
  {
    path: '/',
    component: RouteWorkspace,
    children: [
      { path: '', redirect: { name: 'trip-list' } },
      { path: 'login', name: 'login', component: RouteMarker },
      { path: 'register', name: 'register', component: RouteMarker },
      { path: 'trips', name: 'trip-list', component: RouteMarker },
      { path: 'trips/new', name: 'trip-create', component: RouteMarker },
      { path: 'trips/:tripId', name: 'trip-detail', component: RouteMarker },
      { path: 'trips/:tripId/plan', name: 'trip-plan', component: RouteMarker },
      { path: 'trips/:tripId/versions', name: 'trip-versions', component: RouteMarker },
      { path: ':pathMatch(.*)*', name: 'not-found', component: RouteMarker },
    ],
  },
]

export function createTripPilotRouter(history: RouterHistory = createWebHistory(import.meta.env.BASE_URL)) {
  return createRouter({ history, routes })
}
