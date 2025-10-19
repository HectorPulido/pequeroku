<template>
  <div>
    <AlertStack
      :alerts="alerts"
      @pause="pauseAlert"
      @resume="resumeAlert"
      @dismiss="dismissAlert"
    />

    <LoginForm
      v-if="!isAuthenticated"
      v-model:username="login.username"
      v-model:password="login.password"
      :error="loginError"
      :is-logging-in="isLoggingIn"
      @submit="submitLogin"
    />

    <ThemeToggleButton :is-dark="isDarkTheme" @toggle="handleThemeToggle" />

    <div id="app" :class="{ hidden: !isAuthenticated }">
      <DashboardHeader
        :greeting="greeting"
        :quota-info="quotaInfo"
        :create-button-state="createButtonState"
        @refresh="refreshContainers"
        @create="openCreateModal"
      />
      <main>
        <h2 class="container-title">Containers</h2>
        <ContainerList
          section-id="container-list"
          :containers="myContainers"
          empty-message="No containers yet."
          @open-console="openConsole"
          @open-metrics="openMetrics"
          @power-on="powerOn"
          @power-off="powerOff"
          @delete="deleteContainer"
        />

        <template v-if="otherContainers.length > 0">
          <h2 class="container-title">Other containers</h2>
          <ContainerList
            section-id="other-container-list"
            :containers="otherContainers"
            empty-message="No other containers."
            @open-console="openConsole"
            @open-metrics="openMetrics"
            @power-on="powerOn"
            @power-off="powerOff"
            @delete="deleteContainer"
          />
        </template>

        <IframeModal
          wrapper-id="metrics-modal"
          baseClass="metrics-modal"
          bodyClass="metrics-body console"
          :title="metricsTitle"
          :src="metricsUrl"
          :visible="isMetricsOpen"
          fullscreen-button-id="btn-fullscreen-metrics"
          close-button-id="btn-close-metrics"
          @fullscreen="openMetricsFullScreen"
          @close="closeMetrics"
        />

        <IframeModal
          wrapper-id="console-modal"
          baseClass=""
          bodyClass="console-body console"
          :title="consoleTitle"
          :src="consoleUrl"
          :visible="isConsoleOpen"
          fullscreen-button-id="btn-fullscreen"
          close-button-id="btn-close"
          @fullscreen="openConsoleFullScreen"
          @close="closeConsole"
        />

        <CreateContainerModal
          :open="isCreateModalOpen"
          :container-types="containerTypes"
          :is-loading="isLoadingTypes"
          :container-name="containerName"
          :creating-type-id="creatingTypeId"
          :can-afford-type="canAffordType"
          :type-name="typeName"
          :type-specs="typeSpecs"
          :create-action-label="createActionLabel"
          @close="closeCreateModal"
          @update:containerName="updateContainerName"
          @select="createContainer"
        />
      </main>
    </div>

    <LoaderOverlay :active="loaderCount > 0" />
  </div>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, reactive, ref, watch, type Ref } from 'vue'
import AlertStack from './components/AlertStack.vue'
import ContainerList from './components/ContainerList.vue'
import CreateContainerModal from './components/CreateContainerModal.vue'
import DashboardHeader from './components/DashboardHeader.vue'
import IframeModal from './components/IframeModal.vue'
import LoaderOverlay from './components/LoaderOverlay.vue'
import LoginForm from './components/LoginForm.vue'
import ThemeToggleButton from './components/ThemeToggleButton.vue'
import type { AlertItem, AlertType } from './types'
import {
  ContainerSummary,
  ContainerType,
  UserData,
  isSmallScreen,
  makeApi,
  signatureFrom
} from '../services/api'
import { applyTheme, getCurrentTheme, toggleTheme, watchSystemThemeChanges } from '../utils/theme'

interface AlertTimer {
  timeout: number | null
  remaining: number
  start: number
}

const loaderRef = inject<Ref<number>>('loaderCounter', ref(0))
const loaderCount = computed(() => loaderRef.value ?? 0)

const theme = ref<'light' | 'dark'>(getCurrentTheme())
const isDarkTheme = computed(() => theme.value === 'dark')

const alerts = ref<AlertItem[]>([])
const alertTimers = new Map<number, AlertTimer>()
const alertRemoveTimers = new Map<number, number>()

const login = reactive({ username: '', password: '' })
const loginError = ref('')
const isLoggingIn = ref(false)

