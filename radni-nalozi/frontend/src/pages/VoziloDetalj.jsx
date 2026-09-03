import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import Layout from '../Layout'
import { api, medijUrl } from '../api'
import { useAuth } from '../auth'
import { Spinner, datum } from '../ui'
import { useT } from '../i18n'
import PovijestDijelova from '../PovijestDijelova'

export default function VoziloDetalj() {
  const { id } = useParams()
  const { t } = useT()
  const { korisnik } = useAuth()
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
        <div className="voz-glava">
          <SlikaVozila vozilo={vozilo} setVozilo={setVozilo} jeVoditelj={korisnik.uloga === 'voditelj'} naGresku={setGreska} />
          <div>
            <h3 style={{ margin: 0 }}>🚚 {vozilo.gb}</h3>
            <p className="meta" style={{ margin: '4px 0 0' }}>
              {[vozilo.marka, vozilo.model, vozilo.registracija].filter(Boolean).join(' · ') || '—'}
            </p>
          </div>
        </div>
      </div>

      <div className="sekcija-naslov">{t('voz.servisnaPovijest')}</div>
      <ServisnaPovijest voziloId={id} />

      <div className="sekcija-naslov">Povijest dijelova</div>
      <PovijestDijelova vozilo={vozilo} />
    </Layout>
  )
}

function SlikaVozila({ vozilo, setVozilo, jeVoditelj, naGresku }) {
  const { t } = useT()
  const input = useRef(null)
  const [radi, setRadi] = useState(false)

  const odaberi = async (e) => {
    const f = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!f) return
    setRadi(true)
    try {
      const fd = new FormData()
      fd.append('slika', f)
      const v = await api.postaviSlikuVozila(vozilo.id, fd)
      setVozilo(v)
    } catch (err) { naGresku(err.message) } finally { setRadi(false) }
  }
  const ukloni = async () => {
    setRadi(true)
    try { setVozilo(await api.obrisiSlikuVozila(vozilo.id)) }
    catch (err) { naGresku(err.message) } finally { setRadi(false) }
  }

  return (
    <div className="voz-slika-blok">
      <div
        className={'voz-slika' + (jeVoditelj ? ' klik' : '')}
        onClick={() => jeVoditelj && !radi && input.current?.click()}
        title={jeVoditelj ? t('voz.dodajSliku') : ''}
      >
        {vozilo.slika ? <img src={medijUrl(vozilo.slika)} alt={vozilo.gb} /> : <span className="voz-slika-ph">🚚</span>}
        {radi && <span className="voz-slika-radi">…</span>}
      </div>
      {jeVoditelj && (
        <div className="voz-slika-akcije">
          <input ref={input} type="file" accept="image/*" style={{ display: 'none' }} onChange={odaberi} />
          <button className="btn sekund mali" onClick={() => input.current?.click()} disabled={radi}>
            {vozilo.slika ? t('voz.promijeniSliku') : t('voz.dodajSliku')}
          </button>
          {vozilo.slika && <span className="voz-ukloni" onClick={() => !radi && ukloni()}>{t('voz.ukloniSliku')}</span>}
        </div>
      )}
    </div>
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
          <div className="pr-radnik">{s.radnik || '—'}</div>
          <div>
            {s.operacija && <span className="pr-op">{s.operacija}</span>}
            {s.opis && <span className="pr-opis">{s.opis}</span>}
            {!s.operacija && !s.opis && <span className="meta">—</span>}
            {s.minute ? <span className="pr-min">⏱ {trajanjeMin(s.minute)}</span> : null}
          </div>
        </div>
      ))}
    </div>
  )
}
