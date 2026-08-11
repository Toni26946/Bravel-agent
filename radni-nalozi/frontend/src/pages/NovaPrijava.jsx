import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { HITNOST, voziloLabel } from '../ui'

export default function NovaPrijava() {
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
    if (!voziloId) { setGreska('Odaberi vozilo.'); return }
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
    <Layout naslov="Nova prijava kvara" nazad="/prijave">
      <form onSubmit={posalji}>
        {greska && <div className="greska">{greska}</div>}

        <label>Vozilo (kamion)</label>
        <select value={voziloId} onChange={(e) => setVoziloId(e.target.value)} required>
          {vozila.length === 0 && <option value="">Nema vozila</option>}
          {vozila.map((v) => <option key={v.id} value={v.id}>{voziloLabel(v)}</option>)}
        </select>

        <label>Opis kvara</label>
        <textarea value={opis} onChange={(e) => setOpis(e.target.value)} placeholder="Što ne valja s vozilom?" required />

        <label>Hitnost</label>
        <select value={hitnost} onChange={(e) => setHitnost(e.target.value)}>
          {Object.entries(HITNOST).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>

        <button className="btn" disabled={radi}>{radi ? 'Šaljem…' : 'Pošalji prijavu'}</button>
      </form>
    </Layout>
  )
}
