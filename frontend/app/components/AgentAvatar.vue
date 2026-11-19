<script setup lang="ts">
// Presentational: the speech pipeline sets `speaking` (true only while the agent
// is talking back).
const props = defineProps<{ speaking: boolean }>()

const root = ref<HTMLElement>()
let avatar: CubeAvatar | undefined

onMounted(() => {
  avatar = createCubeAvatar(root.value!)
  avatar.setSpeaking(props.speaking)
})
onBeforeUnmount(() => avatar?.dispose())
watch(() => props.speaking, (v) => avatar?.setSpeaking(v))
</script>

<template>
  <div ref="root" class="avatar" role="img" aria-label="CubeVision agent" />
</template>

<style scoped>
.avatar { position: absolute; inset: 0; }
</style>
