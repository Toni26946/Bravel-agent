import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'

// Valjci — mjerenje kočnica preko mobitela (Toni 19.11.2026.):
// upišu se vozila → shema osovina → stisne se osovina koja se mjeri (i „Ručna") →
// sila se vidi uživo, rezultat ostaje na toj osovini dok se ne stisne druga.
// Završetak: u nalog idu operacije SAMO za osovine koje nisu dobre.

const kN = (n) => (n / 1000).toLocaleString('hr-HR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const PLAVO = '#1565c0'
const CRVENO = 'var(--crveno, #c62828)'
const ZELENO_BG = '#e8f5e9'
const ZELENO = '#2e7d32'

function Razlika({ m, sitno }) {
  if (!m) return null
  return (
    <span style={{
      display: 'inline-block', padding: sitno ? '1px 8px' : '2px 10px', borderRadius: 999, fontSize: sitno ? 12 : 13, fontWeight: 700,
      background: m.losa ? CRVENO : ZELENO_BG, color: m.losa ? '#fff' : ZELENO,
    }}>razlika {Math.round(m.razlika)} %</span>
  )
}

function Traka({ vrijednost, max, desno }) {
  const pct = Math.max(0, Math.min(100, Math.round((vrijednost / Math.max(max, 1)) * 100)))
  return (
    <div style={{ height: 12, borderRadius: 6, background: '#e5e7eb', overflow: 'hidden', display: 'flex', justifyContent: desno ? 'flex-start' : 'flex-end' }}>
      <div style={{ width: `${pct}%`, background: PLAVO, transition: 'width .3s' }} />
    </div>
  )
}

// Sila uživo na odabranoj osovini: velika najveća sila + traka trenutne sile.
function Uzivo({ u }) {
  const vrh = Math.max(u.max_l, u.max_d, 8000)
  const razlika = Math.max(u.max_l, u.max_d) ? Math.round(Math.abs(u.max_l - u.max_d) / Math.max(u.max_l, u.max_d) * 100) : null
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 22, fontWeight: 800 }}>
        <span>{kN(u.max_l)}</span><span>{kN(u.max_d)}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, margin: '4px 0' }}>
        <Traka vrijednost={u.l} max={vrh} />
        <Traka vrijednost={u.d} max={vrh} desno />
      </div>
      <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--muted)' }}>
        kN · uživo{razlika !== null ? ` · razlika ${razlika} %` : ''}
      </div>
    </div>
  )
}

