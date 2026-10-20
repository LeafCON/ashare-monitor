<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 18 },
})
</script>

<template>
  <svg class="sf-icon" :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <template v-if="name === 'chart'">
      <path d="M4 16.5 9 11l3.2 3.2L20 7" />
      <path d="M14.5 7H20v5.5" />
    </template>
    <template v-else-if="name === 'case'">
      <rect x="3.5" y="7.5" width="17" height="12" rx="2" />
      <path d="M9 7.5V6.2A1.7 1.7 0 0 1 10.7 4.5h2.6A1.7 1.7 0 0 1 15 6.2v1.3" />
    </template>
    <template v-else-if="name === 'bell'">
      <path d="M6.2 16.5h11.6c-.7-1.1-1.3-2.2-1.3-4.2V10a4.5 4.5 0 0 0-9 0v2.3c0 2-.6 3.1-1.3 4.2Z" />
      <path d="M10 16.5a2 2 0 0 0 4 0" />
    </template>
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="7.5" />
      <path d="M12 8.2V12l2.6 1.8" />
    </template>
    <template v-else-if="name === 'list'">
      <path d="M8 7.5h11M8 12h11M8 16.5h11" />
      <path d="M4.8 7.5h.01M4.8 12h.01M4.8 16.5h.01" />
    </template>
    <template v-else-if="name === 'cash'">
      <rect x="3.5" y="6.5" width="17" height="11" rx="2" />
      <circle cx="12" cy="12" r="2.2" />
    </template>
    <template v-else-if="name === 'calendar'">
      <rect x="4" y="5.5" width="16" height="14" rx="2" />
      <path d="M8 4v3M16 4v3M4 10h16" />
    </template>
    <template v-else-if="name === 'wave'">
      <path d="M3.5 13c1.6-4 2.6-4 4.2 0s2.6 4 4.2 0 2.6-4 4.2 0 2.6 4 4.2 0" />
    </template>
    <template v-else-if="name === 'gear'">
      <path d="M10.1 3.8h3.8l.5 1.8c.5.2 1 .5 1.4.8l1.7-.8 1.9 1.9-.8 1.7c.3.4.6.9.8 1.4l1.8.5v3.8l-1.8.5c-.2.5-.5 1-.8 1.4l.8 1.7-1.9 1.9-1.7-.8c-.4.3-.9.6-1.4.8l-.5 1.8h-3.8l-.5-1.8a6 6 0 0 1-1.4-.8l-1.7.8-1.9-1.9.8-1.7a6 6 0 0 1-.8-1.4l-1.8-.5V9.9l1.8-.5c.2-.5.5-1 .8-1.4l-.8-1.7 1.9-1.9 1.7.8c.4-.3.9-.6 1.4-.8l.5-1.8Z" />
      <circle cx="12" cy="12" r="2.3" />
    </template>
    <template v-else-if="name === 'sun'">
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 4.2v1.6M12 18.2v1.6M4.2 12h1.6M18.2 12h1.6M6.5 6.5l1.1 1.1M16.4 16.4l1.1 1.1M17.5 6.5l-1.1 1.1M7.6 16.4l-1.1 1.1" />
    </template>
    <template v-else-if="name === 'moon'">
      <path d="M16.2 14.8A6.2 6.2 0 0 1 9.4 6.2 6.4 6.4 0 1 0 16.2 14.8Z" />
    </template>
    <template v-else-if="name === 'display'">
      <rect x="4" y="5" width="16" height="11" rx="2" />
      <path d="M9 19.5h6M12 16v3.5" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M19 12a7 7 0 1 1-2-4.9" />
      <path d="M19 5.2V9h-3.8" />
    </template>
    <template v-else-if="name === 'plus'">
      <path d="M12 6.5v11M6.5 12h11" />
    </template>
    <template v-else-if="name === 'close'">
      <path d="M7 7l10 10M17 7 7 17" />
    </template>
    <template v-else-if="name === 'search'">
      <circle cx="11" cy="11" r="5.5" />
      <path d="M15.2 15.2 19 19" />
    </template>
  </svg>
</template>
