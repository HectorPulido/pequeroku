<template>
  <section :id="sectionId">
    <div v-if="containers.length === 0" class="empty-placeholder">
      {{ emptyMessage }}
    </div>
    <div v-else>
      <div v-for="container in containers" :key="container.id">
        <div class="container-card">
          <h2>{{ container.id }} — {{ container.name }}</h2>
          <small>{{ container.username }}</small>
          -
          <small>{{ container.container_type_name }}</small>
          -
          <small>{{ formatDate(container.created_at) }}</small>
          <p>
            Status:
            <strong :id="`st-${container.id}`" :class="`status-${container.status}`">
              {{ container.status }}
            </strong>
          </p>
          <div>
            <button class="btn-edit" :hidden="container.status !== 'running'" @click="emit('open-console', container)">
              <i class="mod-iconoir iconoir-edit-pencil"></i> Open
            </button>
            <button class="btn-start" :hidden="container.status === 'running'" @click="emit('power-on', container)">
              <i class="mod-iconoir iconoir-play"></i> Start
            </button>
            <button class="btn-stop" :hidden="container.status !== 'running'" @click="emit('power-off', container)">
              <i class="mod-iconoir iconoir-pause"></i>Stop
            </button>
            <button class="btn-metrics" :hidden="container.status !== 'running'" @click="emit('open-metrics', container)">
              <i class="mod-iconoir iconoir-graph-up"></i> Metrics
            </button>
            <button class="btn-delete" @click="emit('delete', container)">
              <i class="mod-iconoir iconoir-bin-minus-in"></i> Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { ContainerSummary } from '@/services/api'

defineProps<{
  containers: ContainerSummary[]
  sectionId: string
  emptyMessage: string
}>()

const emit = defineEmits<{
  (e: 'open-console', container: ContainerSummary): void
  (e: 'open-metrics', container: ContainerSummary): void
  (e: 'power-on', container: ContainerSummary): void
  (e: 'power-off', container: ContainerSummary): void
  (e: 'delete', container: ContainerSummary): void
}>()

function formatDate(date: string) {
  try {
    return new Date(date).toLocaleString()
  } catch {
    return date
  }
}
</script>