const isAuthenticated = ref(false)
const userData = ref<UserData | null>(null)
const alertShown = ref(false)
const containers = ref<ContainerSummary[]>([])
const lastSignature = ref<string>('')
const pollId = ref<number | null>(null)
const currentContainerId = ref<string | null>(null)

const isConsoleOpen = ref(false)
const consoleTitle = ref('Console')
const consoleUrl = ref('')
const isMetricsOpen = ref(false)
const metricsTitle = ref('Metrics')
const metricsUrl = ref('')

const containerTypes = ref<ContainerType[] | null>(null)
const isLoadingTypes = ref(false)
const isCreateModalOpen = ref(false)
const containerName = ref('')
const creatingTypeId = ref<number | null>(null)

let stopWatchTheme: (() => void) | null = null
let createModalKeyHandler: ((event: KeyboardEvent) => void) | null = null

const apiRoot = makeApi('/api')
const apiContainers = makeApi('/api/containers')
const apiContainerTypes = makeApi('/api/container-types')

const greeting = computed(() => {
  const username = userData.value?.username
  if (!username) return 'Hello User!'
  return `Hello ${username.charAt(0).toUpperCase()}${username.slice(1)}!`
})

const quotaInfo = computed(() =>
  userData.value ? JSON.stringify(userData.value, null, '\t') : 'Not available'
)

const currentCredits = computed(() => {
  if (!userData.value?.has_quota) return 0
  const credits = userData.value.quota?.credits_left
  const normalized = typeof credits === 'number' ? credits : Number(credits) || 0
  return normalized
})

const createButtonState = computed(() => {
  if (!userData.value) {
    return { text: 'Loading…', disabled: true, showIcon: false }
  }
  if (!userData.value.has_quota) {
    return { text: 'No quota', disabled: true, showIcon: false }
  }
  const credits = currentCredits.value
  const disabled = credits <= 0
  return {
    text: `New container (${credits})`,
    disabled,
    showIcon: true
  }
})

const myContainers = computed(() => {
  const username = userData.value?.username
  if (!username) return [] as ContainerSummary[]
  return containers.value.filter((c) => c.username === username)
})

const otherContainers = computed(() => {
  const username = userData.value?.username
  if (!username) return [] as ContainerSummary[]
  return containers.value.filter((c) => c.username !== username)
})

watch(
  () => isAuthenticated.value,
  (value) => {
    if (!value) {
      stopPolling()
      closeConsole()
      closeMetrics()
      isCreateModalOpen.value = false
    }
  }
)

watch(isCreateModalOpen, (open) => {
  if (open) {
    createModalKeyHandler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeCreateModal()
      }
    }
    window.addEventListener('keydown', createModalKeyHandler)
  } else if (createModalKeyHandler) {
    window.removeEventListener('keydown', createModalKeyHandler)
    createModalKeyHandler = null
  }
})

function handleThemeToggle() {
  theme.value = toggleTheme()
}

function refreshContainers() {
  void fetchContainers(false)
}

function addAlert(message: string, type: AlertType = 'info', autoClose = true) {
  const id = Math.floor(Math.random() * 1_000_000)
  const alert: AlertItem = { id, message, type, autoClose, visible: false }
  alerts.value = [...alerts.value, alert]

  if (type === 'error') {
    console.error(message)
  } else {
    console.log(message)
  }

  requestAnimationFrame(() => {
    const target = alerts.value.find((a) => a.id === id)
    if (target) target.visible = true
  })

  if (autoClose) {
    scheduleAutoClose(id)
  }

  return id
}

function scheduleAutoClose(id: number) {
  const record: AlertTimer = {
    timeout: null,
    remaining: 15_000,
    start: Date.now()
  }
  alertTimers.set(id, record)
  resumeAlert(id)
}

function pauseAlert(id: number) {
  const record = alertTimers.get(id)
  if (!record) return
  if (record.timeout) {
    clearTimeout(record.timeout)
    record.timeout = null
    record.remaining -= Date.now() - record.start
  }
}

function resumeAlert(id: number) {
  const record = alertTimers.get(id)
  if (!record) return
  if (record.timeout) return
  if (record.remaining <= 0) {
    dismissAlert(id)
    return
  }
  record.start = Date.now()
  record.timeout = window.setTimeout(() => dismissAlert(id), record.remaining)
}

