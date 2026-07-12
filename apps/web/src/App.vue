<script setup lang="ts">
const serviceStatus = [
  { name: '业务服务', state: '待连接' },
  { name: 'Agent 服务', state: '待连接' },
]
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <div>
        <h1>TripPilot</h1>
        <p>智能旅行规划工作台</p>
      </div>
      <span class="mode">Demo mode</span>
    </header>

    <section class="workspace" aria-label="规划工作台预览">
      <div class="map-panel">
        <span>地图工作区</span>
      </div>
      <aside class="timeline-panel">
        <h2>行程时间轴</h2>
        <p>创建旅行后，规划结果将在这里展示。</p>
      </aside>
    </section>

    <section class="status-bar" aria-label="服务状态">
      <div v-for="service in serviceStatus" :key="service.name">
        <span class="status-dot" aria-hidden="true"></span>
        <strong>{{ service.name }}</strong>
        <span>{{ service.state }}</span>
      </div>
    </section>
  </main>
</template>

<style scoped>
:global(*) {
  box-sizing: border-box;
}

:global(body) {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  color: #17201d;
  background: #f4f6f5;
  font-family:
    Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
}

.shell {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
}

.topbar {
  min-height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 12px 24px;
  color: #f9fbfa;
  background: #183c33;
  border-bottom: 3px solid #e6b44a;
}

h1,
h2,
p {
  margin: 0;
  letter-spacing: 0;
}

h1 {
  font-size: 24px;
  line-height: 1.2;
}

.topbar p {
  margin-top: 4px;
  color: #c9d7d2;
  font-size: 13px;
}

.mode {
  color: #17201d;
  background: #e6b44a;
  padding: 5px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.workspace {
  min-height: 560px;
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(320px, 2fr);
}

.map-panel {
  display: grid;
  place-items: center;
  color: #51635e;
  background-color: #dce5e1;
  background-image:
    linear-gradient(#c9d5d0 1px, transparent 1px),
    linear-gradient(90deg, #c9d5d0 1px, transparent 1px);
  background-size: 32px 32px;
}

.timeline-panel {
  padding: 24px;
  background: #ffffff;
  border-left: 1px solid #d5dcda;
}

.timeline-panel h2 {
  font-size: 18px;
}

.timeline-panel p {
  margin-top: 12px;
  color: #64716d;
  line-height: 1.6;
}

.status-bar {
  display: flex;
  gap: 24px;
  padding: 12px 24px;
  color: #47534f;
  background: #ffffff;
  border-top: 1px solid #d5dcda;
  font-size: 13px;
}

.status-bar div {
  display: flex;
  align-items: center;
  gap: 7px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e6b44a;
}

@media (max-width: 760px) {
  .topbar {
    padding-inline: 16px;
  }

  .workspace {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(300px, 52vh) auto;
  }

  .timeline-panel {
    min-height: 220px;
    border-top: 1px solid #d5dcda;
    border-left: 0;
  }

  .status-bar {
    flex-wrap: wrap;
    padding-inline: 16px;
  }
}
</style>
