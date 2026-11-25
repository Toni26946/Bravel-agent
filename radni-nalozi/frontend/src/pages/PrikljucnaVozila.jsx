import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useAuth } from '../auth'
import { Parkinzi, ParkingSelect } from './SpremneSlepe'

// Priključna vozila — gdje je što (Toni 25.11.2026.): JEDNA ploča umjesto
// „Slobodna" + „Spremna". Svaka prikolica/šlepa ima točno jedno stanje.
const STANJA = [
  { k: 'radiona', ikona: '🔧', naziv: 'U radioni', boja: '#1d4ed8', bg: '#e5edff' },
  { k: 'prikacena', ikona: '🔗', naziv: 'Prikačena', boja: '#047857', bg: '#dcfce7' },
  { k: 'za_upisati', ikona: '⚠', naziv: 'Za upisati', boja: '#b91c1c', bg: '#fee2e2' },
  { k: 'spremna', ikona: '🟢', naziv: 'Spremna', boja: '#15803d', bg: '#ecfdf5' },
  { k: 'slobodna', ikona: '🅿️', naziv: 'Slobodna', boja: '#0369a1', bg: '#e0f2fe' },
  { k: 'pokvarena', ikona: '🛑', naziv: 'Pokvarena', boja: '#9f1239', bg: '#ffe4e6' },
  { k: 'nepoznato', ikona: '❔', naziv: 'Ne zna se gdje je', boja: '#6b7280', bg: '#f3f4f6' },
]
const ST = Object.fromEntries(STANJA.map((s) => [s.k, s]))

