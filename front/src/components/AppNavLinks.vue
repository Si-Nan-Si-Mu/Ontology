<script setup>
import { RouterLink } from 'vue-router'

defineProps({
  items: {
    type: Array,
    required: true,
  },
  currentPath: {
    type: String,
    required: true,
  },
})

const emit = defineEmits(['afterNavigate'])

function onLinkClick() {
  emit('afterNavigate')
}
</script>

<template>
  <nav class="side-nav" aria-label="主导航">
    <RouterLink
      v-for="item in items"
      :key="item.to"
      :to="item.to"
      class="side-link"
      :class="{ 'side-link--active': currentPath === item.to }"
      @click="onLinkClick"
    >
      <span class="side-link-title">{{ item.title }}</span>
      <span class="side-link-sub">{{ item.subtitle }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.side-nav {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  flex: 1;
}

.side-link {
  text-decoration: none;
  color: #475569;
  padding: 0.55rem 0.65rem;
  border-radius: 10px;
  border: 1px solid transparent;
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  transition:
    background 0.15s,
    border-color 0.15s;
}

.side-link:hover {
  background: #f1f5f9;
}

.side-link--active {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #1e3a8a;
}

.side-link-title {
  font-size: 0.88rem;
  font-weight: 650;
}

.side-link-sub {
  font-size: 0.72rem;
  color: var(--po-muted, #64748b);
}

.side-link--active .side-link-sub {
  color: #3b82f6;
}
</style>
