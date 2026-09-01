import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import { createTripPilotRouter } from './app/router'
import './main.css'

const app = createApp(App)

app.use(createPinia())
app.use(createTripPilotRouter())
app.mount('#app')
