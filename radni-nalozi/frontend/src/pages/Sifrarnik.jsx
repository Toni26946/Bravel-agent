import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Bedz, MikrofonGumb, Spinner, ULOGA, datum, voziloLabel } from '../ui'

export default function Sifrarnik() {
  const [tab, setTab] = useState('korisnici')
  return (
    <Layout naslov="Šifrarnik">
      <div className="chips">
        <span className={`chip ${tab === 'korisnici' ? 'akt' : ''}`} onClick={() => setTab('korisnici')}>Korisnici</span>
        <span className={`chip ${tab === 'vozila' ? 'akt' : ''}`} onClick={() => setTab('vozila')}>Vozila</span>
        <span className={`chip ${tab === 'dijelovi' ? 'akt' : ''}`} onClick={() => setTab('dijelovi')}>Dijelovi</span>
      </div>
      {tab === 'korisnici' && <Korisnici />}
      {tab === 'vozila' && <Vozila />}
      {tab === 'dijelovi' && <PretragaDijelova />}
    </Layout>
  )
}

// Globalna pretraga povijesti dijelova po nazivu (kroz sve kamione).
function PretragaDijelova() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')

  useEffect(() => {
    let poništen = false
    const t = setTimeout(() => {
      api.pretraziDijelove(q)
        .then((r) => { if (!poništen) setLista(r) })
        .catch((e) => { if (!poništen) setGreska(e.message) })
    }, 250)
    return () => { poništen = true; clearTimeout(t) }
  }, [q])

  return (
    <>
      {greska && <div className="greska">{greska}</div>}
      <div className="polje-mik">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Pretraži po nazivu dijela (npr. pločice)"
          autoFocus
        />
        <MikrofonGumb naslov="Izgovori naziv dijela" onTekst={(t) => setQ(t)} />
      </div>

      {lista === null ? (
        <p className="meta" style={{ marginTop: 12 }}>Učitavam…</p>
      ) : lista.length === 0 ? (
        <p className="meta" style={{ marginTop: 12 }}>
          {q.trim() ? `Nema rezultata za „${q.trim()}".` : 'Još nema zabilježenih zamjena dijelova.'}
        </p>
      ) : (
        <>
          <p className="meta" style={{ marginTop: 12 }}>{lista.length} {lista.length === 1 ? 'rezultat' : 'rezultata'}</p>
          <div className="dio-lista">
            {lista.map((z) => (
              <div key={z.id} className="dio-zapis dio-klik" onClick={() => nav(`/vozila/${z.vozilo.id}`)}>
                <div className="dio-glava">
                  <strong>{z.naziv}</strong>
                  <span className="dio-datum">{datum(z.datum)}</span>
                </div>
                <p className="meta" style={{ margin: '2px 0 0' }}>🚚 <strong>{z.vozilo.gb}</strong></p>
                {z.razlog && <p className="dio-razlog">{z.razlog}</p>}
                <p className="meta">
                  {z.kilometraza != null && <>🧭 {z.kilometraza.toLocaleString('hr-HR')} km · </>}
                  {z.promijenio?.ime} ›
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </>
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
  const nav = useNavigate()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [otvori, setOtvori] = useState(false)
  const [uvozOtvori, setUvozOtvori] = useState(false)
  const [uvozTekst, setUvozTekst] = useState('')
  const [uvozRezultat, setUvozRezultat] = useState(null)
  const [uvozRadi, setUvozRadi] = useState(false)
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

  const uvezi = async () => {
    setGreska(''); setUvozRezultat(null); setUvozRadi(true)
    try {
      const r = await api.uvozVozila(uvozTekst)
      setUvozRezultat(r); setUvozTekst(''); ucitaj()
    } catch (err) { setGreska(err.message) } finally { setUvozRadi(false) }
  }

  if (lista === null) return <Spinner />
  return (
    <>
      {greska && <div className="greska">{greska}</div>}

      {/* Uvoz postojećih kamiona */}
      {!uvozOtvori ? (
        <button className="btn sekund" onClick={() => setUvozOtvori(true)}>📋 Uvezi popis kamiona (iz Excela)</button>
      ) : (
        <div className="karta">
          <label style={{ marginTop: 0 }}>Zalijepi popis (jedan kamion po retku)</label>
          <p className="meta" style={{ marginTop: 0 }}>
            Svaki redak počinje <strong>GB</strong>. Možeš zalijepiti i cijele stupce iz Excela
            (GB, VOZILO, REG OZNAKA) — registracija se prepozna sama, redoslijed nije bitan.
            Postojeći kamioni se preskaču.
          </p>
          <textarea
            value={uvozTekst}
            onChange={(e) => setUvozTekst(e.target.value)}
            placeholder={'GB-101\nGB-102, ZG1234AB, MAN\nGB-103, ZG5678CD, Scania'}
            style={{ minHeight: 140, fontFamily: 'monospace' }}
          />
          {uvozRezultat && (
            <div className="uspjeh">Dodano {uvozRezultat.dodano}, preskočeno {uvozRezultat.preskoceno} (već postoje). Ukupno redaka: {uvozRezultat.ukupno}.</div>
          )}
          <div className="btn-red">
            <button className="btn mali" onClick={uvezi} disabled={uvozRadi || !uvozTekst.trim()}>{uvozRadi ? 'Uvozim…' : 'Uvezi'}</button>
            <button className="btn sekund mali" onClick={() => { setUvozOtvori(false); setUvozRezultat(null) }}>Zatvori</button>
          </div>
        </div>
      )}

      {!otvori && <button className="btn" onClick={() => setOtvori(true)} style={{ marginTop: 12 }}>+ Novo vozilo</button>}
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
        <div key={v.id} className="karta klik" onClick={() => nav(`/vozila/${v.id}`)}>
          <div className="naslov-red">
            <div>
              <h3 style={{ margin: 0 }}>{v.gb}</h3>
              <p className="meta" style={{ margin: '4px 0 0' }}>{[v.marka, v.model, v.registracija].filter(Boolean).join(' · ') || '—'}</p>
            </div>
            <span className="meta" style={{ fontSize: 13 }}>Povijest ›</span>
          </div>
        </div>
      ))}
    </>
  )
}
