import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'
import PovijestDijelova from '../PovijestDijelova'

export default function VoziloDetalj() {
  const { id } = useParams()
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

      <div className="sekcija-naslov">Povijest dijelova</div>
      <PovijestDijelova vozilo={vozilo} />
    </Layout>
  )
}
