import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useT } from '../i18n'

// Kamioni koji su napustili radionu (GPS), a nalog je još u radu — s gumbom za završavanje.
export default function IzasliIzRadione() {
  const { t } = useT()
  const nav = useNavigate()
  const [nalozi, setNalozi] = useState(null)
  const [greska, setGreska] = useState('')
  const [radiId, setRadiId] = useState(0)

  const ucitaj = () => api.izasli().then(setNalozi).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])
  useAutoOsvjezi(() => api.izasli().then(setNalozi).catch(() => {}), 15000)

  const zavrsi = async (id) => {
    setRadiId(id); setGreska('')
    try { await api.nalogStatus(id, 'gotov'); ucitaj() }
    catch (e) { setGreska(e.message) } finally { setRadiId(0) }
  }

  if (greska) return <Layout naslov={t('tab.izasli')}><div className="greska">{greska}</div></Layout>
  if (!nalozi) return <Layout naslov={t('tab.izasli')}><Spinner /></Layout>

  return (
    <Layout naslov={t('tab.izasli')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('izasli.opis')}</p>
      {nalozi.length === 0 ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('izasli.nema')}</p></div>
      ) : (
        nalozi.map((n) => (
          <div className="karta izasli-red" key={n.id}>
            <div className="izasli-info" onClick={() => nav(`/nalozi/${n.id}`)}>
              <div className="izasli-gb">🚚 {n.vozilo?.gb}</div>
              <div className="meta">{n.broj}{n.vozilo?.registracija ? ` · ${n.vozilo.registracija}` : ''}</div>
            </div>
            <button className="btn mali izasli-btn" disabled={radiId === n.id} onClick={() => zavrsi(n.id)}>
              {radiId === n.id ? '…' : `✓ ${t('izasli.zavrsi')}`}
            </button>
          </div>
        ))
      )}
      <FlotaStatus />
    </Layout>
  )
}

// Dijagnostika GPS nadzora — pomaže vidjeti zašto obavijest (ni)je stigla.
function FlotaStatus() {
  const [otvoreno, setOtvoreno] = useState(false)
  const [s, setS] = useState(null)
  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)

  const ucitaj = () => api.flotaStatus().then(setS).catch((e) => setGreska(e.message))
  useEffect(() => { if (otvoreno && !s) ucitaj() }, [otvoreno])

  const provjeri = async () => {
    setRadi(true); setGreska('')
    try { const r = await api.flotaProvjeri(); setS(r.status) }
    catch (e) { setGreska(e.message) } finally { setRadi(false) }
  }

  const zivo = s && s.sekundi_od_osvjezenja != null && s.sekundi_od_osvjezenja < (s.interval_s + 60)

  return (
    <div className="karta" style={{ marginTop: 16 }}>
      <div className="fs-glava" onClick={() => setOtvoreno((o) => !o)}>
        <strong>📡 GPS status</strong>
        <span className="meta">{otvoreno ? '▲' : '▼'}</span>
      </div>
      {otvoreno && (
        <div style={{ marginTop: 10 }}>
          {greska && <div className="greska">{greska}</div>}
          {!s ? <Spinner /> : (
            <>
              <div className="fs-red"><span>Nadzor konfiguriran</span><b>{s.konfigurirano ? 'DA' : 'NE'}</b></div>
              <div className="fs-red"><span>Push obavijesti (server)</span><b>{s.push_omogucen ? 'DA' : 'NE'}</b></div>
              <div className="fs-red">
                <span>Voditelja s uključenim obavijestima</span>
                <b className={s.voditelja_s_pushom ? '' : 'fs-lose'}>{s.voditelja_s_pushom}</b>
              </div>
              <div className="fs-red">
                <span>Zadnje osvježenje pozicija</span>
                <b className={zivo ? '' : 'fs-lose'}>
                  {s.sekundi_od_osvjezenja == null ? 'nikad' : `prije ${s.sekundi_od_osvjezenja} s`}
                </b>
              </div>
              <div className="fs-red"><span>Broj GPS pozicija</span><b>{s.broj_pozicija}</b></div>
              {s.zadnja_greska && <div className="fs-red"><span>Zadnja greška</span><b className="fs-lose">{s.zadnja_greska}</b></div>}
              <div className="fs-red"><span>Geokrug radione</span><b>{s.radius_m} m</b></div>

              <div className="sekcija-naslov" style={{ marginTop: 12 }}>Nalozi u radu ({s.aktivni_nalozi.length})</div>
              {s.aktivni_nalozi.length === 0 ? (
                <p className="meta" style={{ margin: 0 }}>Nema naloga u statusu „u radu“.</p>
              ) : (
                <div className="op-tablica" style={{ overflowX: 'auto' }}>
                  <div className="fs-th"><div>GB</div><div>GPS</div><div>Udaljenost</div><div>Vani</div><div>Javljeno</div></div>
                  {s.aktivni_nalozi.map((a) => (
                    <div className="fs-tr" key={a.nalog_id}>
                      <div>{a.gb || '—'}</div>
                      <div>{!a.ima_poziciju ? '— nema' : a.zastarjelo ? 'zastarjelo' : 'ok'}</div>
                      <div>{a.udaljenost_m == null ? '—' : `${a.udaljenost_m} m`}</div>
                      <div>{a.vani == null ? '—' : a.vani ? 'DA' : 'ne'}</div>
                      <div>{a.vec_javljeno ? 'DA' : 'ne'}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
          <div className="btn-red" style={{ marginTop: 12 }}>
            <button className="btn sekund mali" disabled={radi} onClick={provjeri}>{radi ? '…' : '🔄 Provjeri sada'}</button>
            <button className="btn sekund mali" disabled={radi} onClick={ucitaj}>Osvježi status</button>
          </div>
        </div>
      )}
    </div>
  )
}
