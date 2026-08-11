import { useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
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

      <PromjenaLozinke />

      <button className="btn sekund" onClick={ukljuciObavijesti} style={{ marginTop: 12 }}>🔔 Uključi push obavijesti</button>
      <button className="btn opasno" onClick={odjava} style={{ marginTop: 12 }}>Odjava</button>

      <p className="meta" style={{ textAlign: 'center', marginTop: 24 }}>
        Savjet: dodaj aplikaciju na početni zaslon (izbornik preglednika → „Dodaj na početni zaslon”).
      </p>
    </Layout>
  )
}

function PromjenaLozinke() {
  const [otvori, setOtvori] = useState(false)
  const [stara, setStara] = useState('')
  const [nova, setNova] = useState('')
  const [potvrda, setPotvrda] = useState('')
  const [greska, setGreska] = useState('')
  const [uspjeh, setUspjeh] = useState('')
  const [radi, setRadi] = useState(false)

  if (!otvori) {
    return (
      <button className="btn sekund" onClick={() => setOtvori(true)} style={{ marginTop: 12 }}>
        🔑 Promijeni lozinku
      </button>
    )
  }

  const spremi = async (e) => {
    e.preventDefault()
    setGreska(''); setUspjeh('')
    if (nova.length < 4) { setGreska('Nova lozinka mora imati barem 4 znaka.'); return }
    if (nova !== potvrda) { setGreska('Nova lozinka i potvrda se ne podudaraju.'); return }
    setRadi(true)
    try {
      await api.promijeniLozinku(stara, nova)
      setUspjeh('Lozinka je promijenjena ✅')
      setStara(''); setNova(''); setPotvrda('')
      setOtvori(false)
    } catch (err) {
      setGreska(err.message)
    } finally {
      setRadi(false)
    }
  }

  return (
    <form className="karta" onSubmit={spremi} style={{ marginTop: 12 }}>
      <h3 style={{ marginTop: 0 }}>Promjena lozinke</h3>
      {greska && <div className="greska">{greska}</div>}
      {uspjeh && <div className="uspjeh">{uspjeh}</div>}
      <label>Trenutna lozinka</label>
      <input type="password" value={stara} onChange={(e) => setStara(e.target.value)} autoComplete="current-password" required />
      <label>Nova lozinka</label>
      <input type="password" value={nova} onChange={(e) => setNova(e.target.value)} autoComplete="new-password" required />
      <label>Ponovi novu lozinku</label>
      <input type="password" value={potvrda} onChange={(e) => setPotvrda(e.target.value)} autoComplete="new-password" required />
      <div className="btn-red">
        <button className="btn mali" disabled={radi}>{radi ? 'Spremam…' : 'Spremi'}</button>
        <button type="button" className="btn sekund mali" onClick={() => { setOtvori(false); setGreska('') }}>Odustani</button>
      </div>
    </form>
  )
}
