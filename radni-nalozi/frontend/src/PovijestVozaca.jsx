// Povijest: koji je vozač vozio koje vozilo (GB) — Veljko 26.11.2026., #437.
// Upiše se garažni broj (samo brojke) ili dio imena vozača; podaci dolaze iz Flota OS-a
// (dnevne vožnje + potvrde „Da vozim"), uzastopni dani istog vozača spojeni u od–do.
import { useEffect, useState } from 'react'
import { api } from './api'
import { datum } from './ui'

const jeGb = (q) => /^\d+[a-z]?$/i.test(q.trim())

export default function PovijestVozaca({ pocetno = '', onZatvori }) {
  const [q, setQ] = useState(pocetno)
  const [upit, setUpit] = useState(pocetno)
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')
  const [ucitava, setUcitava] = useState(false)

  useEffect(() => {
    const u = upit.trim()
    if (!u) { setD(null); return }
    setUcitava(true); setGreska('')
    api.povijestVozaca(jeGb(u) ? { gb: u } : { vozac: u })
      .then(setD).catch((e) => { setD(null); setGreska(e.message) })
      .finally(() => setUcitava(false))
  }, [upit])

  const poGb = d && d.gb
  const raz = d?.razdoblja || []
  return (
    <div className="sheet-bg" onClick={onZatvori}>
      <div className="sheet pvz-sheet" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0 }}>📜 Povijest vozača</h3>
          <button type="button" className="btn sekund mali" onClick={onZatvori}>✕</button>
        </div>
        <p className="meta" style={{ margin: '6px 0 8px' }}>Upiši garažni broj (koji su vozači vozili vozilo) ili ime vozača (koja je vozila vozio).</p>
        <form onSubmit={(e) => { e.preventDefault(); setUpit(q) }} style={{ display: 'flex', gap: 6 }}>
          <input className="pretraga-input" style={{ margin: 0, flex: 1 }} autoFocus={!pocetno}
            placeholder="GB ili ime vozača…" value={q} onChange={(e) => setQ(e.target.value)} />
          <button type="submit" className="btn mali">Traži</button>
        </form>
        <div className="pvz-lista">
          {ucitava && <p className="meta">Učitavam…</p>}
          {greska && <div className="greska">{greska}</div>}
          {!ucitava && d && raz.length === 0 && <p className="meta">{d.prikolica ? 'Nema upisanih prikapčanja.' : 'Nema zapisa za zadnju godinu.'}</p>}
          {!ucitava && raz.length > 0 && (
            <div className="sekcija-naslov" style={{ marginTop: 10 }}>
              {poGb ? `GB ${d.gb} — ${d.prikolica ? 'prikapčanja (tko ju je vukao)' : 'tko je vozio'}` : `„${d.vozac}" — koja je vozila vozio`}
            </div>
          )}
          {!ucitava && raz.map((r, i) => (
            <div key={i} className="pvz-red">
              <div className="pvz-glavno">
                {poGb ? <>🧑 {r.vozac}{r.kamion_gb ? <span className="meta"> · na kamionu GB {r.kamion_gb}</span> : ''}</> : <>🚚 GB {r.gb} <span className="meta">· {r.vozac}</span></>}
              </div>
              <div className="meta">
                {r.traje ? `od ${datum(r.od)} (još traje)` : r.od === r.do ? datum(r.od) : `${datum(r.od)} – ${datum(r.do)}`}
                {` · ${r.dana} ${r.dana === 1 ? 'dan' : 'dana'}`}
                {r.km ? ` · ${Number(r.km).toLocaleString('hr-HR')} km` : ''}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