function dismissAlert(id: number) {
  const record = alertTimers.get(id)
  if (record?.timeout) {
    clearTimeout(record.timeout)
  }
  alertTimers.delete(id)

  const alert = alerts.value.find((a) => a.id === id)
  if (!alert) return
  alert.visible = false

  const pendingRemoval = alertRemoveTimers.get(id)
  if (pendingRemoval) {
    clearTimeout(pendingRemoval)
  }
  const removeTimer = window.setTimeout(() => {
    alerts.value = alerts.value.filter((a) => a.id !== id)
    alertRemoveTimers.delete(id)
  }, 600)
  alertRemoveTimers.set(id, removeTimer)
}

function openConsole(container: ContainerSummary) {
  currentContainerId.value = container.id
  if (isSmallScreen()) {
    window.open(
      `/dashboard/ide/?containerId=${container.id}`,
      '_blank',
      'noopener,noreferrer'
    )
    return
  }
  consoleTitle.value = `${container.id} — ${container.name} - Editor`
  consoleUrl.value = `/dashboard/ide/?containerId=${container.id}&showHeader`
  isConsoleOpen.value = true
}

function openMetrics(container: ContainerSummary) {
  currentContainerId.value = container.id
  if (isSmallScreen()) {
    window.open(
      `/dashboard/metrics/?container=${container.id}`,
      '_blank',
      'noopener,noreferrer'
    )
    return
  }
  metricsTitle.value = `${container.id} — ${container.name} - Stats`
  metricsUrl.value = `/dashboard/metrics/?container=${container.id}&showHeader`
  isMetricsOpen.value = true
}

function openConsoleFullScreen() {
  if (!currentContainerId.value) return
  window.open(
    `/dashboard/ide/?containerId=${currentContainerId.value}`,
    '_blank',
    'noopener,noreferrer'
  )
}

function openMetricsFullScreen() {
  if (!currentContainerId.value) return
  window.open(
    `/dashboard/metrics/?container=${currentContainerId.value}`,
    '_blank',
    'noopener,noreferrer'
  )
}

function closeConsole() {
  if (!isConsoleOpen.value) return
  isConsoleOpen.value = false
  consoleUrl.value = ''
  consoleTitle.value = 'Console'
}

function closeMetrics() {
  if (!isMetricsOpen.value) return
  isMetricsOpen.value = false
  metricsUrl.value = ''
  metricsTitle.value = 'Metrics'
}

async function fetchUserData() {
  try {
    const data = await apiRoot<UserData>('/user/me/', {
      credentials: 'same-origin',
      noLoader: true,
      noAuthRedirect: true,
      noAuthAlert: true
    })
    userData.value = data
    if (!data.is_superuser && !alertShown.value) {
      alertShown.value = true
      addAlert(importantNotice, 'warning', false)
    }
  } catch (error) {
    addAlert((error as Error).message, 'error')
  }
}

async function fetchContainers(lazy = false) {
  try {
    if (!userData.value) {
      await fetchUserData()
    }
    const data = await apiContainers<ContainerSummary[] | null>('/', {
      credentials: 'same-origin',
      noLoader: true,
      noAuthRedirect: true,
      noAuthAlert: true
    })
    const sig = signatureFrom(data)
    if (lazy && sig === lastSignature.value) return
    lastSignature.value = sig
    containers.value = Array.isArray(data) ? data : []
    startPolling()
  } catch (error) {
    addAlert((error as Error).message, 'error')
  }
}

function startPolling() {
  if (pollId.value) return
  pollId.value = window.setInterval(() => {
    fetchContainers(true)
  }, 5000)
}

function stopPolling() {
  if (!pollId.value) return
  clearInterval(pollId.value)
  pollId.value = null
}

async function submitLogin() {
  if (isLoggingIn.value) return
  loginError.value = ''
  isLoggingIn.value = true
  try {
    const username = login.username.trim()
    const password = login.password.trim()
    await apiRoot('/user/login/', {
      method: 'POST',
      credentials: 'same-origin',
      noAuthRedirect: true,
      noAuthAlert: true,
      body: JSON.stringify({ username, password })
    })
    isAuthenticated.value = true
    await fetchContainers(false)
  } catch (error) {
    const message = (error as Error).message
    loginError.value = message
    addAlert(message, 'error')
  } finally {
    isLoggingIn.value = false
  }
}

