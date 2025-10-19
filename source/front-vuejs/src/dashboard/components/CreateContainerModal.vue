<template>
  <div
    id="create-container-modal"
    class="modal-overlay"
    :class="{ hidden: !open }"
    @click.self="emit('close')"
  >
    <div class="console-header console">
      <span id="create-title">Create container</span>
      <div>
        <button id="btn-close-create" class="top-btn" @click="emit('close')">
          <i class="iconoir-xmark-circle"></i>
        </button>
      </div>
    </div>
    <div id="create-modal-body" class="console-body console">
      <div style="margin-bottom: 0.75rem">
        <input
          type="text"
          id="container-name-input"
          :value="containerName"
          placeholder="Container name (Optional)"
          style="
            width: 100%;
            padding: 0.5rem;
            margin-top: 0.25rem;
            border: 1px solid var(--button-border);
            border-radius: 4px;
            background: var(--console-bg);
            color: var(--console-fg);
          "
          @input="emit('update:containerName', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div v-if="isLoading">Loading container types…</div>
      <div v-else-if="containerTypes && containerTypes.length === 0">
        No container types available
      </div>
      <div v-else-if="containerTypes" class="container-grid">
        <div
          v-for="type in containerTypes"
          :key="type.id"
          class="container-card container-type-card"
        >
          <h3>{{ typeName(type) }}</h3>
          <p>{{ typeSpecs(type) }}</p>
          <button
            :data-type-id="type.id"
            :disabled="!canAffordType(type) || creatingTypeId === type.id"
            @click="emit('select', type)">
            <i class="mod-iconoir iconoir-plus-circle"></i>
            {{ creatingTypeId === type.id ? 'Creating…' : createActionLabel(type) }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ContainerType } from '@/services/api'

defineProps<{
  open: boolean
  containerTypes: ContainerType[] | null
  isLoading: boolean
  containerName: string
  creatingTypeId: number | null
  canAffordType: (type: ContainerType) => boolean
  typeName: (type: ContainerType) => string
  typeSpecs: (type: ContainerType) => string
  createActionLabel: (type: ContainerType) => string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:containerName', name: string): void
  (e: 'select', type: ContainerType): void
}>()
</script>
