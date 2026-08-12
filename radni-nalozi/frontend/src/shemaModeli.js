// Gradnja low-poly 3D modela vozila iz primitiva (Three.js se predaje kao argument
// da bi se učitavao lijeno). Svaki "dio" ima jedan materijal (radi bojenja po statusu)
// i osnovnu (realističnu) boju koja se koristi kad dio nema posla.
import { ZONE } from './shemaMapiranje'

const BAZA = {
  kabina: 0x2f6fb0,
  motor: 0x565c62,
  osovine: 0x6b7178,
  kotaci: 0x232629,
  kocnice: 0x9aa0a6,
  sasija: 0x878d95,
  spremnik: 0xb9bec3,
  sedlo: 0x3a3f45,
  hidraulika: 0x7d8388,
  elektrika: 0xf0cf4a,
}

function napraviRegistar(THREE) {
  const grupa = new THREE.Group()
  const dijelovi = {}
  const svojstva = { roughness: 0.72, metalness: 0.14 }

  const dio = (key) => {
    if (!dijelovi[key]) {
      const material = new THREE.MeshStandardMaterial({ color: BAZA[key] ?? 0xc4cbd4, ...svojstva })
      dijelovi[key] = { key, label: ZONE[key] || key, base: BAZA[key] ?? 0xc4cbd4, material, meshes: [] }
    }
    return dijelovi[key]
  }

  // geom: THREE.*Geometry; rot: [x,y,z] u radijanima
  const add = (key, geom, pos, rot) => {
    const d = dio(key)
    const m = new THREE.Mesh(geom, d.material)
    m.position.set(pos[0], pos[1], pos[2])
    if (rot) m.rotation.set(rot[0], rot[1], rot[2])
    m.userData.partKey = key
    grupa.add(m)
    d.meshes.push(m)
    return m
  }

  return { grupa, dijelovi, add }
}

const PI2 = Math.PI / 2

// Zajednički kotači (tegljač/kruti): dvije prednje + tandem straga.
function dodajKotace(THREE, add, { prednjaX = 1.9, stražnjeX = [-1.1, -1.9], polaSirina = 1.05, R = 0.55 } = {}) {
  const tyre = (x, z, deb) => add('kotaci', new THREE.CylinderGeometry(R, R, deb, 22), [x, R, z], [PI2, 0, 0])
  const rim = (x, z, vani) => add('kocnice', new THREE.CylinderGeometry(0.3, 0.3, 0.09, 18), [x, R, z + vani], [PI2, 0, 0])
  // prednja os — pojedinačni kotači
  for (const z of [polaSirina, -polaSirina]) {
    tyre(prednjaX, z, 0.36)
    rim(prednjaX, z, z > 0 ? 0.22 : -0.22)
  }
  // stražnje osovine — dvostruki kotači
  for (const ax of stražnjeX) {
    for (const z of [polaSirina, -polaSirina]) {
      tyre(ax, z, 0.56)
      rim(ax, z, z > 0 ? 0.32 : -0.32)
    }
  }
}

function dodajOsovine(THREE, add, xs = [1.9, -1.1, -1.9]) {
  for (const x of xs) {
    add('osovine', new THREE.CylinderGeometry(0.1, 0.1, 2.25, 12), [x, 0.55, 0], [PI2, 0, 0])
    // ovjes (blokovi uz osovinu)
    add('osovine', new THREE.BoxGeometry(0.5, 0.18, 0.22), [x, 0.82, 0.7])
    add('osovine', new THREE.BoxGeometry(0.5, 0.18, 0.22), [x, 0.82, -0.7])
  }
}

function dodajSvjetla(THREE, add, { prednjiX, stražnjiX }) {
  add('elektrika', new THREE.BoxGeometry(0.12, 0.26, 0.34), [prednjiX, 1.0, 0.8])
  add('elektrika', new THREE.BoxGeometry(0.12, 0.26, 0.34), [prednjiX, 1.0, -0.8])
  add('elektrika', new THREE.BoxGeometry(0.1, 0.2, 0.3), [stražnjiX, 1.0, 0.62])
  add('elektrika', new THREE.BoxGeometry(0.1, 0.2, 0.3), [stražnjiX, 1.0, -0.62])
}

function staklo(THREE, grupa) {
  const g = new THREE.MeshStandardMaterial({ color: 0x8bb7d6, roughness: 0.15, metalness: 0.1, transparent: true, opacity: 0.55 })
  return { material: g, meshes: [] }
}

// --- Tegljač (kamion s kabinom) ---------------------------------------------
function tegljac(THREE) {
  const { grupa, dijelovi, add } = napraviRegistar(THREE)

  // šasija
  add('sasija', new THREE.BoxGeometry(6.4, 0.3, 1.5), [-0.2, 0.95, 0])
  add('sasija', new THREE.BoxGeometry(0.3, 0.5, 1.5), [-3.35, 1.05, 0]) // stražnja greda
  // blatobrani straga
  add('sasija', new THREE.BoxGeometry(1.4, 0.12, 1.3), [-1.5, 1.25, 0])

  // kabina + krov
  add('kabina', new THREE.BoxGeometry(1.9, 1.9, 2.3), [2.35, 1.85, 0])
  add('kabina', new THREE.BoxGeometry(1.9, 0.24, 2.3), [2.35, 2.95, 0])
  // vjetrobran (staklo — bez statusa)
  const glass = staklo(THREE)
  const ws = new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.0, 2.02), glass.material)
  ws.position.set(3.32, 2.2, 0)
  grupa.add(ws); glass.meshes.push(ws)

  // motor (motorni prostor pod kabinom)
  add('motor', new THREE.BoxGeometry(1.1, 0.85, 1.6), [2.55, 0.78, 0])

  // spremnici (gorivo lijevo, AdBlue desno)
  add('spremnik', new THREE.CylinderGeometry(0.4, 0.4, 1.5, 16), [0.5, 0.75, -1.18], [0, 0, PI2])
  add('spremnik', new THREE.CylinderGeometry(0.28, 0.28, 0.8, 16), [0.7, 0.75, 1.2], [0, 0, PI2])

  // sedlo (peta)
  add('sedlo', new THREE.BoxGeometry(1.5, 0.12, 1.5), [-1.5, 1.18, 0])
  add('sedlo', new THREE.CylinderGeometry(0.16, 0.16, 0.28, 12), [-1.5, 1.32, 0])

  // hidraulika (mali sklop na šasiji)
  add('hidraulika', new THREE.BoxGeometry(0.5, 0.4, 0.5), [-0.2, 1.25, 0.62])

  dodajOsovine(THREE, add, [1.9, -1.1, -1.9])
  dodajKotace(THREE, add, { prednjaX: 1.9, stražnjeX: [-1.1, -1.9] })
  dodajSvjetla(THREE, add, { prednjiX: 3.34, stražnjiX: -3.48 })

  return { grupa, dijelovi: Object.values(dijelovi), glass }
}

// --- Dispatcher (Faza 1: implementiran tegljač; ostali se dodaju u Fazi 2) ---
export function gradiModel(THREE, tip = 'tegljac') {
  switch (tip) {
    case 'tegljac':
    default:
      return tegljac(THREE)
  }
}
