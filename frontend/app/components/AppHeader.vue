<template>
  <header class="header">
    <div class="inner">
      <NuxtLink to="/" class="brand">CubeVision</NuxtLink>
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.header {
  flex: 0 0 var(--header-h);
  box-sizing: border-box;
  background: var(--header-bg);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--header-border);
}
.inner {
  height: 100%;
  padding: 0 var(--pad);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.brand {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text);
  text-decoration: none;
}
</style>
