import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { HITNOST, MikrofonGumb, voziloLabel } from '../ui'
import { useT } from '../i18n'

export default function NovaPrijava() {
  const { t } = useT()
  const nav = useNavigate()
  const [vozila, setVozila] = useState([])
  const [voziloId, setVoziloId] = useState('')
  const [opis, setOpis] = useState('')
  const [hitnost, setHitnost] = useState('srednja')
  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)

  useEffect(() => {
    api.vozila().then((v) => {
      setVozila(v)
      if (v.length) setVoziloId(String(v[0].id))
    }).catch((e) => setGreska(e.message))
  }, [])

  const posalji = async (e) => {
    e.preventDefault()
    setGreska('')
    if (!voziloId) { setGreska(t('prijava.odaberiVozilo')); return }
    setRadi(true)
    try {
      const fd = new FormData()
      fd.append('vozilo_id', voziloId)
      fd.append('opis', opis)
      fd.append('hitnost', hitnost)
      await api.kreirajPrijavu(fd)
      nav('/prijave')
    } catch (err) {
      setGreska(err.message)
      setRadi(false)
    }
  }

  return (
    <Layout naslov={t('prijava.naslov')} nazad="/prijave">
      <form onSubmit={posalji}>
        {greska && <div className="greska">{greska}</div>}

        <label>{t('prijava.vozilo')}</label>
        <select value={voziloId} onChange={(e) => setVoziloId(e.target.value)} required>
          {vozila.length === 0 && <option value="">{t('prijava.nemaVozila')}</option>}
          {vozila.map((v) => <option key={v.id} value={v.id}>{voziloLabel(v)}</option>)}
        </select>

        <label>{t('prijava.opisKvara')}</label>
        <div className="polje-mik">
          <textarea value={opis} onChange={(e) => setOpis(e.target.value)} placeholder={t('prijava.phOpis')} required />
          <MikrofonGumb naslov={t('prijava.diktirajOpis')} onTekst={(tekst) => setOpis((v) => (v ? v + ' ' : '') + tekst)} />
        </div>

        <label>{t('hitnost.oznaka')}</label>
        <select value={hitnost} onChange={(e) => setHitnost(e.target.value)}>
          {Object.keys(HITNOST).map((k) => <option key={k} value={k}>{t('hitnost.' + k)}</option>)}
        </select>

        <button className="btn" disabled={radi}>{radi ? t('prijava.salji') : t('prijava.posalji')}</button>
      </form>
    </Layout>
  )
}
