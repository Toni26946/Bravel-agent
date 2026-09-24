import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useT } from '../i18n'

// Evidencija prikapčanja — vlastita stranica.
//  1) „Trenutno" — tko vozi koju prikolicu (zadnji događaj = prikačeno)
//  2) Dnevnik svih događaja (prikačeno/otkačeno) s filterima i ispisom
export default function EvidencijaPrikapcanja() {
  const { t } = useT()
  const [trenutno, setTrenutno] = useState(null)
  const [rows, setRows] = useState(null)
  const [vrsta, setVrsta] = useState('')

  const ucitajTrenutno = () => api.prikapcanjeTrenutno().then(setTrenutno).catch(() => setTrenutno([]))
  const ucitajDnevnik = (v = vrsta) => api.dnevnikPrikapcanja({ vrsta: v, dana: 180 }).then(setRows).catch(() => setRows([]))
  useEffect(() => { ucitajTrenutno(); ucitajDnevnik('') }, [])
  useAutoOsvjezi(() => { ucitajTrenutno(); ucitajDnevnik(vrsta) }, 60000)

  const oznaka = (x) => (x.vrsta === 'prikaceno' ? `🔗 ${t('spremne.prikaceno')}` : `⛓️‍💥 ${t('spremne.otkaceno')}`)
  const kada = (iso) => { try { return new Date(iso).toLocaleString('hr-HR') } catch (_) { return iso } }
  const datumKratko = (iso) => { try { return new Date(iso).toLocaleDateString('hr-HR') } catch (_) { return iso } }

  return (
    <Layout naslov={t('tab.prikapcanje')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('prikapcanje.opis')}</p>

      {/* Trenutno — tko vozi koju prikolicu */}
      <div className="sekcija-naslov" style={{ marginTop: 0 }}>
        🚚 {t('prikapcanje.trenutno')} {trenutno ? `(${trenutno.length})` : ''}
      </div>
      <div className="karta">
        {trenutno === null ? <Spinner /> : trenutno.length === 0 ? (
          <p className="meta" style={{ margin: 0 }}>{t('prikapcanje.nemaTrenutno')}</p>
        ) : (
          <table className="di-tab">
            <thead>
              <tr><th>{t('spremne.kamion')}</th><th>{t('spremne.prikolica')}</th>
                <th>{t('spremne.vozac')}</th><th>{t('spremne.od')}</th></tr>
            </thead>
            <tbody>
              {trenutno.map((x) => (
                <tr key={x.prikolica_gb}>
                  <td><strong>🚚 {x.kamion_gb || '—'}</strong></td>
                  <td>🛻 {x.prikolica_gb}{x.reg ? <span className="meta"> · {x.reg}</span> : ''}</td>
                  <td>{x.vozac || '—'}</td>
                  <td>{x.vrijeme ? datumKratko(x.vrijeme) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Dnevnik svih događaja */}
      <div className="sekcija-naslov">📋 {t('prikapcanje.dnevnik')}</div>
      <div className="karta">
        <div className="vz-filteri no-print">
          {['', 'prikaceno', 'otkaceno'].map((v) => (
            <button key={v || 'sve'} className={'vz-fil' + (vrsta === v ? ' akt' : '')}
              onClick={() => { setVrsta(v); ucitajDnevnik(v) }}>
              {v === '' ? t('vozila.sve') : v === 'prikaceno' ? t('spremne.prikaceno') : t('spremne.otkaceno')}
            </button>
          ))}
          <button className="btn sekund mali" onClick={() => window.print()}>🖨️ {t('spremne.ispisi')}</button>
        </div>
        {rows === null ? <Spinner /> : rows.length === 0 ? (
          <p className="meta">{t('spremne.nemaEvidencije')}</p>
        ) : (
          <div className="dnevnik-ispis">
            <h3 className="di-naslov">{t('spremne.evidencija')}</h3>
            <table className="di-tab">
              <thead>
                <tr><th>{t('spremne.kada')}</th><th>{t('spremne.dogadaj')}</th><th>{t('spremne.kamion')}</th>
                  <th>{t('spremne.prikolica')}</th><th>{t('spremne.vozac')}</th><th>{t('spremne.lokacijaKol')}</th></tr>
              </thead>
              <tbody>
                {rows.map((x) => (
                  <tr key={x.id}>
                    <td>{kada(x.vrijeme)}</td>
                    <td>{oznaka(x)}</td>
                    <td>{x.kamion_gb || '—'}</td>
                    <td>{x.prikolica_gb}</td>
                    <td>{x.vozac || '—'}</td>
                    <td>{x.lokacija || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  )
}
