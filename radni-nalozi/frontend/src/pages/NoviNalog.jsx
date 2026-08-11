import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { PRIORITET, voziloLabel } from '../ui'

export default function NoviNalog() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const prijavaId = params.get('prijava')

  const [vozila, setVozila] = useState([])
  const [radnici, setRadnici] = useState([])
  const [voziloId, setVoziloId] = useState('')
  const [naslov, setNaslov] = useState('')
  const [opis, setOpis] = useState('')
  const [prioritet, setPrioritet] = useState('srednji')
  const [rok, setRok] = useState('')
  const [odabrani, setOdabrani] = useState([])
  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)

  useEffect(() => {
    Promise.all([api.vozila(), api.korisnici('radnik')])
      .then(([v, r]) => { setVozila(v); setRadnici(r) })
      .catch((e) => setGreska(e.message))
  }, [])

  // Predpopuni iz prijave kvara
  useEffect(() => {
    if (!prijavaId) return
    api.prijava(prijavaId).then((p) => {
      setVoziloId(String(p.vozilo_id))
      setNaslov(`Kvar — ${p.vozilo?.gb || ''}`.trim())
      setOpis(p.opis)
      if (p.hitnost === 'visoka') setPrioritet('visok')
    }).catch(() => {})
  }, [prijavaId])

  const toggle = (id) =>
    setOdabrani((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id]))

  const posalji = async (e) => {
    e.preventDefault()
    setGreska('')
    if (!voziloId) { setGreska('Odaberi vozilo.'); return }
    setRadi(true)
    try {
      const n = await api.kreirajNalog({
        vozilo_id: Number(voziloId),
        naslov,
        opis: opis || null,
        prioritet,
        rok: rok || null,
        prijava_id: prijavaId ? Number(prijavaId) : null,
        radnici_ids: odabrani,
      })
      nav(`/nalozi/${n.id}`, { replace: true })
    } catch (err) {
      setGreska(err.message)
      setRadi(false)
    }
  }

  return (
    <Layout naslov="Novi radni nalog" nazad={true}>
      <form onSubmit={posalji}>
        {greska && <div className="greska">{greska}</div>}
        {prijavaId && <div className="uspjeh">Nalog se kreira iz prijave kvara #{prijavaId}.</div>}

        <label>Vozilo (kamion)</label>
        <select value={voziloId} onChange={(e) => setVoziloId(e.target.value)} required>
          <option value="">— odaberi —</option>
          {vozila.map((v) => <option key={v.id} value={v.id}>{voziloLabel(v)}</option>)}
        </select>

        <label>Naslov</label>
        <input value={naslov} onChange={(e) => setNaslov(e.target.value)} placeholder="npr. Popravak kočnica" required />

        <label>Opis posla</label>
        <textarea value={opis} onChange={(e) => setOpis(e.target.value)} placeholder="Detalji zahvata…" />

        <label>Prioritet</label>
        <select value={prioritet} onChange={(e) => setPrioritet(e.target.value)}>
          {Object.entries(PRIORITET).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>

        <label>Rok (opcionalno)</label>
        <input type="date" value={rok} onChange={(e) => setRok(e.target.value)} />

        <label>Dodijeli radnicima</label>
        {radnici.length === 0 ? (
          <p className="meta">Nema radnika — dodaj ih u Šifrarniku.</p>
        ) : (
          <div className="multi">
            {radnici.map((r) => (
              <span key={r.id} className={`opt ${odabrani.includes(r.id) ? 'akt' : ''}`} onClick={() => toggle(r.id)}>
                {r.ime}
              </span>
            ))}
          </div>
        )}

        <button className="btn" disabled={radi} style={{ marginTop: 20 }}>{radi ? 'Kreiram…' : 'Kreiraj nalog'}</button>
      </form>
    </Layout>
  )
}
