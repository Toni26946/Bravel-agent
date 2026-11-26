import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import { Parkinzi, ParkingSelect } from './SpremneSlepe'

// Priključna vozila — gdje je što (Toni 25.11.2026.): JEDNA ploča umjesto
// „Slobodna" + „Spremna". Svaka prikolica/šlepa ima točno jedno stanje.
// Svi tekstovi idu kroz prijevode (pv2.*) — 26.11.2026. pola stranice nije bilo na engleskom.
const STANJA = [
  { k: 'radiona', ikona: '🔧', boja: '#1d4ed8', bg: '#e5edff' },
  { k: 'prikacena', ikona: '🔗', boja: '#047857', bg: '#dcfce7' },
  { k: 'za_upisati', ikona: '⚠', boja: '#b91c1c', bg: '#fee2e2' },
  { k: 'spremna', ikona: '🟢', boja: '#15803d', bg: '#ecfdf5' },
  { k: 'slobodna', ikona: '🅿️', boja: '#0369a1', bg: '#e0f2fe' },
  { k: 'pokvarena', ikona: '🛑', boja: '#9f1239', bg: '#ffe4e6' },
  { k: 'nepoznato', ikona: '❔', boja: '#6b7280', bg: '#f3f4f6' },
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
const odTxt = (t, iso) => {
  if (!iso) return ''
  const n = dana(iso)
  const koliko = n == null ? '' : n === 0 ? ` (${t('pv2.danas')})` : ` (${n} ${n === 1 ? t('pv2.dan') : t('pv2.dana')})`
  return ` · ${t('pv2.od')} ${dHR(iso)}${koliko}`
}
const norm = (s) => (s || '').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')

export default function PrikljucnaVozila() {
  const nav = useNavigate()
  const { t } = useT()
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

  const naslov = t('tab.prikljucna')
  if (greska) return <Layout naslov={naslov}><div className="greska">{greska}</div></Layout>
  if (!d) return <Layout naslov={naslov}><Spinner /></Layout>

  const qn = norm(q.trim())
  const vidljive = (d.stavke || [])
    .filter((s) => filter === 'sve' || s.stanje === filter)
    .filter((s) => !qn || norm([s.gb, s.reg, s.vrsta, s.kamion_gb, s.kamion_reg, s.vozac, s.lokacija, s.broj].join(' ')).includes(qn))
  const sekcije = STANJA.map((st) => ({ st, lista: vidljive.filter((s) => s.stanje === st.k) })).filter((x) => x.lista.length)
  const uredjuje = korisnik?.uloga === 'voditelj' || korisnik?.uloga === 'poslovodja'

  return (
    <Layout naslov={naslov}>
      <p className="meta" style={{ marginTop: 0 }}>{t('pv2.opis')}</p>

      {uredjuje && <Parkinzi parkinzi={parkinzi} onPromjena={ucitajParkinge} brisanje={korisnik?.uloga === 'voditelj'} />}

      <div className="pv2-cipovi">
        <button className={'pv2-cip' + (filter === 'sve' ? ' akt' : '')} onClick={() => setFilter('sve')}>
          {t('pv2.sve')} <b>{d.ukupno}</b>
        </button>
        {STANJA.map((st) => (
          <button key={st.k} className={'pv2-cip' + (filter === st.k ? ' akt' : '')}
            style={filter === st.k ? { background: st.boja, borderColor: st.boja, color: '#fff' } : { borderColor: st.boja, color: st.boja }}
            onClick={() => setFilter(filter === st.k ? 'sve' : st.k)} disabled={!d.brojevi[st.k]}>
            {st.ikona} {t('pv2.st.' + st.k)} <b>{d.brojevi[st.k] || 0}</b>
          </button>
        ))}
      </div>
      <input className="pretraga-input" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={t('pv2.trazi')} style={{ margin: '6px 0 10px' }} />

      {sekcije.length === 0 && <p className="meta">{t('pv2.nema')}</p>}
      {sekcije.map(({ st, lista }) => (
        <div key={st.k} className="karta pv2-sek" style={{ borderLeft: `5px solid ${st.boja}` }}>
          <div className="sekcija-naslov" style={{ marginTop: 0, color: st.boja }}>{st.ikona} {t('pv2.st.' + st.k)} ({lista.length})</div>
          {st.k === 'za_upisati' && <p className="meta" style={{ marginTop: 0 }}>{t('pv2.zaUpisatiOpis')}</p>}
          {st.k === 'nepoznato' && <p className="meta" style={{ marginTop: 0 }}>{t('pv2.nepoznatoOpis')}</p>}
          {lista.map((s) => <Redak key={s.gb} s={s} parkinzi={parkinzi} nav={nav} onGotovo={ucitaj} onNoviParking={ucitajParkinge} />)}
        </div>
      ))}
    </Layout>
  )
}

function Opis({ s }) {
  const { t } = useT()
  const nijeUpisan = t('pv2.parkingNijeUpisan')
  switch (s.stanje) {
    case 'radiona': return <>🔧 {t('pv2.st.radiona')}{s.broj ? ` · ${s.broj}` : ''}{odTxt(t, s.od)}</>
    case 'prikacena': return <>🔗 {t('pv2.naKamionu')} <b>GB {s.kamion_gb || '?'}</b>{s.kamion_reg ? ` (${s.kamion_reg})` : ''}{s.vozac ? ` · 🧑 ${s.vozac}` : ''}{odTxt(t, s.od)}</>
    case 'spremna': return <>🟢 📍 <b>{s.lokacija || nijeUpisan}</b>{odTxt(t, s.od)}</>
    case 'slobodna': return <>🅿️ 📍 {s.lokacija ? <b>{s.lokacija}</b> : <i>{nijeUpisan}</i>}{odTxt(t, s.od)}</>
    case 'pokvarena': return <>🛑 {t('pv2.st.pokvarena')}{s.lokacija ? <> · 📍 <b>{s.lokacija}</b></> : ''}</>
    case 'za_upisati': return <>⚠ {t('pv2.nalogGotov')}</>
    default: return <>❔ {t('pv2.nijeUpisano')}</>
  }
}

function Redak({ s, parkinzi, nav, onGotovo, onNoviParking }) {
  const st = ST[s.stanje] || ST.nepoznato
  return (
    <div className="sp-red pv2-red">
      <div className="sp-info" onClick={() => s.nalog_id && nav(`/nalozi/${s.nalog_id}`)} style={{ cursor: s.nalog_id ? 'pointer' : 'default' }}>
        <div className="sp-gb">🛻 {s.gb} <span className="meta" style={{ fontWeight: 400 }}>{[s.reg, s.vrsta].filter(Boolean).join(' · ')}</span></div>
        <div className="meta pv2-opis" style={{ color: st.boja }}><Opis s={s} /></div>
        {s.napomena && <div className="meta sp-nap">📝 {s.napomena}</div>}
      </div>
      <Akcije s={s} parkinzi={parkinzi} onGotovo={onGotovo} onNoviParking={onNoviParking} />
    </div>
  )
}

// Akcije po stanju: prikači na kamion / na parking / spremna / pokvarena.
function Akcije({ s, parkinzi, onGotovo, onNoviParking }) {
  const { t } = useT()
  const [forma, setForma] = useState(null)   // null | 'prikaci' | 'parking' | 'spremna'
  const [kamion, setKamion] = useState('')
  const [vozac, setVozac] = useState('')
  const [lok, setLok] = useState('')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')

  if (s.stanje === 'radiona') return null
  const izvrsi = async (fn) => {
    setRadi(true); setGreska('')
    try { await fn(); setForma(null); onGotovo() } catch (e) { setGreska(e.message || t('pv2.greska')) } finally { setRadi(false) }
  }
  const prikaci = () => izvrsi(async () => {
    if (!kamion.trim()) throw new Error(t('pv2.upisiGb'))
    await api.zabiljeziPrikapcanje({ prikolica_gb: s.gb, vrsta: 'prikaceno', kamion_gb: kamion.trim(), vozac: vozac.trim() || null })
    if (s.stanje !== 'nepoznato') await api.postaviStatusVozila(s.gb, { status: 'aktivno' })
  })
  const naParking = () => izvrsi(async () => {
    if (!lok.trim()) throw new Error(t('prikapcanje.trebaParking'))
    await api.zabiljeziPrikapcanje({ prikolica_gb: s.gb, vrsta: 'otkaceno', lokacija: lok.trim() })
    await api.postaviStatusVozila(s.gb, { status: 'nezaduzeno', lokacija: lok.trim() })
  })
  const spremna = () => izvrsi(async () => {
    if (!lok.trim()) throw new Error(t('prikapcanje.trebaParking'))
    await api.postaviStatusVozila(s.gb, { status: 'spremno', lokacija: lok.trim() })
  })
  const pokvarena = () => izvrsi(() => api.postaviStatusVozila(s.gb, { status: 'pokvareno' }))
  const gumbi = (spremi) => (
    <div className="btn-red" style={{ marginTop: 5 }}>
      <button className="btn mali" disabled={radi} onClick={spremi}>{radi ? '…' : t('common.spremi')}</button>
      <button className="btn sekund mali" disabled={radi} onClick={() => setForma(null)}>{t('common.odustani')}</button>
    </div>
  )

  if (forma === 'prikaci') {
    return (
      <div className="sp-forma">
        <div className="cm-naslov">🔗 {t('pv2.naKojiKamion')}</div>
        <input className="pretraga-input" style={{ marginBottom: 5 }} placeholder={t('pv2.gbKamiona')} value={kamion}
          onChange={(e) => setKamion(e.target.value)} autoFocus />
        <input className="pretraga-input" placeholder={t('pv2.vozacNeobavezno')} value={vozac} onChange={(e) => setVozac(e.target.value)} />
        {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
        {gumbi(prikaci)}
      </div>
    )
  }
  if (forma === 'parking' || forma === 'spremna') {
    return (
      <div className="sp-forma">
        <div className="cm-naslov">{forma === 'spremna' ? `🟢 ${t('pv2.spremnaKojiParking')}` : `🅿️ ${t('pv2.kojiParking')}`}</div>
        <ParkingSelect parkinzi={parkinzi} value={lok} onChange={setLok} onNovi={onNoviParking} />
        {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
        {gumbi(forma === 'spremna' ? spremna : naParking)}
      </div>
    )
  }
  // Otvori formu parkinga s već upisanim parkingom (da se samo potvrdi ili promijeni).
  const otvori = (f) => { setLok(s.lokacija || ''); setForma(f) }
  // Pokvarena bez naloga (26.11.2026.) — jedan dodir, pa pitaj da se ne promaši na mobitelu.
  const pokvarenaPotvrdi = () => {
    if (s.stanje === 'za_upisati' || window.confirm(t('pv2.potvrdaPokvarena', { gb: s.gb }))) pokvarena()
  }
  const st = s.stanje
  return (
    <div className="btn-red pv2-akcije">
      {st !== 'prikacena' && st !== 'za_upisati' && (
        <button className="btn mali" disabled={radi} onClick={() => setForma('prikaci')}>🔗 {st === 'spremna' ? t('pv2.uzeta') : t('pv2.prikaci')}</button>
      )}
      {st === 'prikacena' && (
        <button className="btn sekund mali" disabled={radi} onClick={() => otvori('parking')}>🅿️ {t('pv2.otkacena')}</button>
      )}
      {st !== 'spremna' && st !== 'prikacena' && (
        <button className="btn mali" disabled={radi} onClick={() => otvori('spremna')}>🟢 {t('pv2.st.spremna')}</button>
      )}
      {/* Slobodna = stoji na parkingu, nije potvrđeno da je spremna (bez naloga). */}
      {st === 'spremna' && (
        <button className="btn sekund mali" disabled={radi} onClick={() => otvori('parking')}>🅿️ {t('pv2.nijeSpremna')}</button>
      )}
      {(st === 'slobodna' || st === 'nepoznato' || st === 'pokvarena') && (
        <button className="btn sekund mali" disabled={radi} onClick={() => otvori('parking')}>🅿️ {st === 'slobodna' ? t('pv2.promijeniParking') : t('pv2.naParkingu')}</button>
      )}
      {st !== 'pokvarena' && st !== 'prikacena' && (
        <button className="btn sekund mali" disabled={radi} onClick={pokvarenaPotvrdi}>🛑 {t('pv2.st.pokvarena')}</button>
      )}
      {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
    </div>
  )
}
