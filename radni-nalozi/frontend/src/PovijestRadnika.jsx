// Povijest po radniku: tko je što radio — Veljko 26.11.2026., #438.
// Odabere se radnik (ili upiše dio imena); popis gotovih poslova iz servisne povijesti
// (datum, vozilo, nalog, operacija, opis, trajanje). Klik na posao otvori nalog.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from './api'
import { datum } from './ui'

const RAZDOBLJA = [[30, '30 dana'], [90, '3 mj.'], [365, 'godina'], [0, 'sve']]

const trajanje = (min) => {
  if (!min) return ''
  const h = Math.floor(min / 60), m = min % 60
  return h ? `${h} h${m ? ` ${m} min` : ''}` : `${m} min`
}

export default function PovijestRadnika({ onZatvori }) {
  const nav = useNavigate()
  const [radnici, setRadnici] = useState([])
  const [q, setQ] = useState('')
  const [upit, setUpit] = useState('')
  const [dana, setDana] = useState(90)
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')
  const [ucitava, setUcitava] = useState(false)

  useEffect(() => { api.povijestRadnika().then((r) => setRadnici(r.radnici || [])).catch(() => {}) }, [])

  useEffect(() => {
    const u = upit.trim()
    if (!u) { setD(null); return }
    setUcitava(true); setGreska('')
    api.povijestRadnika(u, dana)
      .then(setD).catch((e) => { setD(null); setGreska(e.message) })
      .finally(() => setUcitava(false))
  }, [upit, dana])

  const poslovi = d?.poslovi || []
  return (
    <div className="sheet-bg" onClick={onZatvori}>
      <div className="sheet pvz-sheet" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <h3 style={{ margin: 0 }}>👷 Povijest radnika</h3>
          <button type="button" className="btn sekund mali" onClick={onZatvori}>✕</button>
        </div>
        <p className="meta" style={{ margin: '6px 0 8px' }}>Odaberi radnika ili upiši dio imena — vidi se što je radio, na kojem vozilu i kada.</p>
        <form onSubmit={(e) => { e.preventDefault(); setUpit(q) }} style={{ display: 'flex', gap: 6 }}>
          <input className="pretraga-input" style={{ margin: 0, flex: 1, minWidth: 0 }} list="povijest-radnici"
            placeholder="Ime radnika…" value={q}
            onChange={(e) => { setQ(e.target.value); if (radnici.includes(e.target.value)) setUpit(e.target.value) }} />
          <datalist id="povijest-radnici">{radnici.map((r) => <option key={r} value={r} />)}</datalist>
          <button type="submit" className="btn mali">Traži</button>
        </form>
        <div className="vz-filteri" style={{ marginTop: 8 }}>
          {RAZDOBLJA.map(([n, l]) => (
            <button key={n} type="button" className={'vz-fil' + (dana === n ? ' akt' : '')} onClick={() => setDana(n)}>{l}</button>
          ))}
        </div>
        <div className="pvz-lista">
          {ucitava && <p className="meta">Učitavam…</p>}
          {greska && <div className="greska">{greska}</div>}
          {!ucitava && d && poslovi.length === 0 && <p className="meta">Nema upisanih gotovih poslova za „{d.radnik}" u tom razdoblju.</p>}
          {!ucitava && poslovi.length > 0 && (
            <div className="sekcija-naslov" style={{ marginTop: 10 }}>
              „{d.radnik}" — {d.ukupno_poslova} {d.ukupno_poslova === 1 ? 'posao' : 'poslova'} · {d.vozila} {d.vozila === 1 ? 'vozilo' : 'vozila'}
              {d.ukupno_minuta ? ` · ${trajanje(d.ukupno_minuta)}` : ''}
            </div>
          )}
          {!ucitava && poslovi.map((p) => (
            <div key={p.id} className="pvz-red" style={p.nalog_id ? { cursor: 'pointer' } : undefined}
              onClick={p.nalog_id ? () => { onZatvori(); nav(`/nalozi/${p.nalog_id}`) } : undefined}>
              <div className="pvz-glavno">
                🚚 GB {p.gb}{p.operacija ? <span className="meta"> · {p.operacija}</span> : ''}
              </div>
              {p.opis && <div>{p.opis}</div>}
              <div className="meta">
                {datum(p.datum)}
                {p.minute ? ` · ${trajanje(p.minute)}` : ''}
                {p.nalog_broj ? ` · nalog ${p.nalog_broj}` : ''}
                {p.radnik && p.radnik.includes(',') ? ` · 👥 ${p.radnik}` : ''}
              </div>
            </div>
          ))}
          {d?.skraceno && <p className="meta">Prikazano zadnjih 2000 poslova — odaberi kraće razdoblje.</p>}
        </div>
      </div>
    </div>
  )
}
