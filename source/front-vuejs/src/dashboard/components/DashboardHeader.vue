<template>
  <header>
    <h1>PequeRoku</h1>
    <div class="user-info">
      <h3 id="user_data">{{ greeting }}</h3>
      <div>
        <div class="dropdown header-dropdown">
          <button class="header-button">
            <i class="iconoir-user"></i>
          </button>
          <div class="dropdown-content">
            <div>
              <pre id="quota_info">{{ quotaInfo }}</pre>
            </div>
          </div>
        </div>
      </div>

      <button class="header-button" id="btn-refresh" @click="emit('refresh')">
        <i class="iconoir-restart"></i>
      </button>
      <button
        class="header-button"
        id="btn-create"
        :disabled="createButtonState.disabled"
        @click="emit('create')"
      >
        <i v-if="createButtonState.showIcon" class="mod-iconoir iconoir-plus-circle"></i>
        <span>{{ createButtonState.text }}</span>
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import type { CreateButtonState } from '@/dashboard/types'

defineProps<{
  greeting: string
  quotaInfo: string
  createButtonState: CreateButtonState
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'create'): void
}>()
</script>
