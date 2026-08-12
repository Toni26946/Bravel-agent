import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import { Bedz, Spinner, datumVrijeme, voziloLabel } from '../ui'

export default function PrijavaDetalj() {
  const { id } = useParams()
  const { korisnik } = useAuth()
  const { t } = useT()
  const nav = useNavigate()
  const [p, setP] = useState(null)
  const [greska, setGreska] = useState('')

  const ucitaj = () => api.prijava(id).then(setP).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [id])

  if (greska) return <Layout naslov={t('prijava.title')} nazad={true}><div className="greska">{greska}</div></Layout>
  if (!p) return <Layout naslov={t('prijava.title')} nazad={true}><Spinner /></Layout>

  const jeVoditelj = korisnik.uloga === 'voditelj'

  const promijeni = async (status) => {
    try { await api.prijavaStatus(id, status); ucitaj() } catch (e) { setGreska(e.message) }
  }

  return (
    <Layout naslov={t('prijava.title')} nazad={true}>
      <div className="karta">
        <div className="naslov-red">
          <h3>{voziloLabel(p.vozilo)}</h3>
          <Bedz vrsta={p.status} tekst={t('statusp.' + p.status)} />
        </div>
        <p className="meta"><Bedz vrsta={p.hitnost} tekst={t('hitnost.oznaka') + ': ' + t('hitnost.' + p.hitnost)} /></p>
        <p style={{ margin: '12px 0', whiteSpace: 'pre-wrap' }}>{p.opis}</p>
        <p className="meta">{t('prijava.prijavio')}: <strong>{p.prijavio?.ime}</strong></p>
        <p className="meta">{datumVrijeme(p.kreirana)}</p>
      </div>

      {jeVoditelj && (
        <>
          {p.nalog_id ? (
            <button className="btn sekund" onClick={() => nav(`/nalozi/${p.nalog_id}`)} style={{ marginTop: 16 }}>
              {t('prijava.otvoriNalog')}
            </button>
          ) : p.status === 'nova' && (
            <button className="btn" onClick={() => nav(`/nalozi/novi?prijava=${p.id}`)} style={{ marginTop: 16 }}>
              {t('prijava.kreirajNalog')}
            </button>
          )}
          {p.status !== 'zatvorena' && !p.nalog_id && (
            <button className="btn opasno" onClick={() => promijeni('zatvorena')} style={{ marginTop: 8 }}>
              {t('prijava.zatvori')}
            </button>
          )}
        </>
      )}
    </Layout>
  )
}
