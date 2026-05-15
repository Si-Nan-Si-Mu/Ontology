<script setup>
import { RouterView } from 'vue-router'
</script>

<template>
  <div class="shell">
    <RouterView />
  </div>
</template>

<style>
:root {
  --po-text: #1e293b;
  --po-muted: #64748b;
  --po-border: #e2e8f0;
  --po-card: #ffffff;
  --po-accent: #2563eb;
  --po-bg: #f8fafc;
}

html,
body {
  margin: 0;
  background: var(--po-bg);
  color: var(--po-text);
}
</style>
