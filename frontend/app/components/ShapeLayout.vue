<template>
  <main class="layout">
    <div class="row">
      <RoundedShape variant="tall" />
      <div class="stack">
        <RoundedShape variant="square" />
        <RoundedShape variant="square" />
        <RoundedShape variant="square" />
      </div>
    </div>
  </main>
</template>

<style scoped>
.layout {
  --avail-h: calc(100vh - var(--header-h) - 2 * var(--pad));
  --sq-h: calc((var(--avail-h) - 2 * var(--gap)) / 3);
  --sq-w: calc((100vw - 2 * var(--pad) - var(--gap)) / 1.7);
  --tall-w: calc(var(--sq-w) * 0.7);
  --radius: calc(min(var(--sq-w), var(--sq-h)) * 0.13);

  flex: 1 1 auto;
  min-height: 0;
  padding: var(--pad);
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
@supports (height: 100dvh) {
  .layout { --avail-h: calc(100dvh - var(--header-h) - 2 * var(--pad)); }
}
.row { display: flex; gap: var(--gap); align-items: stretch; }
.stack { display: flex; flex-direction: column; gap: var(--gap); }
</style>
