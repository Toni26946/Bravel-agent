import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

// Operativni statusi (mjerodavni — „sveto pismo"). Redoslijed = redoslijed u izborniku.
const STATUSI = ['aktivno', 'u_radionici', 'pokvareno', 'spremno', 'nezaduzeno', 'prodano']
const EMO = { aktivno: '✅', u_radionici: '🔧', pokvareno: '🛑', prodano: '💰', nezaduzeno: '🛻', spremno: '🟢' }

// Naziv kategorije: prevedi ako postoji ključ, inače prikaži sirovu vrijednost.
function katLabel(t, k) {
  const p = t('kat.' + k)
  return p === 'kat.' + k ? k : p
}

// Matični popis svih vozila iz flote; status se postavlja ručno i mjerodavan je.
export default function Vozila() {
  const { t } = useT()
  const nav = useNavigate()
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')
  const [pretraga, setPretraga] = useState('')
  const [kat, setKat] = useState('')
  const [stat, setStat] = useState('')
  const [parkinzi, setParkinzi] = useState([])

  const ucitaj = () => api.vozilaRegistar().then(setD).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj(); api.parkinzi().then(setParkinzi).catch(() => {}) }, [])

  const promijeniLokalno = (gb, izmjena) =>
    setD((prev) => (prev ? prev.map((v) => (v.gb === gb ? { ...v, ...izmjena } : v)) : prev))

  const kategorije = useMemo(
    () => [...new Set((d || []).map((v) => v.kategorija).filter(Boolean))].sort(),
    [d],
  )
  const brojac = useMemo(() => {
    const b = {}
    for (const v of d || []) b[v.status] = (b[v.status] || 0) + 1
    return b
  }, [d])

  const filtrirana = useMemo(() => {
    const p = pretraga.trim().toLowerCase()
    return (d || []).filter((v) => {
      if (kat && v.kategorija !== kat) return false
      if (stat && v.status !== stat) return false
      if (!p) return true
      return [v.gb, v.registracija, v.tip].some((x) => (x || '').toLowerCase().includes(p))
    })
  }, [d, pretraga, kat, stat])

  if (greska) return <Layout naslov={t('tab.vozila')}><div className="greska">{greska}</div></Layout>
  if (!d) return <Layout naslov={t('tab.vozila')}><Spinner /></Layout>

  return (
    <Layout naslov={t('tab.vozila')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('vozila.opis')}</p>

      <input
        className="pretraga-input"
        placeholder={t('vozila.pretraga')}
        value={pretraga}
        onChange={(e) => setPretraga(e.target.value)}
      />

      <div className="vz-filteri">
        <button className={'vz-fil' + (kat === '' ? ' akt' : '')} onClick={() => setKat('')}>{t('vozila.sve')}</button>
        {kategorije.map((k) => (
          <button key={k} className={'vz-fil' + (kat === k ? ' akt' : '')} onClick={() => setKat(kat === k ? '' : k)}>
            {katLabel(t, k)}
          </button>
        ))}
      </div>
      <div className="vz-filteri">
        <button className={'vz-fil' + (stat === '' ? ' akt' : '')} onClick={() => setStat('')}>{t('vozila.sviStatusi')}</button>
        {STATUSI.map((s) => (
          <button
            key={s}
            className={'vz-fil sv-' + s + (stat === s ? ' akt' : '')}
            onClick={() => setStat(stat === s ? '' : s)}
          >
            {EMO[s]} {t('sv.' + s)} {brojac[s] ? `(${brojac[s]})` : ''}
          </button>
        ))}
      </div>

      <div className="sekcija-naslov">{filtrirana.length} / {d.length} {t('vozila.vozila')}</div>
      {filtrirana.length === 0 && <p className="meta">{t('vozila.nema')}</p>}
      {filtrirana.map((v) => (
        <div className="karta vz-red" key={v.gb}>
          <div className="vz-info" onClick={() => v.nalog_id && nav(`/nalozi/${v.nalog_id}`)}>
            <div className="vz-gb">{v.gb}</div>
            <div className="meta">
              {[v.registracija, v.tip].filter(Boolean).join(' · ') || '—'}
              {v.nalog_id ? ` · ${v.broj}` : ''}
            </div>
            {v.status === 'spremno' && v.lokacija && (
              <div className="meta vz-lok">📍 {v.lokacija}</div>
            )}
            <div className="meta vz-mob">
              {t('vozila.mobilisis')}: {v.mobilisis_status || '—'}
              {v.rucno && <span className="vz-rucno"> · {t('vozila.rucno')}</span>}
            </div>
          </div>
          <StatusChip v={v} parkinzi={parkinzi} onPromjena={(izmjena) => promijeniLokalno(v.gb, izmjena)} />
        </div>
      ))}
    </Layout>
  )
}

