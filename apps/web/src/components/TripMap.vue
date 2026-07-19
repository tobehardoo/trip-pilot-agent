<script setup lang="ts">
import { MapPinned, Route, TriangleAlert } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { Itinerary } from '../lib/api'
import { getAMapConfig, loadAMap, type AMapMap, type AMapMarker, type AMapNamespace, type AMapPolyline } from '../lib/amap'
import { buildMapModel, projectMapCoordinate, type MapActivity, type MapModel } from '../lib/map'

const props = defineProps<{
  itinerary: Pick<Itinerary, 'days'>
  selectedActivityId: string | null
}>()

const emit = defineEmits<{
  selectActivity: [activityId: string]
}>()

const mapElement = ref<HTMLElement | null>(null)
const sdkState = ref<'idle' | 'loading' | 'ready' | 'fallback' | 'error'>('idle')
const mapError = ref<string | null>(null)
const model = computed<MapModel>(() => buildMapModel(props.itinerary))
const selectedActivity = computed(() => {
  if (props.selectedActivityId === null) return model.value.activities[0] ?? null
  return model.value.activities.find((activity) => activity.id === props.selectedActivityId) ?? null
})
const hasCoordinates = computed(() => model.value.activities.length > 0)
const hasAmapConfig = computed(() => Boolean(getAMapConfig()))
let map: AMapMap | null = null
let amap: AMapNamespace | null = null
let markers: AMapMarker[] = []
let polylines: AMapPolyline[] = []
let mapLoadSequence = 0

function selectActivity(activity: MapActivity) {
  emit('selectActivity', activity.id)
  if (map && activity.coordinate) {
    map.setCenter?.([activity.coordinate.longitude, activity.coordinate.latitude])
    map.setZoom?.(15)
  }
}

function clearOverlays() {
  markers.forEach((marker) => marker.setMap(null))
  polylines.forEach((polyline) => polyline.setMap(null))
  markers = []
  polylines = []
}

function destroyMap() {
  clearOverlays()
  map?.destroy?.()
  map = null
  amap = null
}

function markerContent(activity: MapActivity, index: number) {
  const selected = activity.id === selectedActivity.value?.id
  return `<span class="amap-marker-pin${selected ? ' is-selected' : ''}">${index + 1}</span>`
}

function renderAmap(namespace: AMapNamespace) {
  if (!mapElement.value) return
  clearOverlays()
  if (!map) {
    map = new namespace.Map(mapElement.value, {
      zoom: 12,
      center: selectedActivity.value
        ? [selectedActivity.value.coordinate.longitude, selectedActivity.value.coordinate.latitude]
        : undefined,
      resizeEnable: true,
    })
  }
  model.value.legs.forEach((leg) => {
    const polyline = new namespace.Polyline({
      path: leg.polyline.map((point) => [point.longitude, point.latitude]),
      strokeColor: '#c38d22',
      strokeOpacity: 0.9,
      strokeWeight: 4,
      lineJoin: 'round',
      lineCap: 'round',
      showDir: true,
    })
    polyline.setMap(map)
    polylines.push(polyline)
  })
  model.value.activities.forEach((activity, index) => {
    const marker = new namespace.Marker({
      position: [activity.coordinate.longitude, activity.coordinate.latitude],
      content: markerContent(activity, index),
      anchor: 'center',
      title: activity.title,
    })
    marker.setMap(map)
    marker.on?.('click', () => selectActivity(activity))
    markers.push(marker)
  })
  if (markers.length > 0 || polylines.length > 0) map.setFitView([...markers, ...polylines])
  sdkState.value = 'ready'
}

