<template>
  <div :id="wrapperId" :class="[baseClass, { hidden: !visible }]">
    <div class="console-header console">
      <span>{{ title }}</span>
      <div>
        <button :id="fullscreenButtonId" class="top-btn" @click="emit('fullscreen')">
          <i class="iconoir-expand"></i>
        </button>
        <button :id="closeButtonId" class="top-btn" @click="emit('close')">
          <i class="iconoir-xmark-circle"></i>
        </button>
      </div>
    </div>
    <div :class="bodyClass">
      <iframe v-if="visible && src" :title="title" :src="src" allowfullscreen></iframe>
    </div>
  </div>
</template>

<script setup lang="ts">
const emit = defineEmits<{
  (e: 'fullscreen'): void
  (e: 'close'): void
}>()

defineProps<{
  wrapperId: string
  baseClass: string
  bodyClass: string
  title: string
  src: string
  visible: boolean
  fullscreenButtonId: string
  closeButtonId: string
}>()
</script>