function StatusChip({ v, parkinzi = [], onPromjena }) {
  const { t } = useT()
  const [otvoren, setOtvoren] = useState(false)
  const [radi, setRadi] = useState(false)
  const [trazimLok, setTrazimLok] = useState(false)   // upisujemo lokaciju za „Spremno"
  const [lok, setLok] = useState(v.lokacija || '')
  const [greskaLok, setGreskaLok] = useState('')

  const posalji = async (body, izmjena) => {
    setRadi(true); setGreskaLok('')
    try {
      const r = await api.postaviStatusVozila(v.gb, body)
      onPromjena({ status: r.status, rucno: r.rucno, lokacija: r.lokacija, ...izmjena })
      setOtvoren(false); setTrazimLok(false)
    } catch (e) { setGreskaLok(e.message || 'Greška') } finally { setRadi(false) }
  }

  const odabir = (s) => {
    if (s === 'spremno') { setTrazimLok(true); setLok(v.lokacija || '') }  // traži lokaciju prvo
    else posalji({ status: s })
  }
  const spremiSpremno = () => {
    if (!lok.trim()) { setGreskaLok(t('spremne.lokObavezna')); return }
    posalji({ status: 'spremno', lokacija: lok.trim() })
  }
  const vratiMobilisis = async () => {
    setRadi(true)
    try {
      const r = await api.vratiNaMobilisis(v.gb)
      onPromjena({ status: r.status, rucno: r.rucno })
      setOtvoren(false)
    } catch (_) { /* tiho */ } finally { setRadi(false) }
  }

  return (
    <span className="chip-wrap">
      <button type="button" className={'slobodni-chip sv-' + v.status} onClick={() => { setOtvoren((o) => !o); setTrazimLok(false) }} disabled={radi}>
        {EMO[v.status] || ''} {t('sv.' + v.status)}
      </button>
      {otvoren && (
        <div className="chip-menu" onClick={(e) => e.stopPropagation()}>
          {!trazimLok ? (
            <>
              {STATUSI.map((s) => (
                <button key={s} className={'cm-opt' + (v.status === s ? ' akt' : '')} disabled={radi} onClick={() => odabir(s)}>
                  {EMO[s]} {t('sv.' + s)}
                </button>
              ))}
              {v.rucno && (
                <button className="cm-opt" disabled={radi} onClick={vratiMobilisis} title={t('vozila.vratiMobilisisOpis')}>
                  ↺ {t('vozila.vratiMobilisis')}
                </button>
              )}
            </>
          ) : (
            <div className="cm-form">
              <div className="cm-naslov">🟢 {t('spremne.gdjeParkirana')}</div>
              {parkinzi.length === 0 ? (
                <div className="meta" style={{ marginBottom: 6 }}>{t('spremne.trebaParking')}</div>
              ) : (
                <select className="pretraga-input" style={{ marginBottom: 6 }} value={lok}
                  onChange={(e) => setLok(e.target.value)} autoFocus>
                  <option value="">{t('spremne.odaberiParking')}</option>
                  {parkinzi.map((p) => <option key={p.id} value={p.naziv}>{p.naziv}</option>)}
                </select>
              )}
              {greskaLok && <div className="greska" style={{ margin: '2px 0' }}>{greskaLok}</div>}
              <div className="btn-red" style={{ marginTop: 4 }}>
                <button className="btn mali" disabled={radi || parkinzi.length === 0} onClick={spremiSpremno}>{radi ? '…' : t('common.spremi')}</button>
                <button className="btn sekund mali" disabled={radi} onClick={() => setTrazimLok(false)}>{t('common.odustani')}</button>
              </div>
            </div>
          )}
        </div>
      )}
    </span>
  )
}
