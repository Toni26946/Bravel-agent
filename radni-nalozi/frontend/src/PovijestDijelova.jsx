import { useEffect, useState } from 'react'
import { api } from './api'
import { useAuth } from './auth'
import { MikrofonGumb, datum } from './ui'

// Povijest zamjene dijelova za jedan kamion (kada i zašto su se mijenjali).
// Koristi se na stranici kamiona i unutar radnog naloga.
export default function PovijestDijelova({ vozilo, nalogId = null }) {
  const { korisnik } = useAuth()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [otvori, setOtvori] = useState(false)

  const ucitaj = () => api.povijestDijelova(vozilo.id).then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => { if (vozilo?.id) ucitaj() }, [vozilo?.id])

  const obrisi = async (z) => {
    if (!window.confirm('Obrisati ovaj zapis iz povijesti?')) return
    try { await api.obrisiZamjenuDijela(vozilo.id, z.id); ucitaj() } catch (e) { setGreska(e.message) }
  }

  return (
    <>
      {greska && <div className="greska">{greska}</div>}

      {!otvori && (
        <button className="btn sekund mali" onClick={() => setOtvori(true)}>+ Zamjena dijela</button>
      )}
      {otvori && (
        <DodajZamjenu
          voziloId={vozilo.id}
          nalogId={nalogId}
          naGresku={setGreska}
          naSpremljeno={() => { setOtvori(false); ucitaj() }}
          naOdustani={() => setOtvori(false)}
        />
      )}

      {lista === null ? (
        <p className="meta">Učitavam…</p>
      ) : lista.length === 0 ? (
        <p className="meta" style={{ marginTop: 10 }}>Još nema zabilježenih zamjena dijelova.</p>
      ) : (
        <div className="dio-lista">
          {lista.map((z) => (
            <div key={z.id} className="dio-zapis">
              <div className="dio-glava">
                <strong>{z.naziv}</strong>
                <span className="dio-datum">{datum(z.datum)}</span>
              </div>
              {z.razlog && <p className="dio-razlog">{z.razlog}</p>}
              <p className="meta">
                {z.kilometraza != null && <>🧭 {z.kilometraza.toLocaleString('hr-HR')} km · </>}
                {z.promijenio?.ime}
                {(korisnik.uloga === 'voditelj' || z.promijenio?.id === korisnik.id) && (
                  <span className="dio-obrisi" onClick={() => obrisi(z)}> · Obriši</span>
                )}
              </p>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function DodajZamjenu({ voziloId, nalogId, naSpremljeno, naOdustani, naGresku }) {
  const danas = new Date().toISOString().slice(0, 10)
  const [naziv, setNaziv] = useState('')
  const [razlog, setRazlog] = useState('')
  const [datumV, setDatumV] = useState(danas)
  const [km, setKm] = useState('')
  const [radi, setRadi] = useState(false)

  const spremi = async () => {
    if (!naziv.trim()) { naGresku('Upišite naziv dijela.'); return }
    setRadi(true); naGresku('')
    try {
      await api.dodajZamjenuDijela(voziloId, {
        naziv: naziv.trim(),
        razlog: razlog.trim() || null,
        datum: datumV || null,
        kilometraza: km ? Number(km) : null,
        nalog_id: nalogId || null,
      })
      naSpremljeno()
    } catch (e) { naGresku(e.message); setRadi(false) }
  }

  return (
    <div className="karta" style={{ marginTop: 10 }}>
      <label style={{ marginTop: 0 }}>Koji dio je zamijenjen</label>
      <div className="polje-mik">
        <input value={naziv} onChange={(e) => setNaziv(e.target.value)} placeholder="npr. Prednje kočione pločice" />
        <MikrofonGumb naslov="Diktiraj naziv dijela" onTekst={(t) => setNaziv((v) => (v ? v + ' ' : '') + t)} />
      </div>

      <label>Zašto / što se desilo</label>
      <div className="polje-mik">
        <textarea value={razlog} onChange={(e) => setRazlog(e.target.value)} placeholder="npr. istrošene, škripale su pri kočenju" />
        <MikrofonGumb naslov="Diktiraj razlog" onTekst={(t) => setRazlog((v) => (v ? v + ' ' : '') + t)} />
      </div>

      <div className="btn-red" style={{ marginTop: 4 }}>
        <div style={{ flex: 1, minWidth: 140 }}>
          <label style={{ marginTop: 0 }}>Datum</label>
          <input type="date" value={datumV} onChange={(e) => setDatumV(e.target.value)} />
        </div>
        <div style={{ flex: 1, minWidth: 140 }}>
          <label style={{ marginTop: 0 }}>Kilometraža (opcionalno)</label>
          <input type="number" inputMode="numeric" value={km} onChange={(e) => setKm(e.target.value)} placeholder="npr. 250000" />
        </div>
      </div>

      <div className="btn-red">
        <button className="btn mali" onClick={spremi} disabled={radi || !naziv.trim()}>
          {radi ? 'Spremam…' : 'Spremi'}
        </button>
        <button className="btn sekund mali" onClick={naOdustani}>Odustani</button>
      </div>
    </div>
  )
}
