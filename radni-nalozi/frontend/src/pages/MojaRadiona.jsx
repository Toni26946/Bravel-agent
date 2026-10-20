import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Prazno, Spinner, useAutoOsvjezi } from '../ui'

// Prikaz trajanja iz sekundi (h:mm:ss ili m:ss).
function trajanje(sek) {
  sek = Math.max(0, Math.floor(sek))
  const h = Math.floor(sek / 3600), m = Math.floor((sek % 3600) / 60), s = sek % 60
  const p = (x) => (x < 10 ? '0' : '') + x
  return h > 0 ? `${h}:${p(m)}:${p(s)}` : `${m}:${p(s)}`
}

// „Moja radiona" — radnik vidi SAMO svoje operacije iz plana i njima upravlja
// (potvrdi početak / nastavi / prekini). Auto-osvježava se.
export default function MojaRadiona() {
  const [ops, setOps] = useState(null)
  const [greska, setGreska] = useState('')
  const [sada, setSada] = useState(Date.now())
  const [stop, setStop] = useState(null)   // operacija za koju se otvara prekid
  const [radi, setRadi] = useState(0)       // id operacije koja se trenutno obrađuje

  const ucitaj = () => api.planMoje().then((d) => setOps(d.ops)).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])
  useAutoOsvjezi(() => api.planMoje().then((d) => setOps(d.ops)).catch(() => {}), 8000)
  useEffect(() => { const t = setInterval(() => setSada(Date.now()), 1000); return () => clearInterval(t) }, [])

  const akcija = async (fn, zid) => {
    setRadi(zid); setGreska('')
    try { await fn(); await ucitaj() } catch (e) { setGreska(e.message) } finally { setRadi(0) }
  }
  const potvrdi = (o) => akcija(() => api.planPotvrdi(o.id), o.id)
  const prekini = async (razlog) => { const o = stop; setStop(null); if (o) await akcija(() => api.planPrekini(o.id, razlog), o.id) }

  if (ops === null) return <Layout naslov="Moja radiona"><Spinner /></Layout>

  const zaPotvrdu = ops.filter((o) => o.status === 'ceka' || o.status === 'pauza')
  const uTijeku = ops.filter((o) => o.status === 'radu')
  const cekaDio = ops.filter((o) => o.status === 'dijelovi')
  const gotovo = ops.filter((o) => o.status === 'gotovo')
  const zivo = (o) => (o.akumSek || 0) + (o.startTs ? Math.max(0, (sada - o.startTs) / 1000) : 0)

  const Glava = ({ o }) => (
    <div className="naslov-red">
      <h3 style={{ margin: 0 }}>GB {o.gb} {o.hitno && <span style={{ color: 'var(--crveno)' }}>🔴</span>}</h3>
      <span className="meta">{[o.vozilo, o.reg].filter(Boolean).join(' · ')}</span>
    </div>
  )

  return (
    <Layout naslov="Moja radiona">
      {greska && <div className="greska" onClick={() => setGreska('')}>{greska}</div>}
      {ops.length === 0 && <Prazno emo="🔧" tekst="Trenutno nemaš dodijeljenih operacija." />}

      {zaPotvrdu.length > 0 && <div className="sekcija-naslov" style={{ marginTop: 0 }}>🔔 Za potvrdu ({zaPotvrdu.length})</div>}
      {zaPotvrdu.map((o) => {
        const nastavak = (o.akumSek || 0) > 0 || o.status === 'pauza'
        return (
          <div key={o.id} className="karta">
            <Glava o={o} />
            <p className="meta" style={{ margin: '4px 0 8px' }}>
              <b>{o.naziv}</b>{o.kat ? ` · ${o.kat}` : ''}
              {nastavak && o.akumSek > 0 ? ` · dosad ⏱ ${trajanje(o.akumSek)}` : ''}
            </p>
            <button className="btn" style={{ width: '100%' }} disabled={radi === o.id} onClick={() => potvrdi(o)}>
              {radi === o.id ? '…' : (nastavak ? '▶️ Nastavi' : '▶️ Potvrdi početak')}
            </button>
          </div>
        )
      })}

      {uTijeku.length > 0 && <div className="sekcija-naslov">⏱ U tijeku ({uTijeku.length})</div>}
      {uTijeku.map((o) => (
        <div key={o.id} className="karta">
          <Glava o={o} />
          <p className="meta" style={{ margin: '4px 0' }}><b>{o.naziv}</b>{o.kat ? ` · ${o.kat}` : ''}</p>
          <p style={{ fontWeight: 800, fontSize: 22, color: '#15803d', margin: '6px 0' }}>⏱ {trajanje(zivo(o))}</p>
          <button className="btn sekund" style={{ width: '100%' }} disabled={radi === o.id} onClick={() => setStop(o)}>⏹ Prekini / završi</button>
        </div>
      ))}

      {cekaDio.length > 0 && <div className="sekcija-naslov">⛔ Čeka dio ({cekaDio.length})</div>}
      {cekaDio.map((o) => (
        <div key={o.id} className="karta" style={{ opacity: 0.85 }}>
          <Glava o={o} />
          <p className="meta" style={{ margin: '4px 0' }}><b>{o.naziv}</b> · javljeno skladištu, čeka dio</p>
        </div>
      ))}

      {gotovo.length > 0 && <div className="sekcija-naslov">✅ Gotovo</div>}
      {gotovo.map((o) => (
        <div key={o.id} className="karta" style={{ opacity: 0.7 }}>
          <Glava o={o} />
          <p className="meta" style={{ margin: '4px 0' }}>{o.naziv}{o.akumSek > 0 ? ` · ⏱ ${trajanje(o.akumSek)}` : ''}</p>
        </div>
      ))}

      {stop && (
        <div className="sheet-bg" onClick={() => setStop(null)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>GB {stop.gb} · {stop.naziv}</h3>
            <p className="meta" style={{ marginBottom: 12 }}>Što je s operacijom?</p>
            <button className="btn" style={{ width: '100%' }} onClick={() => prekini('gotovo')}>✅ Gotovo</button>
            <button className="btn sekund" style={{ width: '100%', marginTop: 8 }} onClick={() => prekini('nije')}>⏸ Nije gotovo (pauza)</button>
            <button className="btn sekund" style={{ width: '100%', marginTop: 8 }} onClick={() => prekini('dijelovi')}>⛔ Nema dijelova</button>
            <button className="btn sekund" style={{ width: '100%', marginTop: 8 }} onClick={() => setStop(null)}>Odustani</button>
          </div>
        </div>
      )}
    </Layout>
  )
}
