import * as THREE from 'three'

// Ported from the cube-avatar.html prototype. Framework-free: give it a container,
// drive it with setSpeaking(), and call dispose() on teardown.

const CUBIE = 0.16
const GAPC = 0.004
const HALF = CUBIE * 1.5
const FACE = { // classic scheme, white facing the viewer
  pz: '#f4f2ee', nz: '#ffd43b', px: '#e03131', nx: '#ff8a1f', py: '#1f6feb', ny: '#2f9e44',
} as const

type Axis = 'x' | 'y'
const MOVES: { axis: Axis; layer: number }[] = [
  { axis: 'y', layer: 1 }, { axis: 'y', layer: -1 }, { axis: 'x', layer: -1 }, { axis: 'x', layer: 1 },
]
const ease = (x: number) => (x < 0.5 ? 4 * x ** 3 : 1 - (-2 * x + 2) ** 3 / 2)

export interface CubeAvatar {
  setSpeaking(v: boolean): void
  dispose(): void
}

export function createCubeAvatar(container: HTMLElement): CubeAvatar {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.toneMapping = THREE.NoToneMapping
  renderer.setClearColor(0x000000, 0) // transparent: the shape's own background shows through
  const cvs = renderer.domElement
  cvs.style.cssText = 'display:block;width:100%;height:100%;pointer-events:none'
  container.prepend(cvs)

  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 100)
  camera.position.set(0, 1.35, 10)
  camera.lookAt(0, 0, 0)
  scene.add(new THREE.HemisphereLight('#ffffff', '#cfc8e6', 1.9))
  const sun = new THREE.DirectionalLight('#ffffff', 1.5)
  sun.position.set(6, 13, 9)
  scene.add(sun)

  function glow(color: string, strength = 0.3) {
    const m = new THREE.MeshLambertMaterial({ color })
    m.onBeforeCompile = (s) => {
      s.fragmentShader = s.fragmentShader.replace(
        '#include <emissivemap_fragment>',
        `#include <emissivemap_fragment>\n totalEmissiveRadiance += diffuseColor.rgb * ${strength};`,
      )
    }
    return m
  }

  const head = new THREE.Group()
  scene.add(head)

  // ---- Cube head: 3x3 rounded black cubies with stickers, solved ----
  function roundedBox(size: number, r: number, seg = 4) {
    const g = new THREE.BoxGeometry(size, size, size, seg * 2, seg * 2, seg * 2)
    const p = g.attributes.position!
    const v = new THREE.Vector3()
    const inner = size / 2 - r
    for (let i = 0; i < p.count; i++) {
      v.fromBufferAttribute(p, i)
      const c = new THREE.Vector3(
        THREE.MathUtils.clamp(v.x, -inner, inner),
        THREE.MathUtils.clamp(v.y, -inner, inner),
        THREE.MathUtils.clamp(v.z, -inner, inner),
      )
      v.sub(c).normalize().multiplyScalar(r).add(c)
      p.setXYZ(i, v.x, v.y, v.z)
    }
    g.computeVertexNormals()
    return g
  }
  function roundedSquare(w: number, r: number) {
    const s = new THREE.Shape()
    const h = w / 2
    s.moveTo(-h + r, -h); s.lineTo(h - r, -h); s.quadraticCurveTo(h, -h, h, -h + r); s.lineTo(h, h - r); s.quadraticCurveTo(h, h, h - r, h)
    s.lineTo(-h + r, h); s.quadraticCurveTo(-h, h, -h, h - r); s.lineTo(-h, -h + r); s.quadraticCurveTo(-h, -h, -h + r, -h)
    return new THREE.ShapeGeometry(s, 6)
  }
  const cubieGeo = roundedBox(CUBIE - GAPC, 0.022)
  const stickerGeo = roundedSquare(CUBIE * 0.84, 0.02)
  const plastic = new THREE.MeshStandardMaterial({ color: '#16171b', roughness: 0.45 })
  const stickerMats = Object.fromEntries(Object.entries(FACE).map(([k, c]) => [k, glow(c, 0.22)])) as Record<keyof typeof FACE, THREE.Material>

  // Cubies never move permanently: a pivot borrows one layer per turn, then gives it back
  const cubies: { obj: THREE.Group; x: number; y: number; z: number }[] = []
  const pivot = new THREE.Group()
  head.add(pivot)
  const SURF = (CUBIE - GAPC) / 2 + 0.0008
  for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) {
    const cubie = new THREE.Group()
    cubie.position.set(x * CUBIE, y * CUBIE, z * CUBIE)
    cubie.add(new THREE.Mesh(cubieGeo, plastic))
    const add = (key: keyof typeof FACE, pos: THREE.Vector3, rot: [number, number, number]) => {
      const st = new THREE.Mesh(stickerGeo, stickerMats[key])
      st.position.copy(pos)
      st.rotation.set(...rot)
      cubie.add(st)
    }
    if (z === 1) add('pz', new THREE.Vector3(0, 0, SURF), [0, 0, 0])
    if (z === -1) add('nz', new THREE.Vector3(0, 0, -SURF), [0, Math.PI, 0])
    if (x === 1) add('px', new THREE.Vector3(SURF, 0, 0), [0, Math.PI / 2, 0])
    if (x === -1) add('nx', new THREE.Vector3(-SURF, 0, 0), [0, -Math.PI / 2, 0])
    if (y === 1) add('py', new THREE.Vector3(0, SURF, 0), [-Math.PI / 2, 0, 0])
    if (y === -1) add('ny', new THREE.Vector3(0, -SURF, 0), [Math.PI / 2, 0, 0])
    head.add(cubie)
    cubies.push({ obj: cubie, x, y, z })
  }

  // ---- Ray-Ban Meta Wayfarers ----
  const frameMat = new THREE.MeshStandardMaterial({ color: '#121314', roughness: 0.35, metalness: 0.1 })
  const lensMat = new THREE.MeshStandardMaterial({ color: '#262c38', roughness: 0.12, metalness: 0.45, transparent: true, opacity: 0.88 })
  function wayfarer(w: number, h: number, r: number) {
    const s = new THREE.Shape()
    const tw = w / 2
    const bw = w * 0.42
    s.moveTo(-tw + r, h / 2); s.lineTo(tw - r, h / 2); s.quadraticCurveTo(tw, h / 2, tw, h / 2 - r)
    s.lineTo(bw, -h / 2 + r); s.quadraticCurveTo(bw - 0.005, -h / 2, bw - r, -h / 2)
    s.lineTo(-bw + r, -h / 2); s.quadraticCurveTo(-bw + 0.005, -h / 2, -bw, -h / 2 + r)
    s.lineTo(-tw, h / 2 - r); s.quadraticCurveTo(-tw, h / 2, -tw + r, h / 2)
    return s
  }
  const glasses = new THREE.Group()
  const rims: Record<number, THREE.Mesh> = {}
  const LW = 0.15, LH = 0.095, GAP = 0.03, FZ = HALF + 0.014, EYE_Y = 0.045
  for (const side of [-1, 1]) {
    const outer = wayfarer(LW + 0.03, LH + 0.03, 0.02)
    outer.holes.push(wayfarer(LW - 0.004, LH - 0.006, 0.014))
    const rim = new THREE.Mesh(new THREE.ExtrudeGeometry(outer, { depth: 0.018, bevelEnabled: false, curveSegments: 6 }), frameMat)
    const lens = new THREE.Mesh(new THREE.ShapeGeometry(wayfarer(LW, LH, 0.016), 6), lensMat)
    const cx = side * (LW / 2 + GAP / 2 + 0.008)
    rim.position.set(cx, EYE_Y, FZ - 0.006)
    lens.position.set(cx, EYE_Y, FZ + 0.004)
    glasses.add(rim, lens)
    rims[side] = rim
    // Arm runs from the hinge back along the side of the cube
    const from = new THREE.Vector3(side * (LW + GAP / 2 + 0.035), EYE_Y + 0.02, FZ - 0.03)
    const to = new THREE.Vector3(side * (HALF + 0.014), EYE_Y + 0.02, -0.17)
    const len = from.distanceTo(to)
    const temple = new THREE.Mesh(new THREE.BoxGeometry(0.022, 0.034, len), frameMat)
    temple.position.copy(from).add(to).multiplyScalar(0.5)
    temple.rotation.y = Math.atan2(to.x - from.x, to.z - from.z)
    glasses.add(temple)
    const hinge = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.042, 0.045), frameMat)
    hinge.position.set(side * (LW + GAP / 2 + 0.03), EYE_Y + 0.02, FZ - 0.006)
    glasses.add(hinge)
  }
  const bridge = new THREE.Mesh(new THREE.BoxGeometry(GAP + 0.03, 0.022, 0.018), frameMat)
  bridge.position.set(0, EYE_Y + 0.03, FZ + 0.004)
  glasses.add(bridge)

  const camRing = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.012, 20).rotateX(Math.PI / 2), new THREE.MeshStandardMaterial({ color: '#3a3d44', metalness: 0.8, roughness: 0.25 }))
  const camGlass = new THREE.Mesh(new THREE.CircleGeometry(0.009, 20), new THREE.MeshStandardMaterial({ color: '#0a0c12', roughness: 0.05 }))
  const ledMat = new THREE.MeshBasicMaterial({ color: '#ffffff', toneMapped: false })
  const led = new THREE.Mesh(new THREE.CircleGeometry(0.0095, 20), ledMat)
  const ledBezel = new THREE.Mesh(new THREE.RingGeometry(0.0095, 0.0135, 24), new THREE.MeshStandardMaterial({ color: '#4a4d55', metalness: 0.7, roughness: 0.3 }))
  // Soft additive glow around the capture light
  const gc = document.createElement('canvas')
  gc.width = gc.height = 64
  {
    const c = gc.getContext('2d')!
    const g = c.createRadialGradient(32, 32, 0, 32, 32, 32)
    g.addColorStop(0, 'rgba(255,255,255,1)')
    g.addColorStop(0.25, 'rgba(255,250,240,0.75)')
    g.addColorStop(1, 'rgba(255,245,230,0)')
    c.fillStyle = g
    c.fillRect(0, 0, 64, 64)
  }
  const ledGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(gc), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false }))
  ledGlow.scale.setScalar(0.07)
  // Mounted on the front face of each rim's outer top corner (rim local space)
  const CX = 0.079, CY = 0.05, CZ = 0.0185
  camRing.position.set(-CX, CY, CZ)
  camGlass.position.set(-CX, CY, CZ + 0.0062)
  led.position.set(CX, CY, CZ + 0.0012)
  ledBezel.position.set(CX, CY, CZ + 0.0008)
  ledGlow.position.set(CX, CY, CZ + 0.008)
  rims[-1]!.add(camRing, camGlass)
  rims[1]!.add(ledBezel, led, ledGlow)
  head.add(glasses)

  // ---- Talking: no mouth. While speaking, a face gives a quarter turn and back ----
  let speaking = false
  let nextTwistAt = 0
  let twistStart = 0
  let twistDir = 1
  let move = MOVES[0]!
  let lastMove = -1

  function startTwist(at: number) {
    let i: number
    do { i = Math.floor(Math.random() * MOVES.length) } while (i === lastMove)
    lastMove = i
    move = MOVES[i]!
    twistDir = Math.random() < 0.5 ? 1 : -1
    pivot.rotation.set(0, 0, 0)
    for (const c of cubies) if (c[move.axis] === move.layer) pivot.add(c.obj)
    twistStart = at
  }
  function endTwist() {
    pivot.rotation.set(0, 0, 0)
    for (const c of [...pivot.children]) head.add(c) // always ends solved
    twistStart = 0
  }

  const half = 0.55
  function resize() {
    const w = Math.max(1, container.clientWidth)
    const h = Math.max(1, container.clientHeight)
    const a = w / h
    renderer.setSize(w, h, false)
    camera.left = -half * Math.max(a, 1)
    camera.right = half * Math.max(a, 1)
    camera.top = half / Math.min(a, 1)
    camera.bottom = -half / Math.min(a, 1)
    camera.updateProjectionMatrix()
  }
  const ro = new ResizeObserver(resize)
  ro.observe(container)
  resize()

  renderer.setAnimationLoop((now: number) => {
    const t = now / 1000
    if (speaking && !twistStart && now > nextTwistAt) {
      startTwist(now)
      nextTwistAt = now + 1300 + Math.random() * 1200 // every 1.3–2.5 s
    }

    // Idle sway, plus small nods while talking
    head.rotation.y = -0.05 + Math.sin(t * 0.6) * 0.3
    head.rotation.x = 0.04 + (speaking ? Math.sin(t * 7) * 0.025 : 0) + Math.sin(t * 0.9) * 0.02
    head.rotation.z = Math.sin(t * 0.7) * 0.03
    head.position.y = Math.sin(t * 1.3) * 0.01

    // Quarter turn and back (~1.2 s, cubic ease in/out)
    if (twistStart && now >= twistStart) {
      const e = (now - twistStart) / 1000
      let a = 0
      if (e < 0.4) a = ease(e / 0.4)
      else if (e < 0.8) a = 1
      else if (e < 1.2) a = 1 - ease((e - 0.8) / 0.4)
      else endTwist()
      if (twistStart) pivot.rotation[move.axis] = a * twistDir * Math.PI / 2
    }

    const pulse = 0.5 + 0.5 * Math.sin(t * 3.2)
    ledMat.color.setScalar(0.85 + 0.15 * pulse)
    ledGlow.material.opacity = 0.55 + 0.45 * pulse
    ledGlow.scale.setScalar(0.06 + 0.025 * pulse)

    renderer.render(scene, camera)
  })

  return {
    setSpeaking(v) {
      const now = performance.now()
      if (v && !speaking) nextTwistAt = now + 500 + Math.random() * 600
      // One turn right after a line ends
      if (!v && speaking && !twistStart) startTwist(now + 250)
      speaking = v
    },
    dispose() {
      renderer.setAnimationLoop(null)
      ro.disconnect()
      renderer.dispose()
      cvs.remove()
    },
  }
}
