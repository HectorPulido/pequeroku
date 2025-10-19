<template>
  <div id="alert-box">
    <div
      v-for="alert in alerts"
      :key="alert.id"
      :id="`alert-${alert.id}`"
      :class="['alert', alert.type, { visible: alert.visible }]"
      @mouseenter="alert.autoClose && emit('pause', alert.id)"
      @mouseleave="alert.autoClose && emit('resume', alert.id)"
    >
      <div class="alert-message" v-html="alert.message"></div>
      <span class="closebtn" @click="emit('dismiss', alert.id)">&times;</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { AlertItem } from '@/dashboard/types'

defineProps<{ alerts: AlertItem[] }>()

const emit = defineEmits<{
  (e: 'pause', id: number): void
  (e: 'resume', id: number): void
  (e: 'dismiss', id: number): void
}>()
</script>
