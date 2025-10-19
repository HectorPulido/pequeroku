import { createApp, ref } from 'vue'
import App from './App.vue'
import './assets/css/themes.css'
import './assets/css/base.css'
import './assets/css/styles.css'

const loaderCounter = ref(0)

const originalFetch = window.fetch.bind(window)

interface ExtendedRequestInit extends RequestInit {
  noLoader?: boolean
}

window.fetch = async (input: RequestInfo | URL, init: ExtendedRequestInit = {}) => {
  const { noLoader, ...rest } = init
  if (!noLoader) {
    loaderCounter.value += 1
  }
  try {
    return await originalFetch(input, rest)
  } finally {
    if (!noLoader) {
      loaderCounter.value = Math.max(0, loaderCounter.value - 1)
    }
  }
}

const app = createApp(App)

app.provide('loaderCounter', loaderCounter)

app.mount('#app')