function resetSession() {
  isAuthenticated.value = false
  userData.value = null
  containers.value = []
  lastSignature.value = ''
  alertShown.value = false
  stopPolling()
  closeConsole()
  closeMetrics()
  isCreateModalOpen.value = false
}

async function powerOn(container: ContainerSummary) {
  try {
    await makeApi(`/api/containers/${container.id}`)('/power_on/', {
      method: 'POST',
      credentials: 'same-origin'
    })
    await fetchContainers(false)
  } catch (error) {
    addAlert((error as Error).message, 'error')
  }
}

async function powerOff(container: ContainerSummary) {
  try {
    await makeApi(`/api/containers/${container.id}`)('/power_off/', {
      method: 'POST',
      credentials: 'same-origin',
      body: JSON.stringify({ force: false })
    })
    await fetchContainers(false)
  } catch (error) {
    addAlert((error as Error).message, 'error')
  }
}

async function deleteContainer(container: ContainerSummary) {
  if (!window.confirm(`Delete VM "${container.id} — ${container.name}"?`)) return
  try {
    await makeApi(`/api/containers/${container.id}`)('/', {
      method: 'DELETE',
      credentials: 'same-origin'
    })
    await fetchContainers(false)
  } catch (error) {
    addAlert((error as Error).message, 'error')
  }
}

function updateContainerName(value: string) {
  containerName.value = value
}

function openCreateModal() {
  if (createButtonState.value.disabled) return
  containerName.value = ''
  isCreateModalOpen.value = true
  void (async () => {
    try {
      await fetchUserData()
    } catch (error) {
      console.warn('Unable to refresh user data before creating container', error)
    }
  })()
  void ensureContainerTypes()
}

async function ensureContainerTypes() {
  if (containerTypes.value) return
  if (isLoadingTypes.value) return
  isLoadingTypes.value = true
  try {
    const types = await apiContainerTypes<ContainerType[]>('/', {
      credentials: 'same-origin',
      noLoader: true,
      noAuthRedirect: true,
      noAuthAlert: true
    })
    containerTypes.value = types ?? []
  } catch (error) {
    addAlert((error as Error).message, 'error')
  } finally {
    isLoadingTypes.value = false
  }
}

function closeCreateModal() {
  isCreateModalOpen.value = false
  creatingTypeId.value = null
}

function canAffordType(type: ContainerType) {
  if (!userData.value?.has_quota) return false
  if (typeof type.credits_cost !== 'number') return true
  return currentCredits.value >= type.credits_cost
}

function typeName(type: ContainerType) {
  return type.container_type_name || type.name || `Type #${type.id}`
}

function typeSpecs(type: ContainerType) {
  const mem = type.memory_mb ? `${type.memory_mb} MB` : ''
  const cpu = type.vcpus ? `${type.vcpus} vCPU` : ''
  const disk = type.disk_gib ? `${type.disk_gib} GiB` : ''
  return [mem, cpu, disk].filter(Boolean).join(' • ')
}

function createActionLabel(type: ContainerType) {
  if (typeof type.credits_cost === 'number') {
    return `Create (Cost: ${type.credits_cost} credits)`
  }
  return 'Create'
}

async function createContainer(type: ContainerType) {
  if (creatingTypeId.value !== null) return
  creatingTypeId.value = type.id
  try {
    const payload: Record<string, unknown> = {
      container_type: type.id
    }
    const name = containerName.value.trim()
    if (name) payload.container_name = name

    await apiContainers('/', {
      method: 'POST',
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    })

    closeCreateModal()
    await fetchContainers(false)
    try {
      await fetchUserData()
    } catch {
      // ignore secondary failure
    }
  } catch (error) {
    addAlert((error as Error).message, 'error')
  } finally {
    creatingTypeId.value = null
  }
}

