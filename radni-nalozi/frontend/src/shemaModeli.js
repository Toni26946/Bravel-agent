// Gradnja low-poly 3D modela vozila iz primitiva (Three.js se predaje kao argument
// da bi se učitavao lijeno). Svaki "dio" ima jedan materijal (radi bojenja po statusu)
// i osnovnu (realističnu) boju koja se koristi kad dio nema posla.
import { ZONE } from './shemaMapiranje'

const PI2 = Math.PI / 2
const R = 0.52 // polumjer kotača

const BAZA = {
  kabina: 0x2f6fb0,
  motor: 0x565c62,
  osovine: 0x5f656c,
  kotaci: 0x24272b,
  kocnice: 0x9aa0a6,
  sasija: 0x7f858d,
  nadogradnja: 0xd7dbe0,
  spremnik: 0xb9bec3,
  sedlo: 0x3a3f45,
  hidraulika: 0x7d8388,
  elektrika: 0xf0cf4a,
}

function napraviRegistar(THREE) {
  const grupa = new THREE.Group()
  const dijelovi = {}
  const glass = { material: new THREE.MeshStandardMaterial({ color: 0x8bb7d6, roughness: 0.12, metalness: 0.1, transparent: true, opacity: 0.5 }), meshes: [] }

  const dio = (key) => {
    if (!dijelovi[key]) {
      const material = new THREE.MeshStandardMaterial({ color: BAZA[key] ?? 0xc4cbd4, roughness: 0.68, metalness: 0.16 })
      dijelovi[key] = { key, label: ZONE[key] || key, base: BAZA[key] ?? 0xc4cbd4, material, meshes: [] }
    }
    return dijelovi[key]
  }
  const add = (key, geom, pos, rot) => {
    const d = dio(key)
    const m = new THREE.Mesh(geom, d.material)
    m.position.set(pos[0], pos[1], pos[2])
    if (rot) m.rotation.set(rot[0], rot[1], rot[2])
    m.userData.partKey = key
    grupa.add(m); d.meshes.push(m)
    return m
  }
  const staklo = (geom, pos, rot) => {
    const m = new THREE.Mesh(geom, glass.material)
    m.position.set(pos[0], pos[1], pos[2])
    if (rot) m.rotation.set(rot[0], rot[1], rot[2])
    grupa.add(m); glass.meshes.push(m)
  }
  return { grupa, dijelovi, glass, add, staklo }
}

// Kotač (guma + naplatak + glavčina) na (x, z). dual = dvostruki (širi).
function kotac(THREE, add, x, z, dual) {
  const deb = dual ? 0.5 : 0.34
  add('kotaci', new THREE.CylinderGeometry(R, R, deb, 26), [x, R, z], [PI2, 0, 0])
  const smjer = z >= 0 ? 1 : -1
  const vani = smjer * (deb / 2 + 0.02)
  add('kocnice', new THREE.CylinderGeometry(0.3, 0.3, 0.06, 20), [x, R, z + vani], [PI2, 0, 0])
  add('kotaci', new THREE.CylinderGeometry(0.14, 0.14, 0.09, 12), [x, R, z + vani + smjer * 0.03], [PI2, 0, 0])
}

function osovina(THREE, add, x, poluSirina = 1.02) {
  add('osovine', new THREE.CylinderGeometry(0.09, 0.09, poluSirina * 2 + 0.1, 12), [x, R, 0], [PI2, 0, 0])
}