function Rezultat({ m, naslov }) {
  if (!m) return null
  return (
    <div style={{ marginTop: 2 }}>
      {naslov && <div style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center' }}>{naslov}</div>}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 18, fontWeight: 800 }}>{kN(m.l)}</span>
        <Razlika m={m} sitno />
        <span style={{ fontSize: 18, fontWeight: 800 }}>{kN(m.d)}</span>
      </div>
    </div>
  )
}

function Osovina({ o, odabrana, rucna, uzivo, onOdaberi, onRucna, zavrseno }) {
  const mjeriSe = odabrana && uzivo
  return (
    <div onClick={zavrseno ? undefined : onOdaberi} style={{
      display: 'grid', gridTemplateColumns: '64px minmax(0,1fr) 72px', gap: 8, alignItems: 'center',
      padding: 10, marginBottom: 8, borderRadius: 10, background: 'var(--kartica, #fff)', cursor: zavrseno ? 'default' : 'pointer',
      border: odabrana ? `3px solid ${PLAVO}` : '1px solid #d1d5db',
    }}>
      <div>
        <div style={{ fontSize: 17, fontWeight: 800 }}>{o.br}. os.</div>
        <div style={{ fontSize: 12, color: odabrana ? PLAVO : 'var(--muted)', fontWeight: odabrana ? 700 : 400 }}>
          {odabrana ? (mjeriSe ? 'mjeri se…' : `koči — ${rucna ? 'ručna' : 'radna'}`) : (o.radna || o.rucna ? 'izmjereno' : 'stisni')}
        </div>
      </div>
      <div style={{ minWidth: 0 }}>
        {mjeriSe ? <Uzivo u={uzivo} /> : (
          <>
            {o.radna ? <Rezultat m={o.radna} /> : <div style={{ textAlign: 'center', fontSize: 13, color: 'var(--muted)' }}>{o.rucna ? '' : 'radna nije izmjerena'}</div>}
            {o.rucna && <Rezultat m={o.rucna} naslov="ručna" />}
          </>
        )}
      </div>
      <button className="btn ghost" disabled={zavrseno}
        onClick={(e) => { e.stopPropagation(); onRucna() }}
        style={{
          width: 72, margin: 0, padding: '8px 4px', fontSize: 13, fontWeight: 700,
          ...(odabrana && rucna ? { background: '#fff3cd', borderColor: '#e0a800', color: '#7a5600' } : {}),
        }}>Ručna{odabrana && rucna ? ' ✓' : ''}</button>
    </div>
  )
}

function Pocetak({ onKreni }) {
  const [kamion, setKamion] = useState('')
  const [prikolica, setPrikolica] = useState('')
  const [osovine, setOsovine] = useState(null)   // {gb: ''} kad vrsta nije poznata
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const samoBroj = (v) => v.replace(/\D/g, '')

  const kreni = async () => {
    if (!kamion) { setGreska('Upiši GB kamiona.'); return }
    setRadi(true); setGreska('')
    try {
      const os = osovine ? Object.fromEntries(Object.entries(osovine).map(([g, n]) => [g, parseInt(n, 10) || 0])) : null
      if (os && Object.values(os).some((n) => !n)) { setGreska('Upiši broj osovina.'); return }
      const r = await api.valjciNova({ kamion_gb: kamion, prikolica_gb: prikolica || null, osovine: os })
      if (r.treba_osovine) { setOsovine(Object.fromEntries(r.treba_osovine.map((g) => [g, '']))); return }
      onKreni(r)
    } catch (e) { setGreska(e.message) } finally { setRadi(false) }
  }

  const polje = { margin: 0, padding: '14px 16px', fontSize: 28, fontWeight: 800, textAlign: 'center' }
  return (
    <div className="card">
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 10 }}>Koja vozila idu na valjke?</div>
      <label style={{ fontSize: 13, color: 'var(--muted)' }}>GB kamiona</label>
      <input value={kamion} inputMode="numeric" autoFocus placeholder="425" style={polje}
        onChange={(e) => { setKamion(samoBroj(e.target.value)); setOsovine(null); setGreska('') }} />
      <label style={{ fontSize: 13, color: 'var(--muted)', display: 'block', marginTop: 10 }}>GB prikolice (ako ima)</label>
      <input value={prikolica} inputMode="numeric" placeholder="200" style={polje}
        onChange={(e) => { setPrikolica(samoBroj(e.target.value)); setOsovine(null); setGreska('') }}
        onKeyDown={(e) => { if (e.key === 'Enter') kreni() }} />
      {osovine && Object.keys(osovine).map((g) => (
        <div key={g} style={{ marginTop: 10 }}>
          <label style={{ fontSize: 13, color: 'var(--muted)' }}>GB {g} — ne znam vrstu vozila. Koliko ima osovina?</label>
          <input value={osovine[g]} inputMode="numeric" style={{ ...polje, fontSize: 22 }}
            onChange={(e) => setOsovine({ ...osovine, [g]: samoBroj(e.target.value).slice(0, 1) })} />
        </div>
      ))}
      <button className="btn" disabled={radi} style={{ marginTop: 14, fontSize: 18, padding: '14px 0' }} onClick={kreni}>Kreni</button>
      {greska && <div style={{ color: CRVENO, marginTop: 8 }}>{greska}</div>}
    </div>
  )
}

