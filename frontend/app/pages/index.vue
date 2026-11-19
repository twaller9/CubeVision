<script setup lang="ts">
useHead({ title: 'CubeVision' })
</script>

<template>
  <div class="page">
    <AppHeader />
    <ShapeLayout />
  </div>
</template>

<style scoped>
.page {
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
