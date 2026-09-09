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
    </Layout>
  )
}
