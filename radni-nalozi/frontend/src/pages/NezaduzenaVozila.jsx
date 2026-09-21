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
  const [nalozi, setNalozi] = useState(null)
  const [greska, setGreska] = useState('')

  const ucitaj = () => api.nezaduzena().then(setNalozi).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])
  useAutoOsvjezi(() => api.nezaduzena().then(setNalozi).catch(() => {}), 30000)

  if (greska) return <Layout naslov={t('tab.nezaduzena')}><div className="greska">{greska}</div></Layout>
  if (!nalozi) return <Layout naslov={t('tab.nezaduzena')}><Spinner /></Layout>

  return (
    <Layout naslov={t('tab.nezaduzena')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('nezaduzena.opis')}</p>
      {nalozi.length === 0 ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('nezaduzena.nema')}</p></div>
      ) : (
        nalozi.map((n) => (
          <div className="karta izasli-red" key={n.id} onClick={() => nav(`/nalozi/${n.id}`)}>
            <div className="izasli-info">
              <div className="izasli-gb">🛻 {n.vozilo?.gb}</div>
              <div className="meta">{n.broj} · {t('status.' + n.status)}{n.vozilo?.registracija ? ` · ${n.vozilo.registracija}` : ''}</div>
            </div>
          </div>
        ))
      )}
    </Layout>
  )
}