async function initialiseMap() {
  const requestSequence = ++mapLoadSequence
  if (!hasCoordinates.value) {
    destroyMap()
    sdkState.value = 'fallback'
    return
  }
  if (!hasAmapConfig.value) {
    sdkState.value = 'fallback'
    return
  }
  sdkState.value = 'loading'
  mapError.value = null
  try {
    const namespace = await loadAMap()
    if (requestSequence !== mapLoadSequence || !mapElement.value) return
    amap = namespace
    renderAmap(namespace)
  } catch {
    if (requestSequence !== mapLoadSequence) return
    destroyMap()
    sdkState.value = 'error'
    mapError.value = '高德地图暂时无法加载，已切换为路线概览'
  }
}

function refreshSelectedMarker() {
  if (sdkState.value === 'ready' && amap) {
    renderAmap(amap)
    if (selectedActivity.value) {
      map?.setCenter?.([selectedActivity.value.coordinate.longitude, selectedActivity.value.coordinate.latitude])
      map?.setZoom?.(15)
    }
  }
}

watch(() => props.itinerary, () => { void initialiseMap() }, { deep: true })
watch(() => props.selectedActivityId, refreshSelectedMarker)

onMounted(() => { void initialiseMap() })

onBeforeUnmount(() => {
  mapLoadSequence += 1
  destroyMap()
})
</script>

