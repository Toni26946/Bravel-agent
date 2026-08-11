import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Bedz, Spinner, ULOGA, voziloLabel } from '../ui'

export default function Sifrarnik() {
  const [tab, setTab] = useState('korisnici')
  return (
    <Layout naslov="Šifrarnik">
      <div className="chips">
        <span className={`chip ${tab === 'korisnici' ? 'akt' : ''}`} onClick={() => setTab('korisnici')}>Korisnici</span>
        <span className={`chip ${tab === 'vozila' ? 'akt' : ''}`} onClick={() => setTab('vozila')}>Vozila</span>
      </div>
      {tab === 'korisnici' ? <Korisnici /> : <Vozila />}
    </Layout>
  )
}

function Korisnici() {
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [otvori, setOtvori] = useState(false)
  const [f, setF] = useState({ ime: '', korisnicko_ime: '', lozinka: '', uloga: 'radnik', telefon: '' })

  const ucitaj = () => api.korisnici().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])

  const spremi = async (e) => {
    e.preventDefault()
    setGreska('')
    try {
      await api.kreirajKorisnika(f)
      setF({ ime: '', korisnicko_ime: '', lozinka: '', uloga: 'radnik', telefon: '' })
      setOtvori(false); ucitaj()
    } catch (err) { setGreska(err.message) }
  }

  const prebaciAktivan = async (k) => {
    await api.azurirajKorisnika(k.id, { aktivan: !k.aktivan }); ucitaj()
  }

  if (lista === null) return <Spinner />
  return (
    <>
      {greska && <div className="greska">{greska}</div>}
      {!otvori && <button className="btn" onClick={() => setOtvori(true)}>+ Novi korisnik</button>}
      {otvori && (
        <form className="karta" onSubmit={spremi}>
          <label>Ime i prezime</label>
          <input value={f.ime} onChange={(e) => setF({ ...f, ime: e.target.value })} required />
          <label>Korisničko ime</label>
          <input value={f.korisnicko_ime} onChange={(e) => setF({ ...f, korisnicko_ime: e.target.value })} autoCapitalize="none" required />
          <label>Lozinka</label>
          <input value={f.lozinka} onChange={(e) => setF({ ...f, lozinka: e.target.value })} required />
          <label>Uloga</label>
          <select value={f.uloga} onChange={(e) => setF({ ...f, uloga: e.target.value })}>
            {Object.entries(ULOGA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label>Telefon (opcionalno)</label>
          <input value={f.telefon} onChange={(e) => setF({ ...f, telefon: e.target.value })} />
          <div className="btn-red">
            <button className="btn mali">Spremi</button>
            <button type="button" className="btn sekund mali" onClick={() => setOtvori(false)}>Odustani</button>
          </div>
        </form>
      )}
      {lista.map((k) => (
        <div key={k.id} className="karta">
          <div className="naslov-red">
            <h3 style={{ opacity: k.aktivan ? 1 : 0.5 }}>{k.ime}</h3>
            <Bedz vrsta="srednji" tekst={ULOGA[k.uloga]} />
          </div>
          <p className="meta">@{k.korisnicko_ime}{k.telefon ? ` · ${k.telefon}` : ''}</p>
          <div className="btn-red">
            <button className="btn sekund mali" onClick={() => prebaciAktivan(k)}>
              {k.aktivan ? 'Deaktiviraj' : 'Aktiviraj'}
            </button>
          </div>
          <ResetLozinke korisnikId={k.id} naGresku={setGreska} />
        </div>
      ))}
    </>
  )
}

function ResetLozinke({ korisnikId, naGresku }) {
  const [otvori, setOtvori] = useState(false)
  const [nova, setNova] = useState('')
  const [uspjeh, setUspjeh] = useState(false)
  const [radi, setRadi] = useState(false)

  if (uspjeh) return <p className="meta" style={{ color: 'var(--zelena)', marginTop: 8 }}>Lozinka resetirana ✅</p>
  if (!otvori) {
    return (
      <button className="btn sekund mali" style={{ marginTop: 8 }} onClick={() => setOtvori(true)}>
        🔑 Resetiraj lozinku
      </button>
    )
  }
  const spremi = async () => {
    if (nova.length < 4) { naGresku('Lozinka mora imati barem 4 znaka.'); return }
    setRadi(true)
    try {
      await api.azurirajKorisnika(korisnikId, { lozinka: nova })
      setUspjeh(true)
    } catch (e) { naGresku(e.message) } finally { setRadi(false) }
  }
  return (
    <div style={{ marginTop: 8 }}>
      <input type="text" placeholder="Nova lozinka" value={nova} onChange={(e) => setNova(e.target.value)} />
      <div className="btn-red">
        <button className="btn mali" onClick={spremi} disabled={radi || !nova}>Postavi</button>
        <button className="btn sekund mali" onClick={() => setOtvori(false)}>Odustani</button>
      </div>
    </div>
  )
}

function Vozila() {
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [otvori, setOtvori] = useState(false)
  const [f, setF] = useState({ gb: '', registracija: '', marka: '', model: '' })

  const ucitaj = () => api.vozila().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])

  const spremi = async (e) => {
    e.preventDefault()
    setGreska('')
    try {
      await api.kreirajVozilo(f)
      setF({ gb: '', registracija: '', marka: '', model: '' })
      setOtvori(false); ucitaj()
    } catch (err) { setGreska(err.message) }
  }

  if (lista === null) return <Spinner />
  return (
    <>
      {greska && <div className="greska">{greska}</div>}
      {!otvori && <button className="btn" onClick={() => setOtvori(true)}>+ Novo vozilo</button>}
      {otvori && (
        <form className="karta" onSubmit={spremi}>
          <label>Garažni broj (GB)</label>
          <input value={f.gb} onChange={(e) => setF({ ...f, gb: e.target.value })} required />
          <label>Registracija</label>
          <input value={f.registracija} onChange={(e) => setF({ ...f, registracija: e.target.value })} />
          <label>Marka</label>
          <input value={f.marka} onChange={(e) => setF({ ...f, marka: e.target.value })} />
          <label>Model</label>
          <input value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} />
          <div className="btn-red">
            <button className="btn mali">Spremi</button>
            <button type="button" className="btn sekund mali" onClick={() => setOtvori(false)}>Odustani</button>
          </div>
        </form>
      )}
      {lista.map((v) => (
        <div key={v.id} className="karta">
          <h3>{v.gb}</h3>
          <p className="meta">{[v.marka, v.model, v.registracija].filter(Boolean).join(' · ') || '—'}</p>
        </div>
      ))}
    </>
  )
}
