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

function renderOverlays(namespace: AMapNamespace) {
  if (!map) return
  clearOverlays()
  model.value.legs.forEach((leg) => {
    const polyline = new namespace.Polyline({
      path: leg.polyline.map((point) => [point.longitude, point.latitude]),
      strokeColor: '#2563eb',
      strokeOpacity: 0.85,
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
}

function renderAmap(namespace: AMapNamespace) {
  if (!mapElement.value) return
  if (!map) {
    const createdMap = new namespace.Map(mapElement.value, {
      zoom: 12,
      center: selectedActivity.value
        ? [selectedActivity.value.coordinate.longitude, selectedActivity.value.coordinate.latitude]
        : undefined,
      resizeEnable: true,
      viewMode: '2D',
      mapStyle: 'amap://styles/normal',
    })
    map = createdMap
  }
  renderOverlays(namespace)
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
  <div class="h-full w-full min-w-0" data-testid="trip-map" aria-label="行程地图" role="region">
    <!-- No Coordinates -->
    <div v-if="!hasCoordinates" class="flex h-full flex-col items-center justify-center gap-2 text-surface-400">
      <MapPinned :size="28" aria-hidden="true" />
      <strong class="text-sm text-surface-500">暂无可定位地点</strong>
      <span class="text-xs text-surface-400">活动生成地点后会显示在这里</span>
    </div>

    <template v-else>
      <!-- Hidden status for screen readers / tests -->
      <span class="sr-only" aria-live="polite">
        {{ sdkState === 'ready' ? '高德地图' : '路线概览' }}
      </span>
      <div class="relative h-full w-full">
        <!-- AMap Canvas -->
        <div
          ref="mapElement"
          class="amap-canvas h-full w-full bg-surface-100"
          :class="{ 'is-hidden': sdkState !== 'ready' }"
          aria-hidden="true"
        />

        <!-- Fallback SVG Overview -->
        <div
          v-if="sdkState !== 'ready'"
          class="absolute inset-0 grid grid-rows-[1fr_auto] p-3.5 bg-surface-50"
          aria-label="路线概览"
        >
          <div
            class="relative h-full overflow-hidden rounded-xl border border-surface-200 bg-surface-100"
            style="background-image: linear-gradient(rgb(148 163 184 / 0.08) 1px, transparent 1px), linear-gradient(90deg, rgb(148 163 184 / 0.08) 1px, transparent 1px); background-size: 28px 28px;"
          >
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <polyline
                v-for="leg in model.legs"
                :key="leg.id"
                :points="leg.polyline.map((point) => { const projected = projectMapCoordinate(point, model.bounds!); return `${projected.x},${projected.y}` }).join(' ')"
                fill="none"
                stroke="#93c5fd"
                stroke-width="1.5"
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
            <span class="absolute right-2.5 bottom-2 text-xs font-semibold text-surface-400">路线概览</span>
          </div>
          <p v-if="sdkState === 'error'" class="flex items-center gap-1.5 min-h-7 mt-2 text-xs text-red-500" role="status">
            <TriangleAlert :size="13" aria-hidden="true" />{{ mapError }}
          </p>
          <p v-else-if="!hasAmapConfig" class="flex items-center gap-1.5 min-h-7 mt-2 text-xs text-surface-400" role="status">
            地图凭据未配置，当前显示路线概览
          </p>
        </div>
      </div>

      <!-- Activity List (bottom of map) -->
      <div class="grid gap-px p-2 bg-surface-200">
        <button
          v-for="(activity, index) in model.activities"
          :key="activity.id"
          class="grid grid-cols-[25px_1fr] items-center gap-2 px-2 py-2 bg-white border-0 text-left cursor-pointer transition-colors hover:bg-primary-50"
          :class="{ 'bg-primary-50': activity.id === selectedActivity?.id }"
          type="button"
          :aria-pressed="activity.id === selectedActivity?.id"
          @click="selectActivity(activity)"
        >
          <span
            class="flex h-5 w-5 items-center justify-center rounded-full text-xs font-extrabold text-white"
            :class="activity.id === selectedActivity?.id ? 'bg-primary-600' : 'bg-primary-500'"
          >{{ index + 1 }}</span>
          <span class="grid gap-0.5 min-w-0">
            <strong class="truncate text-xs text-surface-700">{{ activity.title }}</strong>
            <small class="text-[10px] text-surface-400">{{ activity.coordinate.longitude.toFixed(4) }}, {{ activity.coordinate.latitude.toFixed(4) }}</small>
          </span>
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.overview-marker {
  position: absolute;
  z-index: 1;
  width: 26px;
  height: 26px;
  padding: 0;
  transform: translate(-50%, -50%);
  color: #fff;
  background: #2563eb;
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
  font: inherit;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
}

.overview-marker.is-selected {
  color: #fff;
  background: #1d4ed8;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.25), 0 2px 8px rgba(37, 99, 235, 0.3);
}
</style>

<style>
.amap-marker-pin {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  color: #fff;
  background: #2563eb;
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
  font: 700 11px Inter, sans-serif;
}

.amap-marker-pin.is-selected {
  color: #fff;
  background: #1d4ed8;
}
</style>