<template>
  <section class="trip-map" aria-label="行程地图" data-testid="trip-map">
    <header class="trip-map-heading">
      <div>
        <p class="eyebrow">MAP VIEW</p>
        <h3>地点与路线</h3>
      </div>
      <span v-if="sdkState === 'ready'" class="map-mode"><MapPinned :size="14" aria-hidden="true" />高德地图</span>
      <span v-else class="map-mode"><Route :size="14" aria-hidden="true" />路线概览</span>
    </header>

    <div v-if="!hasCoordinates" class="trip-map-empty">
      <MapPinned :size="24" aria-hidden="true" />
      <strong>暂无可定位地点</strong>
      <span>活动生成地点后会显示在这里</span>
    </div>

    <template v-else>
      <div class="map-surface">
        <div ref="mapElement" class="amap-canvas" :class="{ 'is-hidden': sdkState !== 'ready' }" aria-hidden="true"></div>
        <div v-if="sdkState !== 'ready'" class="route-overview" aria-label="路线概览">
          <div class="overview-grid">
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <polyline
                v-for="leg in model.legs"
                :key="leg.id"
                :points="leg.polyline.map((point) => { const projected = projectMapCoordinate(point, model.bounds!); return `${projected.x},${projected.y}` }).join(' ')"
                fill="none"
                stroke="#c38d22"
                stroke-width="1.3"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-dasharray="2 1.5"
              />
            </svg>
            <button
              v-for="(activity, index) in model.activities"
              :key="activity.id"
              class="overview-marker"
              :class="{ 'is-selected': activity.id === selectedActivity?.id }"
              :style="{ left: `${projectMapCoordinate(activity.coordinate, model.bounds!).x}%`, top: `${projectMapCoordinate(activity.coordinate, model.bounds!).y}%` }"
              type="button"
              :aria-label="`定位 ${activity.title}`"
              :aria-pressed="activity.id === selectedActivity?.id"
              @click="selectActivity(activity)"
            >
              {{ index + 1 }}
            </button>
            <span class="overview-label">路线概览</span>
          </div>
          <p v-if="sdkState === 'error'" class="map-fallback-note" role="status"><TriangleAlert :size="14" aria-hidden="true" />{{ mapError }}</p>
          <p v-else-if="!hasAmapConfig" class="map-fallback-note" role="status">地图凭据未配置，当前显示路线概览</p>
        </div>
      </div>
      <div class="map-activity-list">
        <button
          v-for="(activity, index) in model.activities"
          :key="activity.id"
          class="map-activity"
          :class="{ 'is-selected': activity.id === selectedActivity?.id }"
          type="button"
          :aria-pressed="activity.id === selectedActivity?.id"
          @click="selectActivity(activity)"
        >
          <span class="map-activity-index">{{ index + 1 }}</span>
          <span class="map-activity-copy"><strong>{{ activity.title }}</strong><small>{{ activity.coordinate.longitude.toFixed(4) }}, {{ activity.coordinate.latitude.toFixed(4) }}</small></span>
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.trip-map { min-width: 0; border: 1px solid #d4ddda; background: #f7faf8; }
.trip-map-heading { min-height: 66px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; background: #fff; border-bottom: 1px solid #dfe8e3; }
.trip-map-heading h3 { margin: 5px 0 0; font-size: 16px; }
.eyebrow { margin: 0; color: #8a650f; font-size: 10px; font-weight: 850; }
.map-mode { display: inline-flex; align-items: center; gap: 5px; color: #52625c; font-size: 11px; font-weight: 700; }
.map-surface { position: relative; height: 290px; }
.amap-canvas, .route-overview { height: 100%; }
.amap-canvas { width: 100%; background: #e9f0ec; }
.amap-canvas.is-hidden { visibility: hidden; }
.route-overview { position: absolute; inset: 0; display: grid; grid-template-rows: minmax(0, 1fr) auto; padding: 14px; background: #eff5f1; }
.overview-grid { position: relative; height: 100%; overflow: hidden; border: 1px solid #d2e1d9; background-color: #edf5f0; background-image: linear-gradient(rgba(109, 145, 126, .12) 1px, transparent 1px), linear-gradient(90deg, rgba(109, 145, 126, .12) 1px, transparent 1px); background-size: 28px 28px; }
.overview-grid svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.overview-marker { position: absolute; z-index: 1; width: 26px; height: 26px; padding: 0; transform: translate(-50%, -50%); color: #fff; background: #2f705e; border: 2px solid #fff; border-radius: 50%; box-shadow: 0 2px 5px rgba(28, 67, 54, .25); font: inherit; font-size: 11px; font-weight: 800; cursor: pointer; }
.overview-marker.is-selected { color: #3d2d06; background: #e6b44a; box-shadow: 0 0 0 3px rgba(230, 180, 74, .25), 0 2px 5px rgba(28, 67, 54, .25); }
.overview-label { position: absolute; right: 10px; bottom: 8px; color: #5e786b; font-size: 10px; font-weight: 750; }
.map-fallback-note { min-height: 30px; display: flex; align-items: center; gap: 5px; margin: 0; padding: 8px 3px 0; color: #63746d; font-size: 11px; }
.map-fallback-note svg { flex: 0 0 auto; }
.map-activity-list { display: grid; gap: 1px; padding: 8px; background: #dfe8e3; }
.map-activity { min-width: 0; display: grid; grid-template-columns: 25px minmax(0, 1fr); align-items: center; gap: 8px; padding: 8px; color: #34443f; background: #fff; border: 0; text-align: left; cursor: pointer; }
.map-activity:hover, .map-activity.is-selected { background: #eef6f1; }
.map-activity-index { width: 21px; height: 21px; display: grid; place-items: center; color: #fff; background: #2f705e; border-radius: 50%; font-size: 10px; font-weight: 800; }
.map-activity.is-selected .map-activity-index { color: #3d2d06; background: #e6b44a; }
.map-activity-copy { min-width: 0; display: grid; gap: 3px; }
.map-activity-copy strong { overflow-wrap: anywhere; font-size: 12px; }
.map-activity-copy small { color: #71817b; font-size: 10px; }
.trip-map-empty { min-height: 290px; display: grid; place-items: center; align-content: center; gap: 8px; color: #71817b; font-size: 12px; }
.trip-map-empty strong { color: #34443f; font-size: 14px; }
.trip-map-empty span { color: #84938d; }
:global(.amap-marker-pin) { width: 24px; height: 24px; display: grid; place-items: center; color: #fff; background: #2f705e; border: 2px solid #fff; border-radius: 50%; box-shadow: 0 2px 6px rgba(19, 52, 42, .3); font: 700 11px Inter, sans-serif; }
:global(.amap-marker-pin.is-selected) { color: #3d2d06; background: #e6b44a; }
@media (max-width: 620px) { .map-surface { height: 240px; } }
</style>
