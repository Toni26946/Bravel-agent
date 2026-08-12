// Boje ispune po statusu (svjetlije, da linijski crtež ostane čitljiv).
const ISPUNA = { treba: '#f0a58a', djelomicno: '#f4d27a', gotovo: '#8fce9f' }
// Osnovne (neutralne) ispune po dijelu.
const BAZA = {
  nadogradnja: '#ffffff', sasija: '#ffffff', kabina: '#ffffff', motor: '#eef1f5',
  spremnik: '#eef1f5', sedlo: '#e7eaee', kotaci: '#dfe3e8', kocnice: '#c6cad0',
  elektrika: '#fff2bf', hidraulika: '#eef1f5', osovine: '#e5e8ec',
}

// Prepoznaj marku iz slobodnog teksta (za sitne prilagodbe i natpis).
function marka(v) {
  const m = (v?.marka || '').toUpperCase()
  if (m.includes('SCANIA')) return 'SCANIA'
  if (m.includes('VOLVO')) return 'VOLVO'
  if (m.includes('DAF')) return 'DAF'
  if (m.includes('MERCEDES') || m.includes('ACTROS') || m.includes('BENZ')) return 'MERCEDES'
  if (m.includes('IVECO')) return 'IVECO'
  if (m.includes('RENAULT')) return 'RENAULT'
  if (m.includes('MAN')) return 'MAN'
  return v?.marka ? v.marka.toUpperCase() : ''
}

const TRAILER_WHEELS = [130, 186, 242]
const TRACTOR_WHEELS = [905, 730, 676]

