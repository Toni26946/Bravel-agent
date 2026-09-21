import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useT } from '../i18n'

// Aktivni nalozi čije je vozilo "nezadužena šlepa" (prikolica bez kompozicije — iz Flota OS-a).
export default function NezaduzenaVozila() {
  const { t } = useT()
  const nav = useNavigate()
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')

  const ucitaj = () => api.nezaduzena().then(setD).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])
  useAutoOsvjezi(() => api.nezaduzena().then(setD).catch(() => {}), 60000)

  if (greska) return <Layout naslov={t('tab.nezaduzena')}><div className="greska">{greska}</div></Layout>
  if (!d) return <Layout naslov={t('tab.nezaduzena')}><Spinner /></Layout>

  const prikolice = d.prikolice || []
  return (
    <Layout naslov={t('tab.nezaduzena')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('nezaduzena.opis')}</p>
      {!d.dostupno ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('nezaduzena.nedostupno')}</p></div>
      ) : prikolice.length === 0 ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('nezaduzena.nema')}</p></div>
      ) : (
        <>
          <div className="sekcija-naslov" style={{ marginTop: 0 }}>{prikolice.length} {t('nezaduzena.slobodnih')}</div>
          {prikolice.map((p) => (
            <div
              className={'karta izasli-red' + (p.nalog_id ? '' : ' nz-bez')}
              key={p.gb}
              onClick={() => p.nalog_id && nav(`/nalozi/${p.nalog_id}`)}
            >
              <div className="izasli-info">
                <div className="izasli-gb">🛻 {p.gb}</div>
                <div className="meta">
                  {[p.tip, p.reg].filter(Boolean).join(' · ') || '—'}
                  {p.nalog_id
                    ? ` · ${p.broj} (${t('status.' + p.status)})`
                    : ` · ${t('nezaduzena.nijeURadionici')}`}
                </div>
              </div>
            </div>
          ))}
        </>
      )}
      <Dijagnostika />
    </Layout>
  )
}

// Zašto je prazno: što Flota OS vraća za svako vozilo u radu.
function Dijagnostika() {
  const [otvoreno, setOtvoreno] = useState(false)
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')

  const ucitaj = () => api.nezaduzenaDijagnostika().then(setD).catch((e) => setGreska(e.message))
  useEffect(() => { if (otvoreno && !d) ucitaj() }, [otvoreno])

  return (
    <div className="karta" style={{ marginTop: 16 }}>
      <div className="fs-glava" onClick={() => setOtvoreno((o) => !o)}>
        <strong>🔎 Zašto je prazno?</strong><span className="meta">{otvoreno ? '▲' : '▼'}</span>
      </div>
      {otvoreno && (
        <div style={{ marginTop: 10 }}>
          {greska && <div className="greska">{greska}</div>}
          {!d ? <Spinner /> : (
            <>
              <div className="fs-red"><span>Flota konfigurirana</span><b>{d.flota_konfigurirano ? 'DA' : 'NE'}</b></div>
              {/* Bulk popis svih slobodnih šlepa iz Flote */}
              {!d.bulk ? (
                <div className="fs-red"><span>Flota /nezaduzene-prikolice</span><b className="fs-lose">NEDOSTUPNO (greška/timeout)</b></div>
              ) : (
                <>
                  <div className="fs-red"><span>Slobodnih šlepa (Flota)</span><b>{d.bulk.broj}</b></div>
                  <div className="fs-red"><span>Vozila u mapi (total_gb)</span><b>{d.bulk.dijag?.total_gb ?? '—'}</b></div>
                  <div className="fs-red"><span>Klasificirano kao prikolica</span><b>{d.bulk.dijag?.prikolica_ukupno ?? '—'}</b></div>
                  <div className="fs-red"><span>Zauzetih (u kompoziciji)</span><b>{d.bulk.dijag?.zauzete ?? '—'}</b></div>
                  {d.bulk.dijag?.tipovi && (
                    <div className="fs-red" style={{ display: 'block' }}>
                      <span>TIP-ovi vozila:</span>
                      <div className="meta" style={{ marginTop: 4 }}>
                        {Object.entries(d.bulk.dijag.tipovi).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                      </div>
                    </div>
                  )}
                </>
              )}
              <div className="sekcija-naslov" style={{ margin: '10px 0 4px' }}>Vozila u radu ({d.broj_aktivnih})</div>
              {d.stavke.length === 0 && <p className="meta" style={{ margin: '8px 0 0' }}>Nema naloga u radu.</p>}
              {d.stavke.map((s) => (
                <div className="fs-red" key={s.nalog_id} style={{ display: 'block' }}>
                  <b>{s.gb || '—'}</b> <span className="meta">({s.broj})</span>
                  {' — '}
                  {!s.zaduzenje
                    ? <span className="fs-lose">Flota ne vraća podatak (GB nije u floti?)</span>
                    : <span>tip: {s.zaduzenje.tip || '—'} · prikolica: {s.zaduzenje.prikolica ? 'DA' : 'ne'} · zaduženo: {s.zaduzenje.zaduzeno ? 'DA' : 'ne'}{s.zaduzenje.kamion ? ` (kamion ${s.zaduzenje.kamion})` : ''}</span>}
                  {s.nezaduzena_slepa && <b className="fs-lose"> → nezadužena šlepa</b>}
                </div>
              ))}
            </>
          )}
          <div className="btn-red" style={{ marginTop: 10 }}>
            <button className="btn sekund mali" onClick={ucitaj}>Osvježi</button>
          </div>
        </div>
      )}
    </div>
  )
}