export default function Valjci() {
  const [s, setS] = useState(undefined)          // undefined = učitavam, null = nema mjerenja
  const [greska, setGreska] = useState('')
  const [kraj, setKraj] = useState(null)         // popis upisanih operacija nakon završetka
  const [radi, setRadi] = useState(false)
  const zadnjiOdabir = useRef(0)

  useEffect(() => { api.valjciAktivna().then(setS).catch((e) => { setGreska(e.message); setS(null) }) }, [])

  // Osvježavanje svake sekunde dok mjerenje traje (sila uživo + novi rezultati).
  const osvjezi = useCallback(async () => {
    if (!s || s.zavrsena || document.hidden) return
    const od = zadnjiOdabir.current
    try {
      const n = await api.valjciSesija(s.id)
      if (od === zadnjiOdabir.current) setS(n)   // ne pregazi upravo stisnutu osovinu
    } catch { /* idući put */ }
  }, [s])
  useEffect(() => {
    if (!s || s.zavrsena) return undefined
    const id = setInterval(osvjezi, 1000)
    return () => clearInterval(id)
  }, [s, osvjezi])

  const odaberi = async (vozilo, osovina, rucna) => {
    zadnjiOdabir.current += 1
    setS({ ...s, odabrano_vozilo: vozilo, odabrana_osovina: osovina, rucna })   // odmah na ekranu
    try { setS(await api.valjciOdabir(s.id, { vozilo, osovina, rucna })) } catch (e) { setGreska(e.message) }
  }

  const zavrsi = async () => {
    if (!window.confirm('Završiti test? U nalog idu operacije za osovine koje nisu dobre.')) return
    setRadi(true)
    try { const r = await api.valjciZavrsi(s.id); setKraj(r.operacije || []); setS(r) } catch (e) { setGreska(e.message) } finally { setRadi(false) }
  }

  if (s === undefined) return <Layout naslov="Valjci" nazad={true}><Spinner /></Layout>

  return (
    <Layout naslov="Valjci — test kočnica" nazad={true}>
      <div style={{ maxWidth: 520, margin: '0 auto' }}>
        {!s ? <Pocetak onKreni={(n) => { setKraj(null); setS(n) }} /> : (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '4px 0 10px' }}>
              <span style={{ fontSize: 13, color: 'var(--muted)' }}>{new Date(s.pocetak).toLocaleDateString('hr-HR')}</span>
              {!s.zavrsena && (
                <span style={{ fontSize: 12, fontWeight: 700, padding: '3px 10px', borderRadius: 999,
                  background: s.spojeno ? ZELENO_BG : '#fdecea', color: s.spojeno ? ZELENO : CRVENO }}>
                  {s.spojeno ? '● valjci spojeni' : '● računalo s valjcima se ne javlja'}
                </span>
              )}
            </div>
            {s.vozila.map((v, vi) => (
              <div key={v.gb} style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', margin: '0 0 6px' }}>
                  <span style={{ fontSize: 16, fontWeight: 800 }}>GB {v.gb}{v.vrsta ? ` · ${v.vrsta}` : ''}</span>
                  {v.nalog && <Link to={`/nalozi/${v.nalog.id}`} style={{ fontSize: 13 }}>nalog {v.nalog.broj}{v.nalog.novi ? ' (novi)' : ''}</Link>}
                </div>
                {v.osovine.map((o) => {
                  const odabrana = vi === s.odabrano_vozilo && o.br === s.odabrana_osovina && !s.zavrsena
                  return (
                    <Osovina key={o.br} o={o} odabrana={odabrana} rucna={s.rucna} uzivo={odabrana ? s.uzivo : null}
                      zavrseno={!!s.zavrsena}
                      onOdaberi={() => { if (!odabrana) odaberi(vi, o.br, false) }}
                      onRucna={() => odaberi(vi, o.br, !(odabrana && s.rucna))} />
                  )
                })}
              </div>
            ))}
            {!s.zavrsena ? (
              <button className="btn" disabled={radi} style={{ fontSize: 17, padding: '14px 0' }} onClick={zavrsi}>Završi test</button>
            ) : (
              <div className="card">
                <div style={{ fontSize: 16, fontWeight: 800 }}>Test završen</div>
                <div style={{ fontSize: 14, color: 'var(--muted)', margin: '4px 0 8px' }}>
                  {kraj === null ? 'Rezultati su u nalogu.' : kraj.length ? 'U nalog upisano:' : 'Sve osovine su dobre — u nalog nije upisana nijedna operacija.'}
                </div>
                {(kraj || []).map((x) => <div key={x} style={{ fontSize: 14, marginBottom: 4 }}>• {x}</div>)}
                <button className="btn" style={{ marginTop: 10 }} onClick={() => { setKraj(null); setS(null) }}>Novo mjerenje</button>
              </div>
            )}
            {greska && <div style={{ color: CRVENO, marginTop: 8 }}>{greska}</div>}
          </>
        )}
      </div>
    </Layout>
  )
}
