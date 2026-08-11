import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Bedz, HITNOST, Prazno, STATUS_PRIJAVA, Spinner, datumVrijeme, voziloLabel } from '../ui'
import { useAuth } from '../auth'

export default function Prijave() {
  const { korisnik } = useAuth()
  const nav = useNavigate()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')

  useEffect(() => {
    api.prijave().then(setLista).catch((e) => setGreska(e.message))
  }, [])

  const naslov = korisnik.uloga === 'vozac' ? 'Moje prijave' : 'Prijave kvarova'

  return (
    <Layout naslov={naslov}>
      {greska && <div className="greska">{greska}</div>}
      {lista === null ? (
        <Spinner />
      ) : lista.length === 0 ? (
        <Prazno emo="🔧" tekst={korisnik.uloga === 'vozac' ? 'Još nemaš prijavljenih kvarova.' : 'Nema prijava kvarova.'} />
      ) : (
        lista.map((p) => (
          <div key={p.id} className="karta klik" onClick={() => nav(`/prijave/${p.id}`)}>
            <div className="naslov-red">
              <h3>{voziloLabel(p.vozilo)}</h3>
              <Bedz vrsta={p.status} tekst={STATUS_PRIJAVA[p.status]} />
            </div>
            <p className="meta">{p.opis.length > 90 ? p.opis.slice(0, 90) + '…' : p.opis}</p>
            <p className="meta">
              <Bedz vrsta={p.hitnost} tekst={'Hitnost: ' + HITNOST[p.hitnost]} />
              {korisnik.uloga !== 'vozac' && <> &nbsp; {p.prijavio?.ime}</>}
            </p>
            <p className="meta">{datumVrijeme(p.kreirana)}</p>
          </div>
        ))
      )}
      <button className="fab" onClick={() => nav('/prijave/nova')} aria-label="Nova prijava">+</button>
    </Layout>
  )
}