const dHR = (iso) => {
  if (!iso) return ''
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso)
  if (isNaN(d)) return ''
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}.`
}
const dana = (iso) => {
  if (!iso) return null
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso)
  if (isNaN(d)) return null
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 86400000))
}
const odTxt = (iso) => {
  if (!iso) return ''
  const n = dana(iso)
  return ` · od ${dHR(iso)}${n == null ? '' : n === 0 ? ' (danas)' : ` (${n} ${n === 1 ? 'dan' : 'dana'})`}`
}
const norm = (s) => (s || '').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')

export default function PrikljucnaVozila() {
  const nav = useNavigate()
  const { korisnik } = useAuth()
  const [d, setD] = useState(null)
  const [parkinzi, setParkinzi] = useState([])
  const [greska, setGreska] = useState('')
  const [filter, setFilter] = useState('sve')
  const [q, setQ] = useState('')

  const ucitaj = () => api.prikljucna().then(setD).catch((e) => setGreska(e.message))
  const ucitajParkinge = () => api.parkinzi().then(setParkinzi).catch(() => {})
  useEffect(() => { ucitaj(); ucitajParkinge() }, [])
  useAutoOsvjezi(() => api.prikljucna().then(setD).catch(() => {}), 60000)

  if (greska) return <Layout naslov="Priključna vozila"><div className="greska">{greska}</div></Layout>
  if (!d) return <Layout naslov="Priključna vozila"><Spinner /></Layout>

  const qn = norm(q.trim())
  const vidljive = (d.stavke || [])
    .filter((s) => filter === 'sve' || s.stanje === filter)
    .filter((s) => !qn || norm([s.gb, s.reg, s.vrsta, s.kamion_gb, s.kamion_reg, s.vozac, s.lokacija, s.broj].join(' ')).includes(qn))
  const sekcije = STANJA.map((st) => ({ st, lista: vidljive.filter((s) => s.stanje === st.k) })).filter((x) => x.lista.length)

  return (
    <Layout naslov="Priključna vozila">
      <p className="meta" style={{ marginTop: 0 }}>
        Sve prikolice i šlepe na jednom mjestu — gdje je koja. Prikačene se vide iz Prikapčanja; što je ⚠ ili ❔ treba upisati.
      </p>

      {korisnik?.uloga === 'voditelj' && <Parkinzi parkinzi={parkinzi} onPromjena={ucitajParkinge} />}

      <div className="pv2-cipovi">
        <button className={'pv2-cip' + (filter === 'sve' ? ' akt' : '')} onClick={() => setFilter('sve')}>
          Sve <b>{d.ukupno}</b>
        </button>
        {STANJA.map((st) => (
          <button key={st.k} className={'pv2-cip' + (filter === st.k ? ' akt' : '')}
            style={filter === st.k ? { background: st.boja, borderColor: st.boja, color: '#fff' } : { borderColor: st.boja, color: st.boja }}
            onClick={() => setFilter(filter === st.k ? 'sve' : st.k)} disabled={!d.brojevi[st.k]}>
            {st.ikona} {st.naziv} <b>{d.brojevi[st.k] || 0}</b>
          </button>
        ))}
      </div>
      <input className="pretraga-input" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder="Traži GB, registraciju, kamion, vozača, parking…" style={{ margin: '6px 0 10px' }} />

      {sekcije.length === 0 && <p className="meta">Nema vozila za prikaz.</p>}
      {sekcije.map(({ st, lista }) => (
        <div key={st.k} className="karta pv2-sek" style={{ borderLeft: `5px solid ${st.boja}` }}>
          <div className="sekcija-naslov" style={{ marginTop: 0, color: st.boja }}>{st.ikona} {st.naziv} ({lista.length})</div>
          {st.k === 'za_upisati' && <p className="meta" style={{ marginTop: 0 }}>Nalog je gotov, a nije upisano gdje je — upiši Spremna (+ parking) ili Pokvareno.</p>}
          {st.k === 'nepoznato' && <p className="meta" style={{ marginTop: 0 }}>Za ove nema ni naloga ni zapisa u Prikapčanju — upiši na kojem su kamionu ili na kojem parkingu.</p>}
          {lista.map((s) => <Redak key={s.gb} s={s} parkinzi={parkinzi} nav={nav} onGotovo={ucitaj} />)}
        </div>
      ))}
    </Layout>
  )
}

function Opis({ s }) {
  switch (s.stanje) {
    case 'radiona': return <>🔧 U radioni{s.broj ? ` · ${s.broj}` : ''}{odTxt(s.od)}</>
    case 'prikacena': return <>🔗 Na kamionu <b>GB {s.kamion_gb || '?'}</b>{s.kamion_reg ? ` (${s.kamion_reg})` : ''}{s.vozac ? ` · 🧑 ${s.vozac}` : ''}{odTxt(s.od)}</>
    case 'spremna': return <>🟢 📍 <b>{s.lokacija || 'parking nije upisan'}</b>{odTxt(s.od)}</>
    case 'slobodna': return <>🅿️ 📍 {s.lokacija ? <b>{s.lokacija}</b> : <i>parking nije upisan</i>}{odTxt(s.od)}</>
    case 'pokvarena': return <>🛑 Pokvarena{s.lokacija ? <> · 📍 <b>{s.lokacija}</b></> : ''}</>
    case 'za_upisati': return <>⚠ Nalog gotov — upiši gdje je</>
    default: return <>❔ Nije upisano gdje je</>
  }
}

function Redak({ s, parkinzi, nav, onGotovo }) {
  const st = ST[s.stanje] || ST.nepoznato
  return (
    <div className="sp-red pv2-red">
      <div className="sp-info" onClick={() => s.nalog_id && nav(`/nalozi/${s.nalog_id}`)} style={{ cursor: s.nalog_id ? 'pointer' : 'default' }}>
        <div className="sp-gb">🛻 {s.gb} <span className="meta" style={{ fontWeight: 400 }}>{[s.reg, s.vrsta].filter(Boolean).join(' · ')}</span></div>
        <div className="meta pv2-opis" style={{ color: st.boja }}><Opis s={s} /></div>
        {s.napomena && <div className="meta sp-nap">📝 {s.napomena}</div>}
      </div>
      <Akcije s={s} parkinzi={parkinzi} onGotovo={onGotovo} />
    </div>
  )
}

// Akcije po stanju: prikači na kamion / na parking / spremna / pokvarena.
function Akcije({ s, parkinzi, onGotovo }) {
  const [forma, setForma] = useState(null)   // null | 'prikaci' | 'parking' | 'spremna'
  const [kamion, setKamion] = useState('')
  const [vozac, setVozac] = useState('')
  const [lok, setLok] = useState('')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')

  if (s.stanje === 'radiona') return null
  const izvrsi = async (fn) => {
    setRadi(true); setGreska('')
    try { await fn(); setForma(null); onGotovo() } catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }
  const prikaci = () => izvrsi(async () => {
    if (!kamion.trim()) throw new Error('Upiši GB kamiona')
    await api.zabiljeziPrikapcanje({ prikolica_gb: s.gb, vrsta: 'prikaceno', kamion_gb: kamion.trim(), vozac: vozac.trim() || null })
    if (s.stanje !== 'nepoznato') await api.postaviStatusVozila(s.gb, { status: 'aktivno' })
  })
  const naParking = () => izvrsi(async () => {
    if (!lok.trim()) throw new Error('Odaberi parking')
    await api.zabiljeziPrikapcanje({ prikolica_gb: s.gb, vrsta: 'otkaceno', lokacija: lok.trim() })
    await api.postaviStatusVozila(s.gb, { status: 'nezaduzeno', lokacija: lok.trim() })
  })
  const spremna = () => izvrsi(async () => {
    if (!lok.trim()) throw new Error('Odaberi parking')
    await api.postaviStatusVozila(s.gb, { status: 'spremno', lokacija: lok.trim() })
  })
  const pokvarena = () => izvrsi(() => api.postaviStatusVozila(s.gb, { status: 'pokvareno' }))

  if (forma === 'prikaci') {
    return (
      <div className="sp-forma">
        <div className="cm-naslov">🔗 Na koji kamion?</div>
        <input className="pretraga-input" style={{ marginBottom: 5 }} placeholder="GB kamiona" value={kamion}
          onChange={(e) => setKamion(e.target.value)} autoFocus />
        <input className="pretraga-input" placeholder="Vozač (neobavezno)" value={vozac} onChange={(e) => setVozac(e.target.value)} />
        {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
        <div className="btn-red" style={{ marginTop: 5 }}>
          <button className="btn mali" disabled={radi} onClick={prikaci}>{radi ? '…' : 'Spremi'}</button>
          <button className="btn sekund mali" disabled={radi} onClick={() => setForma(null)}>Odustani</button>
        </div>
      </div>
    )
  }
  if (forma === 'parking' || forma === 'spremna') {
    return (
      <div className="sp-forma">
        <div className="cm-naslov">{forma === 'spremna' ? '🟢 Spremna — na kojem parkingu?' : '🅿️ Na kojem parkingu?'}</div>
        <ParkingSelect parkinzi={parkinzi} value={lok} onChange={setLok} />
        {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
        <div className="btn-red" style={{ marginTop: 5 }}>
          <button className="btn mali" disabled={radi} onClick={forma === 'spremna' ? spremna : naParking}>{radi ? '…' : 'Spremi'}</button>
          <button className="btn sekund mali" disabled={radi} onClick={() => setForma(null)}>Odustani</button>
        </div>
      </div>
    )
  }
  return (
    <div className="btn-red pv2-akcije">
      {(s.stanje === 'za_upisati' || s.stanje === 'pokvarena') && (
        <button className="btn mali" disabled={radi} onClick={() => setForma('spremna')}>🟢 Spremna</button>
      )}
      {s.stanje === 'za_upisati' && (
        <button className="btn sekund mali" disabled={radi} onClick={pokvarena}>🛑 Pokvarena</button>
      )}
      {s.stanje !== 'prikacena' && s.stanje !== 'za_upisati' && (
        <button className="btn mali" disabled={radi} onClick={() => setForma('prikaci')}>🔗 {s.stanje === 'spremna' ? 'Uzeta' : 'Prikači'}</button>
      )}
      {s.stanje === 'prikacena' && (
        <button className="btn sekund mali" disabled={radi} onClick={() => setForma('parking')}>🅿️ Otkačena</button>
      )}
      {(s.stanje === 'slobodna' || s.stanje === 'nepoznato') && (
        <button className="btn sekund mali" disabled={radi} onClick={() => setForma('parking')}>🅿️ Na parkingu</button>
      )}
      {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
    </div>
  )
}
