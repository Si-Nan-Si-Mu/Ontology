<script setup>
defineProps({
  /** 说明文字，如「加载中…」 */
  label: { type: String, default: '' },
  /** sm | md | lg */
  size: { type: String, default: 'md' },
  /** false 时垂直居中块，适合 overlay */
  inline: { type: Boolean, default: true },
})
</script>

<template>
  <span
    class="po-loading"
    :class="[`po-loading--${size}`, { 'po-loading--block': !inline }]"
    role="status"
    aria-live="polite"
  >
    <span class="po-loading__spinner" aria-hidden="true" />
    <span v-if="label" class="po-loading__label">{{ label }}</span>
  </span>
</template>
