import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

// Faza 2 — osobni učinak servisera: zarada po učinku + red poslova s cijenom.
export default function MojUcinak() {
  const { t } = useT()
  const [dana, setDana] = useState(7)
  const [d, setD] = useState(null)
  const ucitaj = (n = dana) => { setD(null); api.mojUcinak(n).then(setD).catch(() => setD({ red: [], zarada_eur: 0, broj_poslova: 0 })) }
  useEffect(() => { ucitaj(dana) }, [dana])
  const eur = (x) => (x || 0).toLocaleString('hr-HR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })

  return (
    <Layout naslov={t('tab.mojUcinak')}>
      <div className="vz-filteri no-print" style={{ marginBottom: 10 }}>
        {[7, 30].map((n) => (
          <button key={n} className={'vz-fil' + (dana === n ? ' akt' : '')} onClick={() => setDana(n)}>{n} {t('pos.dana')}</button>
        ))}
      </div>
      {d === null ? <Spinner /> : (
        <>
          <div className="mu-kpi">
            <div className="mu-glavni">
              <div className="mu-n">{eur(d.zarada_eur)}</div>
              <div className="mu-l">{t('mu.zarada', { dana })}</div>
            </div>
            <div className="mu-sporedni">
              <div><strong>{d.broj_poslova}</strong><span>{t('mu.poslova')}</span></div>
              <div><strong>{d.mjesto ? `${d.mjesto}.` : '—'}</strong><span>{t('mu.mjesto', { n: d.ukupno_servisera || 0 })}</span></div>
            </div>
          </div>

          <h3 className="mu-naslov">{t('mu.red')}</h3>
          {d.red.length === 0 ? (
            <p className="meta">{t('mu.nemaReda')}</p>
          ) : (
            <div className="mu-lista">
              {d.red.map((p) => (
                <Link key={p.zadatak_id} to={p.nalog_id ? `/nalozi/${p.nalog_id}` : '#'} className="mu-posao">
                  <div className="mu-posao-glava">
                    <span className="mu-op">{p.operacija}</span>
                    <span className="mu-cijena">{eur(p.cijena_eur)}</span>
                  </div>
                  <div className="mu-posao-opis">{p.opis}</div>
                  <div className="mu-posao-meta">
                    {p.vozilo && <span>🚚 {p.vozilo}</span>}
                    {p.nalog_broj && <span>#{p.nalog_broj}</span>}
                    {p.mjeri && <span className="mu-mjeri">⏱ {t('mu.uTijeku')}</span>}
                  </div>
                </Link>
              ))}
            </div>
          )}
          <p className="meta" style={{ marginTop: 14 }}>{t('mu.napo')}</p>
        </>
      )}
    </Layout>
  )
}
