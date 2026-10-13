import { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

const eur = (n) => (n == null ? '' : n.toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €')
const broj = (n) => (n == null || n === '' || isNaN(Number(n)) ? (n ?? '') : Number(n).toLocaleString('hr-HR'))
const iso = (d) => d.toISOString().slice(0, 10)
const danasISO = () => iso(new Date())
const prijeDana = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return iso(d) }

export default function SkladisteDashboard() {
  const { t } = useT()
  const [primke, setPrimke] = useState(null)
  const [narucitelji, setNarucitelji] = useState([])
  const [greska, setGreska] = useState('')
  const [od, setOd] = useState(() => prijeDana(30))
  const [doDat, setDoDat] = useState(() => danasISO())
  const [samoStari, setSamoStari] = useState(false)
  const [unos, setUnos] = useState({})   // { "pid:idx": {gb, kol} }

  const ucitaj = () => api.primke().then(setPrimke).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj(); api.narucitelji().then(setNarucitelji).catch(() => {}) }, [])

  if (primke === null) return <Spinner />

  const danas = new Date()
  const dijelovi = []
  for (const p of primke) {
    const datum = p.datum || (p.kreiran ? p.kreiran.slice(0, 10) : null)
    if (od && datum && datum < od) continue
    if (doDat && datum && datum > doDat) continue
    ;(p.stavke || []).forEach((s, idx) => {
      const prim = parseFloat(s.kolicina) || 0
      const razd = s.razduzenja || []
      const poslano = razd.reduce((a, r) => a + (parseFloat(r.kolicina) || 0), 0)
      const preostalo = Math.round((prim - poslano) * 1000) / 1000
      const gotov = prim > 0 && preostalo <= 0
      const dana = datum ? Math.floor((danas - new Date(datum)) / 86400000) : 0
      dijelovi.push({ pid: p.id, idx, artikl: s.artikl, jedinica: s.jedinica || 'kom', cijena: s.cijena,
        prim, razd, preostalo, gotov, dana, datum, dobavljac: p.dobavljac, brojOtp: p.broj_otpremnice, narucioId: s.narucio_id })
    })
  }
  let vidljivi = dijelovi
  if (samoStari) vidljivi = dijelovi.filter((x) => !x.gotov && x.dana > 6)
  // neugrađeni prvo (najstariji gore), gotovi na dno
  vidljivi.sort((a, b) => (a.gotov ? 1 : 0) - (b.gotov ? 1 : 0) || b.dana - a.dana)

  const kljuc = (x) => `${x.pid}:${x.idx}`
  const setU = (x, polje, v) => setUnos((p) => ({ ...p, [kljuc(x)]: { ...(p[kljuc(x)] || {}), [polje]: v } }))

  const razduzi = async (x) => {
    const u = unos[kljuc(x)] || {}
    const gb = (u.gb || '').trim()
    const kol = parseFloat(u.kol)
    if (!gb || !kol) { setGreska(t('skl.unesiGbKol')); return }
    setGreska('')
    try {
      await api.dodajRazduzenje(x.pid, x.idx, { gb, kolicina: kol })
      setUnos((p) => ({ ...p, [kljuc(x)]: { gb: '', kol: '' } }))
      ucitaj()
    } catch (e) { setGreska(e.message) }
  }
  const makniRazd = async (x, ri) => {
    setGreska('')
    try { await api.obrisiRazduzenje(x.pid, x.idx, ri); ucitaj() } catch (e) { setGreska(e.message) }
  }
  const postaviNarucio = async (x, id) => {
    setGreska('')
    try { await api.urediStavku(x.pid, x.idx, { narucio_id: id ? parseInt(id, 10) : null }); ucitaj() } catch (e) { setGreska(e.message) }
  }

  return (
    <>
      {greska && <div className="greska">{greska}</div>}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div style={{ flex: '1 1 130px' }}>
          <label style={{ marginTop: 0 }}>{t('skl.od')}</label>
          <input type="date" value={od} onChange={(e) => setOd(e.target.value)} />
        </div>
        <div style={{ flex: '1 1 130px' }}>
          <label style={{ marginTop: 0 }}>{t('skl.do')}</label>
          <input type="date" value={doDat} onChange={(e) => setDoDat(e.target.value)} />
        </div>
      </div>
      <label className="pos-toggle" style={{ marginTop: 8 }}>
        <input type="checkbox" checked={samoStari} onChange={(e) => setSamoStari(e.target.checked)} />
        {t('skl.stari6')}
      </label>

      <p className="meta" style={{ marginTop: 8 }}>{t('skl.dijelova', { n: vidljivi.length })}</p>

      {vidljivi.length === 0 ? (
        <p className="meta">{t('skl.nemaDijelova')}</p>
      ) : vidljivi.map((x) => {
        const cls = x.gotov ? ' gotov' : (x.dana > 6 ? ' kasni' : '')
        const u = unos[kljuc(x)] || {}
        return (
          <div key={kljuc(x)} className={'skl-dio-red' + cls}>
            <div className="sdr-glava">
              <span className="sdr-naziv" title={x.artikl}>{x.artikl}</span>
              <span className="sdr-meta">
                {x.gotov ? '✓ ' + t('skl.ugradjeno') : `${t('skl.preostalo')}: ${broj(x.preostalo)} ${x.jedinica}`}
                {` · ${t('skl.primljeno')} ${broj(x.prim)}`}
                {x.datum ? ` · ${t('skl.prijeDana', { n: x.dana })}` : ''}
                {x.brojOtp ? ` · ${x.brojOtp}` : ''}
              </span>
            </div>
            <select className="sdr-nar" value={x.narucioId || ''} title={t('skl.narucio')}
              onChange={(e) => postaviNarucio(x, e.target.value)}>
              <option value="">{t('skl.narucio')}…</option>
              {narucitelji.map((n) => <option key={n.id} value={n.id}>{n.ime}</option>)}
            </select>
            {!x.gotov && (
              <>
                <input className="sdr-gb" value={u.gb || ''} onChange={(e) => setU(x, 'gb', e.target.value)} placeholder={t('skl.gb')} />
                <input className="sdr-kol" type="number" step="any" value={u.kol || ''}
                  onChange={(e) => setU(x, 'kol', e.target.value)} placeholder={String(x.preostalo)} />
                <button className="btn mali sdr-btn" onClick={() => razduzi(x)}>{t('skl.razduzi')}</button>
              </>
            )}
            {x.razd.length > 0 && (
              <div className="sdr-razd">
                {x.razd.map((r, ri) => (
                  <span key={ri} className="sdr-chip">{t('skl.gb')} {r.gb}: {broj(r.kolicina)}
                    <button className="sdr-chip-x" onClick={() => makniRazd(x, ri)} title="✕">✕</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}