// --- Tegljač + poluprikolica -------------------------------------------------
function tegljacSPrikolicom(THREE) {
  const { grupa, dijelovi, glass, add, staklo } = napraviRegistar(THREE)
  const PS = 1.04 // pola širine

  // ===== TEGLJAČ (prednji dio) =====
  // šasija tegljača
  add('sasija', new THREE.BoxGeometry(4.0, 0.26, 1.2), [1.7, 0.95, 0])
  // motorni blok (ispod kabine)
  add('motor', new THREE.BoxGeometry(1.05, 0.8, 1.5), [3.35, 0.74, 0])
  // prednji branik
  add('sasija', new THREE.BoxGeometry(0.35, 0.5, 2.25), [4.12, 0.66, 0])
  // maska/grille
  add('motor', new THREE.BoxGeometry(0.14, 0.95, 1.85), [4.03, 1.45, 0])
  // farovi
  add('elektrika', new THREE.BoxGeometry(0.14, 0.28, 0.4), [4.08, 0.8, 0.82])
  add('elektrika', new THREE.BoxGeometry(0.14, 0.28, 0.4), [4.08, 0.8, -0.82])

  // kabina (tijelo + krov)
  add('kabina', new THREE.BoxGeometry(1.55, 2.05, 2.3), [3.35, 1.98, 0])
  add('kabina', new THREE.BoxGeometry(1.5, 0.3, 2.28), [3.3, 3.12, 0]) // krovni spojler
  add('kabina', new THREE.BoxGeometry(0.5, 0.1, 2.25), [4.02, 2.78, 0]) // sjenilo
  // vjetrobran + bočna stakla
  staklo(new THREE.BoxGeometry(0.1, 0.92, 2.02), [4.06, 2.28, 0])
  staklo(new THREE.BoxGeometry(0.95, 0.72, 0.06), [3.5, 2.28, 1.16])
  staklo(new THREE.BoxGeometry(0.95, 0.72, 0.06), [3.5, 2.28, -1.16])
  // retrovizori (ruka + zrcalo)
  for (const s of [1, -1]) {
    add('kabina', new THREE.BoxGeometry(0.45, 0.06, 0.06), [4.0, 2.45, s * 1.3])
    add('kabina', new THREE.BoxGeometry(0.1, 0.44, 0.16), [4.2, 2.3, s * 1.42])
  }
  // ispušna cijev
  add('motor', new THREE.CylinderGeometry(0.08, 0.08, 1.7, 10), [2.62, 1.85, 1.16])
  // spremnici (gorivo lijevo, AdBlue desno)
  add('spremnik', new THREE.CylinderGeometry(0.38, 0.38, 1.35, 16), [1.7, 0.72, -1.02], [0, 0, PI2])
  add('spremnik', new THREE.CylinderGeometry(0.26, 0.26, 0.7, 16), [1.2, 0.72, 1.06], [0, 0, PI2])
  // akumulatorska kutija
  add('elektrika', new THREE.BoxGeometry(0.45, 0.35, 0.5), [2.3, 0.75, 1.0])
  // sedlo (peta) + kingpin
  add('sedlo', new THREE.BoxGeometry(1.3, 0.12, 1.4), [0.7, 1.14, 0])
  add('sedlo', new THREE.CylinderGeometry(0.14, 0.14, 0.22, 12), [0.7, 1.3, 0])

  // osovine + kotači tegljača: prednja (single) + tandem (dual)
  osovina(THREE, add, 3.45); osovina(THREE, add, 1.0); osovina(THREE, add, 0.25)
  kotac(THREE, add, 3.45, PS, false); kotac(THREE, add, 3.45, -PS, false)
  for (const ax of [1.0, 0.25]) { kotac(THREE, add, ax, PS, true); kotac(THREE, add, ax, -PS, true) }
  // blatobrani tegljača
  add('sasija', new THREE.BoxGeometry(0.95, 0.12, 0.55), [3.45, 1.02, PS]); add('sasija', new THREE.BoxGeometry(0.95, 0.12, 0.55), [3.45, 1.02, -PS])
  add('sasija', new THREE.BoxGeometry(1.5, 0.12, 0.6), [0.62, 1.05, PS]); add('sasija', new THREE.BoxGeometry(1.5, 0.12, 0.6), [0.62, 1.05, -PS])

  // ===== POLUPRIKOLICA (stražnji dio) =====
  // sanduk / cerada
  add('nadogradnja', new THREE.BoxGeometry(6.8, 1.95, 2.5), [-3.1, 2.28, 0])
  add('nadogradnja', new THREE.BoxGeometry(0.12, 1.95, 2.5), [-6.48, 2.28, 0]) // stražnja vrata
  add('nadogradnja', new THREE.BoxGeometry(6.8, 0.12, 2.5), [-3.1, 3.28, 0])   // krov
  // šasija/greda prikolice
  add('sasija', new THREE.BoxGeometry(6.9, 0.22, 1.1), [-3.1, 1.2, 0])
  // bočne zaštite (skirt)
  add('sasija', new THREE.BoxGeometry(4.2, 0.5, 0.08), [-3.6, 0.95, 1.26]); add('sasija', new THREE.BoxGeometry(4.2, 0.5, 0.08), [-3.6, 0.95, -1.26])
  // noge za oslanjanje (landing gear)
  add('sasija', new THREE.BoxGeometry(0.14, 1.0, 0.14), [-0.7, 0.5, 0.7]); add('sasija', new THREE.BoxGeometry(0.14, 1.0, 0.14), [-0.7, 0.5, -0.7])
  // stražnji podletni branik + svjetla
  add('sasija', new THREE.BoxGeometry(0.12, 0.12, 2.1), [-6.55, 0.55, 0])
  add('elektrika', new THREE.BoxGeometry(0.12, 0.3, 0.3), [-6.5, 1.1, 0.95]); add('elektrika', new THREE.BoxGeometry(0.12, 0.3, 0.3), [-6.5, 1.1, -0.95])

  // tri osovine prikolice (sve dual)
  for (const ax of [-4.15, -4.75, -5.35]) {
    osovina(THREE, add, ax)
    kotac(THREE, add, ax, PS, true); kotac(THREE, add, ax, -PS, true)
  }
  // blatobrani prikolice
  add('sasija', new THREE.BoxGeometry(2.0, 0.12, 0.6), [-4.75, 1.05, PS]); add('sasija', new THREE.BoxGeometry(2.0, 0.12, 0.6), [-4.75, 1.05, -PS])

  return { grupa, dijelovi: Object.values(dijelovi), glass }
}

// --- Dispatcher (Faza 1: tegljač+prikolica; ostali tipovi u Fazi 2) ------
export function gradiModel(THREE, tip = 'tegljac') {
  switch (tip) {
    case 'tegljac':
    default:
      return tegljacSPrikolicom(THREE)
  }
}
