<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: String, required: true },
  options: { type: Array, required: true },
})
const emit = defineEmits(['update:modelValue'])
const index = computed(() => Math.max(0, props.options.findIndex(item => item.id === props.modelValue)))
const thumbStyle = computed(() => ({
  width: `calc((100% - 4px) / ${props.options.length})`,
  transform: `translateX(${index.value * 100}%)`,
}))
</script>

<template>
  <div class="segment" role="tablist">
    <span class="segment-thumb" :style="thumbStyle"></span>
    <button
      v-for="item in options"
      :key="item.id"
      type="button"
      class="segment-btn"
      role="tab"
      :class="{ on: modelValue === item.id }"
      :aria-selected="modelValue === item.id"
      @click="emit('update:modelValue', item.id)"
    >{{ item.label }}</button>
  </div>
</template>
