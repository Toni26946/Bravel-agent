import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useT } from '../i18n'

// Pregled servisa po kamionu: zadnji servis, idući (zadnji + 12 mj), preostalo dana.
// Faza 1 = vremenski uvjet; km uvjet dolazi kasnije (iz Mobilisisa).
export default function Servisi() {
  const { t } = useT()
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')
  const [q, setQ] = useState('')
  const [fil, setFil] = useState('')

  const ucitaj = () => api.servisi().then(setD).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])
  useAutoOsvjezi(() => api.servisi().then(setD).catch(() => {}), 120000)

  if (greska) return <Layout naslov={t('tab.servisi')}><div className="greska">{greska}</div></Layout>
  if (!d) return <Layout naslov={t('tab.servisi')}><Spinner /></Layout>

  const broj = { dospjelo: 0, uskoro: 0, ok: 0, nepoznato: 0 }
  d.forEach((x) => { broj[x.status] = (broj[x.status] || 0) + 1 })

  const upit = q.trim().toLowerCase()
  const filtrirano = d.filter((x) => {
    if (fil && x.status !== fil) return false
    if (!upit) return true
    return [x.gb, x.reg, x.tip].some((v) => (v || '').toString().toLowerCase().includes(upit))
  })

  const STAT = [
    { k: 'dospjelo', emo: '🔴', lbl: t('servisi.dospjelo') },
    { k: 'uskoro', emo: '🟡', lbl: t('servisi.uskoro') },
    { k: 'ok', emo: '🟢', lbl: t('servisi.ok') },
    { k: 'nepoznato', emo: '⚪', lbl: t('servisi.nepoznato') },
  ]

  return (
    <Layout naslov={t('tab.servisi')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('servisi.opis')}</p>

      <input className="pretraga-input" placeholder={t('servisi.trazi')}
        value={q} onChange={(e) => setQ(e.target.value)} />

      <div className="vz-filteri">
        <button className={'vz-fil' + (fil === '' ? ' akt' : '')} onClick={() => setFil('')}>
          {t('vozila.sve')} ({d.length})
        </button>
        {STAT.map((s) => (
          <button key={s.k} className={'vz-fil' + (fil === s.k ? ' akt' : '')}
            onClick={() => setFil(fil === s.k ? '' : s.k)}>
            {s.emo} {s.lbl} {broj[s.k] ? `(${broj[s.k]})` : '(0)'}
          </button>
        ))}
      </div>

      <div className="sekcija-naslov">{filtrirano.length} / {d.length} {t('servisi.kamiona')}</div>
      {filtrirano.length === 0 && <p className="meta">{t('prikapcanje.nemaRezultata')}</p>}
      {filtrirano.map((x) => <ServisRed key={x.gb} x={x} onGotovo={ucitaj} />)}
    </Layout>
  )
}

function datum(iso) { if (!iso) return '—'; try { return new Date(iso).toLocaleDateString('hr-HR') } catch (_) { return iso } }

function preostaloTekst(t, x) {
  if (x.preostalo_dana === null || x.preostalo_dana === undefined) return t('servisi.nepoznato')
  if (x.preostalo_dana <= 0) return `${t('servisi.proslo')} ${Math.abs(x.preostalo_dana)} ${t('servisi.dana')}`
  return `${t('servisi.jos')} ${x.preostalo_dana} ${t('servisi.dana')}`
}

function kmBroj(n) { try { return Math.round(n).toLocaleString('hr-HR') } catch (_) { return n } }

function kmTekst(t, x) {
  if (x.servis_km === null || x.servis_km === undefined
      || x.km_trenutni === null || x.km_trenutni === undefined) {
    return t('servisi.nepoznato')
  }
  const emo = EMO[x.status_km] || ''
  const proslo = `${kmBroj(x.km_proslo)} / ${kmBroj(x.prag_km)} km`
  if (x.km_preostalo <= 0) {
    return `${emo} ${proslo} · ${t('servisi.prekoraceno')} ${kmBroj(-x.km_preostalo)} km`
  }
  return `${emo} ${proslo} · ${t('servisi.jos')} ${kmBroj(x.km_preostalo)} km`
}

const EMO = { dospjelo: '🔴', uskoro: '🟡', ok: '🟢', nepoznato: '⚪' }

function ServisRed({ x, onGotovo }) {
  const { t } = useT()
  const [uredi, setUredi] = useState(false)
  const [datumVal, setDatumVal] = useState(x.servis_zadnji || '')
  const [radi, setRadi] = useState(false)

  const spremi = async () => {
    if (!datumVal) return
    setRadi(true)
    try { await api.servisiUredi(x.gb, { servis_zadnji: datumVal }); setUredi(false); onGotovo() }
    catch (_) { /* tiho */ } finally { setRadi(false) }
  }

  return (
    <div className="karta sp-red" style={{ padding: '10px 14px' }}>
      <div className="sp-info">
        <div className="sp-gb">🚚 {x.gb} {EMO[x.status] || ''}
          {x.reg && <span className="meta" style={{ fontWeight: 400 }}> · {x.reg}</span>}</div>
        <div className="meta">
          🗓️ {t('servisi.zadnji')}: <strong>{datum(x.servis_zadnji)}</strong>
          {' · '}{t('servisi.iduci')}: {datum(x.iduci_datum)}
          {' · '}{EMO[x.status_vrijeme] || ''} {preostaloTekst(t, x)}
        </div>
        <div className="meta">
          🛣️ {t('servisi.km')}: {kmTekst(t, x)}
        </div>
        <div className="meta" style={{ fontSize: 11.5, opacity: .8 }}>
          {t('servisi.prag')}: {(x.prag_km / 1000)} 000 km / 12 {t('servisi.mj')}
        </div>
        {uredi && (
          <div className="btn-red" style={{ marginTop: 6 }}>
            <input type="date" className="pretraga-input" style={{ maxWidth: 170, marginBottom: 0 }}
              value={datumVal} onChange={(e) => setDatumVal(e.target.value)} />
            <button className="btn mali" disabled={radi || !datumVal} onClick={spremi}>{radi ? '…' : t('common.spremi')}</button>
            <button className="btn sekund mali" onClick={() => setUredi(false)}>{t('common.odustani')}</button>
          </div>
        )}
      </div>
      {!uredi && (
        <button className="btn sekund mali" onClick={() => { setDatumVal(x.servis_zadnji || ''); setUredi(true) }}>
          ✏️ {t('servisi.obavljen')}
        </button>
      )}
    </div>
  )
}
