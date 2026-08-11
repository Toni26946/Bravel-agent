import { useEffect, useRef, useState } from 'react'
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
  const [brisi, setBrisi] = useState(null) // nalog koji se potvrđuje za brisanje

  const jeVoditelj = korisnik.uloga === 'voditelj'
  const timerRef = useRef(null)
  const dugiRef = useRef(false)

  const ucitaj = () => {
    setLista(null)
    api.nalozi(filter).then(setLista).catch((e) => setGreska(e.message))
  }
  useEffect(() => { ucitaj() }, [filter])

  // Dugi pritisak (samo voditelj) → ponudi brisanje
  const start = (n) => {
    if (!jeVoditelj) return
    dugiRef.current = false
    timerRef.current = setTimeout(() => {
      dugiRef.current = true
      if (navigator.vibrate) navigator.vibrate(30)
      setBrisi(n)
    }, 500)
  }
  const kraj = () => clearTimeout(timerRef.current)
  const klik = (n) => {
    if (dugiRef.current) { dugiRef.current = false; return } // bio je dugi pritisak — ne otvaraj
    nav(`/nalozi/${n.id}`)
  }

  const obrisi = async () => {
    try {
      await api.obrisiNalog(brisi.id)
      setBrisi(null)
      ucitaj()
    } catch (e) {
      setGreska(e.message)
      setBrisi(null)
    }
  }

  const naslov = korisnik.uloga === 'radnik' ? 'Moji nalozi' : 'Radni nalozi'

  return (
    <Layout naslov={naslov}>
      <div className="chips">
        {FILTERI.map((f) => (
          <span key={f.k} className={`chip ${filter === f.k ? 'akt' : ''}`} onClick={() => setFilter(f.k)}>{f.t}</span>
        ))}
      </div>

      {greska && <div className="greska">{greska}</div>}
      {jeVoditelj && lista?.length > 0 && (
        <p className="meta" style={{ marginTop: 0 }}>Savjet: dugim pritiskom na nalog možeš ga obrisati.</p>
      )}
      {lista === null ? (
        <Spinner />
      ) : lista.length === 0 ? (
        <Prazno emo="🔧" tekst="Nema naloga za prikaz." />
      ) : (
        lista.map((n) => (
          <div
            key={n.id}
            className="karta klik"
            onClick={() => klik(n)}
            onTouchStart={() => start(n)}
            onTouchEnd={kraj}
            onTouchMove={kraj}
            onMouseDown={() => start(n)}
            onMouseUp={kraj}
            onMouseLeave={kraj}
            onContextMenu={(e) => { if (jeVoditelj) { e.preventDefault(); setBrisi(n) } }}
          >
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

      {/* Potvrda brisanja */}
      {brisi && (
        <div className="sheet-bg" onClick={() => setBrisi(null)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Obrisati nalog?</h3>
            <p className="meta">{brisi.broj} · {brisi.naslov}</p>
            <p className="meta" style={{ marginBottom: 16 }}>🚚 {voziloLabel(brisi.vozilo)} — brisanje je trajno.</p>
            <button className="btn opasno" onClick={obrisi}>Obriši nalog</button>
            <button className="btn sekund" onClick={() => setBrisi(null)} style={{ marginTop: 8 }}>Odustani</button>
          </div>
        </div>
      )}
    </Layout>
  )
}
