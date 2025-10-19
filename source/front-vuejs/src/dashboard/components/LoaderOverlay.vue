<template>
  <div id="global-loader" class="loader-overlay" :class="{ hidden: !active }">
    <div class="loader-backdrop"></div>
    <div class="loader-spinner"></div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ active: boolean }>()
</script>
