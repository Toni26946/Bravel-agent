import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { gradiModel } from './shemaModeli'
import {
  BOJA_STATUSA, BOJA_STATUSA_CSS, OZNAKA_STATUSA, statusiZona, zonaZaKategoriju,
} from './shemaMapiranje'

const REDOSLIJED_LEGENDE = ['treba', 'djelomicno', 'gotovo', 'neutral']

// 3D shema vozila u nalogu — vrti se prstom; dijelovi se boje automatski iz operacija.
export default function Shema3D({ nalog }) {
  const mountRef = useRef(null)
  const ref = useRef({})            // three objekti izvan Reacta
  const [selektiran, setSelektiran] = useState(null)
  const tip = nalog?.vozilo?.tip || 'tegljac'

  const statusi = useMemo(() => statusiZona(nalog?.operacije || []), [nalog])

  // --- init scene (jednom) ---
  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200)
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    mount.appendChild(renderer.domElement)

    scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa4ad, 1.0))
    const dir = new THREE.DirectionalLight(0xffffff, 0.8); dir.position.set(6, 11, 7); scene.add(dir)
    const fill = new THREE.DirectionalLight(0xffffff, 0.25); fill.position.set(-6, 5, -6); scene.add(fill)

    // podloga
    const pod = new THREE.Mesh(
      new THREE.CircleGeometry(16, 56),
      new THREE.MeshStandardMaterial({ color: 0xe9edf2, roughness: 1 }),
    )
    pod.rotation.x = -Math.PI / 2; pod.position.y = 0; scene.add(pod)

    const { grupa, dijelovi, glass } = gradiModel(THREE, tip)
    scene.add(grupa)

    // Auto-kadriranje: cijeli model uvijek stane u vidno polje (i na uskom mobitelu).
    const bbox = new THREE.Box3().setFromObject(grupa)
    const centar = bbox.getCenter(new THREE.Vector3())
    const sfera = bbox.getBoundingSphere(new THREE.Sphere())
    const smjer = new THREE.Vector3(1.15, 0.6, 1.0).normalize()
    let fitAspect = 0
    const kadriraj = () => {
      const vFov = (camera.fov * Math.PI) / 180
      const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect)
      const dist = (1.18 * sfera.radius) / Math.sin(Math.min(vFov, hFov) / 2)
      camera.position.copy(centar).add(smjer.clone().multiplyScalar(dist))
      controls.target.copy(centar)
      controls.minDistance = dist * 0.4
      controls.maxDistance = dist * 2.4
      controls.update()
      fitAspect = camera.aspect
    }

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.09
    controls.maxPolarAngle = Math.PI * 0.49

    const meshesAll = dijelovi.flatMap((d) => d.meshes)
    const raycaster = new THREE.Raycaster()

    // tap (a ne rotacija) → odabir dijela
    let downXY = null
    const naDown = (e) => { downXY = { x: e.clientX, y: e.clientY, t: Date.now() } }
    const naUp = (e) => {
      if (!downXY) return
      const dx = e.clientX - downXY.x, dy = e.clientY - downXY.y
      const daleko = Math.hypot(dx, dy) > 7 || Date.now() - downXY.t > 400
      downXY = null
      if (daleko) return
      const r = renderer.domElement.getBoundingClientRect()
      const ndc = new THREE.Vector2(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        -((e.clientY - r.top) / r.height) * 2 + 1,
      )
      raycaster.setFromCamera(ndc, camera)
      const hit = raycaster.intersectObjects(meshesAll, false)[0]
      setSelektiran(hit ? hit.object.userData.partKey : null)
    }
    renderer.domElement.addEventListener('pointerdown', naDown)
    renderer.domElement.addEventListener('pointerup', naUp)

    const resize = () => {
      const w = mount.clientWidth, h = mount.clientHeight
      if (!w || !h) return
      renderer.setSize(w, h, false)
      camera.aspect = w / h; camera.updateProjectionMatrix()
      // Prvo kadriranje i pri promjeni orijentacije (veća promjena omjera).
      if (!fitAspect || Math.abs(camera.aspect - fitAspect) > 0.2) kadriraj()
    }
    resize()
    const ro = new ResizeObserver(resize); ro.observe(mount)

    let raf = 0
    const tick = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(tick) }
    tick()

    ref.current = { scene, camera, renderer, controls, dijelovi, glass, meshesAll }

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      renderer.domElement.removeEventListener('pointerdown', naDown)
      renderer.domElement.removeEventListener('pointerup', naUp)
      controls.dispose()
      scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose()
        if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose())
      })
      renderer.dispose()
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement)
      ref.current = {}
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tip])

  // --- bojenje po statusu ---
  useEffect(() => {
    const { dijelovi } = ref.current
    if (!dijelovi) return
    for (const d of dijelovi) {
      const st = statusi[d.key]
      d.material.color.setHex(st ? BOJA_STATUSA[st] : d.base)
    }
  }, [statusi])

  // --- isticanje odabranog dijela ---
  useEffect(() => {
    const { dijelovi } = ref.current
    if (!dijelovi) return
    for (const d of dijelovi) {
      const akt = d.key === selektiran
      d.material.emissive.setHex(akt ? 0x2b2f36 : 0x000000)
      d.material.emissiveIntensity = akt ? 0.6 : 0
    }
  }, [selektiran])

  const opsZone = (nalog?.operacije || []).filter((o) => zonaZaKategoriju(o.kategorija) === selektiran)
  const naziviZona = ref.current.dijelovi?.reduce((m, d) => (m[d.key] = d.label, m), {}) || {}

  return (
    <div className="shema-wrap">
      <div className="shema-canvas" ref={mountRef} style={{ touchAction: 'none' }} />
      <div className="shema-legenda">
        {REDOSLIJED_LEGENDE.map((s) => (
          <span key={s} className="shema-leg">
            <i style={{ background: BOJA_STATUSA_CSS[s] }} /> {OZNAKA_STATUSA[s]}
          </span>
        ))}
      </div>
      <p className="meta shema-uputa">Vrti prstom · dva prsta za zoom · dodirni dio za detalje</p>

      {selektiran && (
        <div className="karta shema-info">
          <div className="naslov-red">
            <h3 style={{ margin: 0 }}>{naziviZona[selektiran] || selektiran}</h3>
            <span className="bedz" style={{ background: BOJA_STATUSA_CSS[statusi[selektiran] || 'neutral'], color: '#fff' }}>
              {OZNAKA_STATUSA[statusi[selektiran] || 'neutral']}
            </span>
          </div>
          {opsZone.length === 0 ? (
            <p className="meta" style={{ marginTop: 6 }}>Nema operacija za ovaj dio u ovom nalogu.</p>
          ) : (
            <div style={{ marginTop: 6 }}>
              {opsZone.map((o) => {
                const uk = (o.zadaci || []).length
                const go = (o.zadaci || []).filter((z) => z.gotovo).length
                return (
                  <div key={o.id} className="steta-stavka">
                    <span>{o.kategorija}</span>
                    <span className="c">{uk ? `${go}/${uk}` : '—'}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
