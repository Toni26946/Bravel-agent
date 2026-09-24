import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useT } from '../i18n'

// Dnevnik prikapčanja/otkapčanja priključnih vozila — vlastita stranica (evidencija/dokaz).
// Filtri Sve/Prikačeno/Otkačeno + ispis. Zapisi nastaju kad se šlepa uzme ("Uzeta")
// ili označi Spremno (otkačeno) na ekranu Spremne.
export default function EvidencijaPrikapcanja() {
  const { t } = useT()
  const [rows, setRows] = useState(null)
  const [vrsta, setVrsta] = useState('')

  const ucitaj = (v = vrsta) => api.dnevnikPrikapcanja({ vrsta: v, dana: 180 }).then(setRows).catch(() => setRows([]))
  useEffect(() => { ucitaj('') }, [])
  useAutoOsvjezi(() => api.dnevnikPrikapcanja({ vrsta, dana: 180 }).then(setRows).catch(() => {}), 60000)

  const oznaka = (x) => (x.vrsta === 'prikaceno' ? `🔗 ${t('spremne.prikaceno')}` : `⛓️‍💥 ${t('spremne.otkaceno')}`)
  const kada = (iso) => { try { return new Date(iso).toLocaleString('hr-HR') } catch (_) { return iso } }

  return (
    <Layout naslov={t('tab.prikapcanje')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('prikapcanje.opis')}</p>
      <div className="karta">
        <div className="vz-filteri no-print">
          {['', 'prikaceno', 'otkaceno'].map((v) => (
            <button key={v || 'sve'} className={'vz-fil' + (vrsta === v ? ' akt' : '')}
              onClick={() => { setVrsta(v); ucitaj(v) }}>
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
                <tr><th>{t('spremne.kada')}</th><th>{t('spremne.dogadaj')}</th><th>{t('spremne.prikolica')}</th>
                  <th>{t('spremne.kamion')}</th><th>{t('spremne.vozac')}</th><th>{t('spremne.lokacijaKol')}</th></tr>
              </thead>
              <tbody>
                {rows.map((x) => (
                  <tr key={x.id}>
                    <td>{kada(x.vrijeme)}</td>
                    <td>{oznaka(x)}</td>
                    <td>{x.prikolica_gb}</td>
                    <td>{x.kamion_gb || '—'}</td>
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
