<template>
  <div class="theme-button">
    <button id="theme-toggle" title="Theme" @click="emit('toggle')">
      <i :class="isDark ? 'iconoir-light-bulb-on' : 'iconoir-light-bulb-off'"></i>
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ isDark: boolean }>()

const emit = defineEmits<{ (e: 'toggle'): void }>()
</script>