// 2D tehnički nacrt vozila (bočni prikaz). Dijelovi se boje po statusu iz naloga.
export default function ShemaCrtez2D({ nalog, statusi, selektiran, onSelect }) {
  const M = marka(nalog?.vozilo)
  const fill = (z) => (statusi[z] ? ISPUNA[statusi[z]] : (BAZA[z] || '#fff'))
  const sel = (z) => (selektiran === z ? 3 : 1.7)

  // Svojstva grupe dijela (klik + boja + debljina ruba).
  const dio = (z) => ({
    fill: fill(z),
    stroke: '#2a2f36',
    strokeWidth: sel(z),
    style: { cursor: 'pointer', transition: 'fill .15s' },
    onClick: () => onSelect(selektiran === z ? null : z),
  })

  return (
    <div className="shema-canvas shema-2d">
      <svg viewBox="0 0 1040 380" width="100%" style={{ display: 'block' }}>
        {/* tlo */}
        <line x1="20" y1="342" x2="1020" y2="342" stroke="#c2c8d0" strokeWidth="2" />

        {/* ===== POLUPRIKOLICA ===== */}
        {/* osovine/ovjes prikolice */}
        <g {...dio('osovine')}>
          <line x1={TRAILER_WHEELS[0]} y1="300" x2={TRAILER_WHEELS[2]} y2="300" strokeWidth="6" />
          {TRAILER_WHEELS.map((x) => <rect key={x} x={x - 16} y="276" width="32" height="10" rx="2" />)}
        </g>
        {/* sanduk / cerada */}
        <g {...dio('nadogradnja')}>
          <rect x="58" y="70" width="512" height="176" rx="6" />
          {Array.from({ length: 16 }).map((_, i) => (
            <line key={i} x1={78 + i * 30} y1="78" x2={78 + i * 30} y2="238" stroke="#7d8794" strokeWidth="1" />
          ))}
          <rect x="58" y="70" width="512" height="20" rx="6" />
        </g>
        {/* šasija prikolice + noge + zaštita */}
        <g {...dio('sasija')}>
          <rect x="58" y="250" width="512" height="12" rx="2" />
          <rect x="60" y="150" width="8" height="112" />
          <rect x="440" y="262" width="10" height="58" />
          <rect x="470" y="262" width="10" height="58" />
          <path d="M100 262 q0 22 22 22 h150 q22 0 22 -22" fill="none" />
        </g>

        {/* ===== TEGLJAČ ===== */}
        {/* osovine/ovjes tegljača */}
        <g {...dio('osovine')}>
          <line x1={TRACTOR_WHEELS[2]} y1="300" x2={TRACTOR_WHEELS[1]} y2="300" strokeWidth="6" />
          {TRACTOR_WHEELS.map((x) => <rect key={x} x={x - 17} y="274" width="34" height="10" rx="2" />)}
        </g>
        {/* šasija tegljača */}
        <g {...dio('sasija')}>
          <rect x="585" y="250" width="360" height="12" rx="2" />
        </g>
        {/* sedlo */}
        <g {...dio('sedlo')}>
          <path d="M600 250 l40 0 l-8 -16 l-24 0 z" />
        </g>
        {/* hidraulika (sklop iza kabine) */}
        <g {...dio('hidraulika')}>
          <rect x="806" y="214" width="26" height="36" rx="3" />
          <circle cx="819" cy="205" r="8" />
        </g>
        {/* spremnik goriva */}
        <g {...dio('spremnik')}>
          <rect x="700" y="252" width="96" height="46" rx="16" />
        </g>
        {/* ispušna cijev */}
        <g {...dio('motor')}>
          <rect x="792" y="150" width="9" height="100" rx="3" />
        </g>
        {/* kabina */}
        <g {...dio('kabina')}>
          <path d="M792 250 L792 118 Q792 100 812 99 L957 97 Q978 97 978 120 L978 250 Z" />
          {/* bočni prozor (staklo) */}
          <rect x="812" y="116" width="104" height="58" rx="5" fill="#bfe0f2" />
          {/* vrata + kvaka */}
          <line x1="922" y1="176" x2="922" y2="248" strokeWidth="1.4" />
          <rect x="905" y="200" width="12" height="4" strokeWidth="1.2" />
          {/* krovni spojler */}
          <path d="M812 99 L978 97 L978 86 Q900 80 812 90 Z" />
          {M && <text x="864" y="228" textAnchor="middle" fontSize="17" fontWeight="700" fill="#2a2f36" stroke="none">{M}</text>}
        </g>
        {/* vjetrobran (staklo) */}
        <g {...dio('kabina')}>
          <path d="M958 118 L976 120 L976 172 L945 172 L945 132 Z" fill="#bfe0f2" />
        </g>
        {/* retrovizor */}
        <g {...dio('kabina')}>
          <line x1="958" y1="126" x2="992" y2="118" strokeWidth="2" />
          <rect x="990" y="110" width="9" height="30" rx="2" />
        </g>
        {/* maska (grille) */}
        <g {...dio('motor')}>
          <rect x="944" y="196" width="32" height="54" rx="3" />
          {[0, 1, 2, 3].map((i) => <line key={i} x1="947" y1={206 + i * 11} x2="973" y2={206 + i * 11} strokeWidth="1" />)}
        </g>
        {/* branik */}
        <g {...dio('sasija')}>
          <rect x="938" y="250" width="46" height="30" rx="4" />
        </g>
        {/* farovi */}
        <g {...dio('elektrika')}>
          <rect x="942" y="228" width="16" height="16" rx="3" />
          <circle cx="948" cy="266" r="6" />
        </g>

        {/* ===== KOTAČI (gume) ===== */}
        <g {...dio('kotaci')}>
          {TRAILER_WHEELS.map((x) => <circle key={x} cx={x} cy="300" r="34" />)}
          {TRACTOR_WHEELS.map((x) => <circle key={x} cx={x} cy="300" r="39" />)}
        </g>
        {/* ===== KOČNICE (naplatci/diskovi) ===== */}
        <g {...dio('kocnice')}>
          {TRAILER_WHEELS.map((x) => <circle key={x} cx={x} cy="300" r="15" />)}
          {TRACTOR_WHEELS.map((x) => <circle key={x} cx={x} cy="300" r="17" />)}
        </g>
      </svg>
    </div>
  )
}