const importantNotice = `
<div>
  <div>
    <div>📜 <strong>Aviso Importante (Pequeroku) – Español</strong></div>
    <div>1. Pequeroku no ofrece ningún tipo de garantía ni soporte oficial. Puedes pedir ayuda en el servidor de Discord, pero no se asegura respuesta ni solución.</div>
    <div>2. Está prohibido cualquier acto ilícito o que afecte la seguridad o estabilidad de la plataforma.</div>
    <div>3. Nada de lo que hagas en Pequeroku es privado. Todas las máquinas virtuales son accesibles y están monitoreadas por motivos de seguridad.</div>
    <div>4. El administrador se reserva el derecho de veto, tanto en la plataforma como en el servidor de Discord.</div>
    <div>5. El uso indebido de la plataforma es responsabilidad exclusiva del usuario. El administrador no se hace responsable por las acciones o consecuencias derivadas de dicho uso.</div>
    <div>6. Está prohibido el uso excesivo de recursos (ej. minería, spam, ataques). Dichas actividades pueden ser suspendidas sin previo aviso.</div>
    <div>7. El uso de Pequeroku implica la aceptación de estas condiciones. El incumplimiento puede resultar en la suspensión inmediata del acceso.</div>
  </div>
  <br />
  <div>
    <div>📜 <strong>Important Notice (Pequeroku) – English</strong></div>
    <div>1. Pequeroku provides no warranty or official support. You may ask for help on the Discord server, but no response or solution is guaranteed.</div>
    <div>2. Any illegal activity or actions that compromise the security or stability of the platform are strictly prohibited.</div>
    <div>3. Nothing you do on Pequeroku is private. All virtual machines are accessible and monitored for security purposes.</div>
    <div>4. The administrator reserves the right to veto usage, both on the platform and on the Discord server.</div>
    <div>5. Misuse of the platform is the sole responsibility of the user. The administrator is not liable for the actions or consequences derived from such misuse.</div>
    <div>6. Excessive use of resources (e.g., mining, spam, attacks) is strictly prohibited and may be terminated without prior notice.</div>
    <div>7. Use of Pequeroku implies acceptance of these conditions. Any violation may result in immediate suspension of access.</div>
  </div>
</div>
`

function onVisibilityChange() {
  if (document.hidden) {
    stopPolling()
  } else if (isAuthenticated.value) {
    startPolling()
  }
}

const notifyHandler = (event: Event) => {
  const custom = event as CustomEvent<{ message?: string; type?: AlertType; autoClose?: boolean }>
  if (custom.detail?.message) {
    addAlert(custom.detail.message, custom.detail.type ?? 'info', custom.detail.autoClose ?? true)
  }
}

const unauthorizedHandler = () => {
  resetSession()
}

const themeChangeHandler = (event: Event) => {
  const custom = event as CustomEvent<{ theme?: 'light' | 'dark' }>
  if (custom.detail?.theme) {
    theme.value = custom.detail.theme
  }
}

onMounted(() => {
  theme.value = applyTheme()
  stopWatchTheme = watchSystemThemeChanges((next) => {
    theme.value = next
  })

  window.addEventListener('notify:alert', notifyHandler as EventListener)
  window.addEventListener('auth:unauthorized', unauthorizedHandler)
  window.addEventListener('themechange', themeChangeHandler as EventListener)
  document.addEventListener('visibilitychange', onVisibilityChange)

  ;(window as typeof window & {
    addAlert?: typeof addAlert
    notifyAlert?: typeof addAlert
  }).addAlert = addAlert
  ;(window as typeof window & {
    addAlert?: typeof addAlert
    notifyAlert?: typeof addAlert
  }).notifyAlert = addAlert

  void (async () => {
    try {
      await apiContainers('/', {
        credentials: 'same-origin',
        noAuthRedirect: true,
        noAuthAlert: true
      })
      isAuthenticated.value = true
      await fetchContainers(false)
    } catch {
      isAuthenticated.value = false
    }
  })()

})

onUnmounted(() => {
  window.removeEventListener('notify:alert', notifyHandler as EventListener)
  window.removeEventListener('auth:unauthorized', unauthorizedHandler)
  window.removeEventListener('themechange', themeChangeHandler as EventListener)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  if (createModalKeyHandler) {
    window.removeEventListener('keydown', createModalKeyHandler)
    createModalKeyHandler = null
  }
  alertTimers.forEach((timer) => {
    if (timer.timeout) clearTimeout(timer.timeout)
  })
  alertRemoveTimers.forEach((timeout) => clearTimeout(timeout))
  if (stopWatchTheme) {
    stopWatchTheme()
    stopWatchTheme = null
  }
  stopPolling()
})
</script>

<style scoped>
.alert {
  transition: opacity 0.6s ease;
  opacity: 0;
}

.alert.visible {
  opacity: 1;
}

.empty-placeholder {
  padding: 1rem;
  text-align: center;
  font-style: italic;
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.6);
  z-index: 30;
}

.metrics-modal {
  display: flex;
  flex-direction: column;
}
</style>
