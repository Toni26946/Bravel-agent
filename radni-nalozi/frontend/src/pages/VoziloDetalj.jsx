import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, datum } from '../ui'
import { useT } from '../i18n'
import PovijestDijelova from '../PovijestDijelova'

export default function VoziloDetalj() {
  const { id } = useParams()
  const { t } = useT()
  const [vozilo, setVozilo] = useState(null)
  const [greska, setGreska] = useState('')

  useEffect(() => {
    api.vozilo(id).then(setVozilo).catch((e) => setGreska(e.message))
  }, [id])

  if (greska) return <Layout naslov="Kamion" nazad={true}><div className="greska">{greska}</div></Layout>
  if (!vozilo) return <Layout naslov="Kamion" nazad={true}><Spinner /></Layout>

  return (
    <Layout naslov={vozilo.gb} nazad={true}>
      <div className="karta">
        <h3 style={{ margin: 0 }}>🚚 {vozilo.gb}</h3>
        <p className="meta" style={{ margin: '4px 0 0' }}>
          {[vozilo.marka, vozilo.model, vozilo.registracija].filter(Boolean).join(' · ') || '—'}
        </p>
      </div>

      <div className="sekcija-naslov">{t('voz.servisnaPovijest')}</div>
      <ServisnaPovijest voziloId={id} />

      <div className="sekcija-naslov">Povijest dijelova</div>
      <PovijestDijelova vozilo={vozilo} />
    </Layout>
  )
}

function trajanjeMin(m) {
  if (!m) return ''
  const h = Math.floor(m / 60), mi = m % 60
  return h > 0 ? `${h} h ${mi} min` : `${mi} min`
}

function ServisnaPovijest({ voziloId }) {
  const { t } = useT()
  const [stavke, setStavke] = useState(null)
  const [greska, setGreska] = useState('')

  useEffect(() => {
    api.povijestRada(voziloId).then(setStavke).catch((e) => setGreska(e.message))
  }, [voziloId])

  if (greska) return <div className="greska">{greska}</div>
  if (!stavke) return <Spinner />
  if (stavke.length === 0) return <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('voz.nemaPovijesti')}</p></div>

  return (
    <div className="op-tablica">
      <div className="pr-head">
        <div>{t('voz.datum')}</div><div>{t('voz.radnik')}</div><div>{t('voz.posao')}</div>
      </div>
      {stavke.map((s) => (
        <div className="pr-red" key={s.id}>
          <div className="pr-datum">{datum(s.datum)}</div>
          <div>{s.radnik || '—'}</div>
          <div>
            {s.operacija || s.opis || <span className="meta">—</span>}
            {s.minute ? <span className="pr-min"> · {trajanjeMin(s.minute)}</span> : null}
          </div>
        </div>
      ))}
    </div>
  )
}
