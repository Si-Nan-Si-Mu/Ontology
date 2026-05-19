<script setup>
import PoLoading from '@/components/PoLoading.vue'

defineProps({
  show: { type: Boolean, default: false },
  label: { type: String, default: '加载中…' },
  /** 盖住整个视口（用于长耗时导入） */
  fullscreen: { type: Boolean, default: false },
})
</script>

<template>
  <Transition name="po-fade">
    <div
      v-if="show"
      class="po-loading-overlay"
      :class="{ 'po-loading-overlay--fullscreen': fullscreen }"
    >
      <PoLoading :label="label" :inline="false" size="lg" />
    </div>
  </Transition>
</template>
