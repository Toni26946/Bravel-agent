import { useEffect, useRef, useState } from 'react'

// Editor poslikane fotografije: prikaže sliku i pusti korisnika da PRSTOM (ili mišem)
// crveno zaokruži / označi što je slikao, pa vrati označenu sliku kao JPEG File.
// Namijenjeno ponovnoj upotrebi (narudžbe dijelova, štete, prijave kvara…).
// Bez vanjskih biblioteka — obično <canvas>.
export default function SlikaEditor({ file, onGotovo, onOdustani }) {
  const platnoRef = useRef(null)
  const bazaRef = useRef(null)        // mala offscreen kopija slike (bez crteža) — štedi memoriju
  const crtaRef = useRef(false)
  const potezeRef = useRef([])        // povijest poteza (za „poništi"): svaki potez = niz točaka {x,y}
  const [spreman, setSpreman] = useState(false)
  const [salje, setSalje] = useState(false)

  const MAX = 1200                     // najdulja stranica platna (server svejedno dodatno smanji)
  const BOJA = '#ff2b2b'

  useEffect(() => {
    // VAŽNO za mobitele: NE učitavamo punu fotku preko base64 (readAsDataURL) i NE
    // držimo je u memoriji — to zna srušiti preglednik („nema dovoljno memorije").
    // Umjesto toga: objectURL → skaliranu kopiju nacrtamo na malo offscreen platno,
    // pa punu sliku ODMAH otpustimo (revoke + ispusti referencu). Crtamo onda iz te kopije.
    const objURL = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      let w = img.naturalWidth || img.width, h = img.naturalHeight || img.height
      const s = Math.min(1, MAX / Math.max(w, h))
      w = Math.max(1, Math.round(w * s)); h = Math.max(1, Math.round(h * s))
      const off = document.createElement('canvas')
      off.width = w; off.height = h
      off.getContext('2d').drawImage(img, 0, 0, w, h)   // skaliraj u malu kopiju
      bazaRef.current = off
      img.onload = null; img.src = ''                    // otpusti punu sliku iz memorije
      URL.revokeObjectURL(objURL)
      const c = platnoRef.current
      if (!c) return
      c.width = w; c.height = h
      potezeRef.current = []
      nacrtaj()
      setSpreman(true)
    }
    img.onerror = () => { URL.revokeObjectURL(objURL); onOdustani && onOdustani() }
    img.src = objURL
    return () => { try { URL.revokeObjectURL(objURL) } catch (e) { /* već otpušten */ } }
  }, [file])

  const debljina = () => {
    const c = platnoRef.current
    return Math.max(4, Math.round((c ? c.width : 600) / 110))
  }

  const nacrtaj = () => {
    const c = platnoRef.current
    if (!c) return
    const g = c.getContext('2d')
    g.clearRect(0, 0, c.width, c.height)
    if (bazaRef.current) g.drawImage(bazaRef.current, 0, 0, c.width, c.height)
    const lw = debljina()
    g.strokeStyle = BOJA; g.lineWidth = lw; g.lineCap = 'round'; g.lineJoin = 'round'
    for (const potez of potezeRef.current) {
      if (!potez.length) continue
      g.beginPath()
      g.moveTo(potez[0].x, potez[0].y)
      for (let i = 1; i < potez.length; i++) g.lineTo(potez[i].x, potez[i].y)
      g.stroke()
      if (potez.length === 1) {   // samo klik/dodir = mala točka
        g.beginPath(); g.arc(potez[0].x, potez[0].y, lw * 0.9, 0, Math.PI * 2); g.fillStyle = BOJA; g.fill()
      }
    }
  }

  const tocka = (e) => {
    const c = platnoRef.current, r = c.getBoundingClientRect()
    return {
      x: (e.clientX - r.left) * (c.width / r.width),
      y: (e.clientY - r.top) * (c.height / r.height),
    }
  }
  const pocni = (e) => { e.preventDefault(); crtaRef.current = true; potezeRef.current.push([tocka(e)]); nacrtaj() }
  const pomak = (e) => {
    if (!crtaRef.current) return
    e.preventDefault()
    potezeRef.current[potezeRef.current.length - 1].push(tocka(e))
    nacrtaj()
  }
  const dizi = () => { crtaRef.current = false }

  const ponisti = () => { potezeRef.current.pop(); nacrtaj() }
  const ocisti = () => { potezeRef.current = []; nacrtaj() }

  const spremi = () => {
    const c = platnoRef.current
    if (!c) return
    setSalje(true)
    c.toBlob((blob) => {
      if (!blob) { setSalje(false); return }
      const osnova = (file.name || 'slika').replace(/\.[^.]+$/, '')
      onGotovo(new File([blob], osnova + '.jpg', { type: 'image/jpeg' }))
    }, 'image/jpeg', 0.9)
  }

  const imaCrtez = potezeRef.current.length > 0

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.72)', zIndex: 9999,
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  padding: 12, boxSizing: 'border-box' }}>
      <div style={{ color: '#fff', fontWeight: 700, marginBottom: 8, fontSize: 15 }}>
        ✏️ Zaokruži prstom što si slikao
      </div>
      <canvas
        ref={platnoRef}
        onPointerDown={pocni} onPointerMove={pomak} onPointerUp={dizi} onPointerLeave={dizi} onPointerCancel={dizi}
        style={{ maxWidth: '100%', maxHeight: '62vh', touchAction: 'none', background: '#000',
                 borderRadius: 8, boxShadow: '0 4px 24px rgba(0,0,0,.5)', cursor: 'crosshair' }}
      />
      {!spreman && <div style={{ color: '#fff', marginTop: 10 }}>Učitavam sliku…</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap', justifyContent: 'center' }}>
        <button className="btn mali" type="button" onClick={ponisti} disabled={!imaCrtez || salje}>↶ Poništi</button>
        <button className="btn mali" type="button" onClick={ocisti} disabled={!imaCrtez || salje}>Očisti</button>
        <button className="btn mali" type="button" onClick={onOdustani} disabled={salje}>Odustani</button>
        <button className="btn" type="button" onClick={spremi} disabled={!spreman || salje}>
          {salje ? 'Spremam…' : (imaCrtez ? '✓ Spremi s oznakom' : '✓ Spremi')}
        </button>
      </div>
    </div>
  )
}
