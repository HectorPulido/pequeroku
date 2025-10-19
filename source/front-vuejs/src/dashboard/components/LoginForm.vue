<template>
  <div id="login-container" class="login-container">
    <form id="login-form" class="login-box" @submit.prevent="emit('submit')">
      <h2>Login</h2>
      <input
        type="text"
        id="username"
        :value="username"
        placeholder="Username"
        required
        @input="emit('update:username', ($event.target as HTMLInputElement).value)"
      />
      <input
        type="password"
        id="password"
        :value="password"
        placeholder="Password"
        required
        @input="emit('update:password', ($event.target as HTMLInputElement).value)"
      />
      <button type="submit" id="btn-login" :disabled="isLoggingIn">
        {{ isLoggingIn ? 'Submitting…' : 'Submit' }}
      </button>
      <p id="login-error" class="error-message">{{ error }}</p>
    </form>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  username: string
  password: string
  error: string
  isLoggingIn: boolean
}>()

const emit = defineEmits<{
  (e: 'update:username', value: string): void
  (e: 'update:password', value: string): void
  (e: 'submit'): void
}>()
</script>
