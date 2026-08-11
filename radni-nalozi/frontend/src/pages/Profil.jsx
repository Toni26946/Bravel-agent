import { useState } from 'react'
import Layout from '../Layout'
import { useAuth } from '../auth'
import { omoguciPush } from '../push'
import { ULOGA } from '../ui'

export default function Profil() {
  const { korisnik, odjava } = useAuth()
  const [poruka, setPoruka] = useState('')

  const ukljuciObavijesti = async () => {
    await omoguciPush()
    if (Notification.permission === 'granted') setPoruka('Obavijesti su uključene ✅')
    else setPoruka('Obavijesti nisu dopuštene u pregledniku.')
  }

  return (
    <Layout naslov="Profil">
      <div className="karta">
        <h3>{korisnik.ime}</h3>
        <p className="meta">Korisničko ime: <strong>{korisnik.korisnicko_ime}</strong></p>
        <p className="meta">Uloga: <strong>{ULOGA[korisnik.uloga]}</strong></p>
        {korisnik.telefon && <p className="meta">Telefon: <strong>{korisnik.telefon}</strong></p>}
      </div>

      {poruka && <div className="uspjeh">{poruka}</div>}

      <button className="btn sekund" onClick={ukljuciObavijesti}>🔔 Uključi push obavijesti</button>
      <button className="btn opasno" onClick={odjava} style={{ marginTop: 12 }}>Odjava</button>

      <p className="meta" style={{ textAlign: 'center', marginTop: 24 }}>
        Savjet: dodaj aplikaciju na početni zaslon (izbornik preglednika → „Dodaj na početni zaslon”).
      </p>
    </Layout>
  )
}
