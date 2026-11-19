<script setup lang="ts">
defineProps<{ variant: 'tall' | 'square' }>()
</script>

<template>
  <div class="shape" :class="variant" aria-hidden="true" />
</template>

<style scoped>
.shape {
  background: var(--shape);
  border-radius: var(--radius);
}
@supports (corner-shape: squircle) {
  .shape { corner-shape: squircle; }
}
.square { width: var(--sq-w); height: var(--sq-h); }
.tall { width: var(--tall-w); align-self: stretch; }
</style>
