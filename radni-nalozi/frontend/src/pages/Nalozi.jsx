import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { Bedz, Prazno, STATUS_NALOG, Spinner, datum, voziloLabel } from '../ui'

const FILTERI = [
  { k: '', t: 'Sve' },
  { k: 'otvoren', t: 'Otvoreni' },
  { k: 'gotov', t: 'Gotovi' },
]

export default function Nalozi() {
  const { korisnik } = useAuth()
  const nav = useNavigate()
  const [lista, setLista] = useState(null)
  const [filter, setFilter] = useState('')
  const [greska, setGreska] = useState('')

  useEffect(() => {
    setLista(null)
    api.nalozi(filter).then(setLista).catch((e) => setGreska(e.message))
  }, [filter])

  const naslov = korisnik.uloga === 'radnik' ? 'Moji nalozi' : 'Radni nalozi'

  return (
    <Layout naslov={naslov}>
      <div className="chips">
        {FILTERI.map((f) => (
          <span key={f.k} className={`chip ${filter === f.k ? 'akt' : ''}`} onClick={() => setFilter(f.k)}>{f.t}</span>
        ))}
      </div>

      {greska && <div className="greska">{greska}</div>}
      {lista === null ? (
        <Spinner />
      ) : lista.length === 0 ? (
        <Prazno emo="🔧" tekst="Nema naloga za prikaz." />
      ) : (
        lista.map((n) => (
          <div key={n.id} className="karta klik" onClick={() => nav(`/nalozi/${n.id}`)}>
            <div className="naslov-red">
              <div>
                <p className="meta" style={{ margin: 0 }}>{n.broj}</p>
                <h3>{n.naslov}</h3>
              </div>
              <Bedz vrsta={n.status} tekst={STATUS_NALOG[n.status]} />
            </div>
            <p className="meta">🚚 {voziloLabel(n.vozilo)}</p>
            {n.rok && <p className="meta">📅 rok: {datum(n.rok)}</p>}
            {(n.voditelj || n.vozac) && (
              <p className="meta">
                {n.voditelj && <>🧑‍🔧 {n.voditelj.ime}</>}
                {n.vozac && <> &nbsp; 🚛 {n.vozac.ime}</>}
              </p>
            )}
          </div>
        ))
      )}

      {korisnik.uloga === 'voditelj' && (
        <button className="fab" onClick={() => nav('/nalozi/novi')} aria-label="Novi nalog">+</button>
      )}
    </Layout>
  )
}
