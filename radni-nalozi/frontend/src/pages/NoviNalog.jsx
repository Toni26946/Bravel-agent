import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { KategorijaPicker, voziloLabel } from '../ui'

export default function NoviNalog() {
  const nav = useNavigate()
  const { korisnik } = useAuth()
  const [params] = useSearchParams()
  const prijavaId = params.get('prijava')

  const [vozila, setVozila] = useState([])
  const [voditelji, setVoditelji] = useState([])
  const [vozaci, setVozaci] = useState([])

  // korak 1 — kamion po GB
  const [gb, setGb] = useState('')
  const [vozilo, setVozilo] = useState(null)
  const [gbGreska, setGbGreska] = useState('')

  // korak 2 — osobe
  const [voditeljId, setVoditeljId] = useState('')
  const [vozacId, setVozacId] = useState('')

  // korak 3 — operacije
  const [operacije, setOperacije] = useState([]) // [{kategorija, zadaci:[str]}]

  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)

  useEffect(() => {
    Promise.all([api.vozila(), api.korisnici('voditelj'), api.korisnici('vozac')])
      .then(([v, vd, vz]) => {
        setVozila(v); setVoditelji(vd); setVozaci(vz)
        if (korisnik.uloga === 'voditelj') setVoditeljId(String(korisnik.id))
      })
      .catch((e) => setGreska(e.message))
  }, [])

  // Predpopuni GB iz prijave kvara
  useEffect(() => {
    if (!prijavaId || vozila.length === 0) return
    api.prijava(prijavaId).then((p) => {
      const v = vozila.find((x) => x.id === p.vozilo_id)
      if (v) { setVozilo(v); setGb(v.gb) }
    }).catch(() => {})
  }, [prijavaId, vozila])

  const pronadji = () => {
    setGbGreska('')
    const trazeni = gb.trim().toLowerCase()
    if (!trazeni) return
    const v = vozila.find((x) => x.gb.toLowerCase() === trazeni)
    if (!v) { setVozilo(null); setGbGreska('Kamion s tim GB ne postoji. Dodaj ga u Šifrarniku.'); return }
    setVozilo(v)
  }

  const dodajOperaciju = (kategorija) => {
    const k = (kategorija || '').trim()
    if (!k) return
    setOperacije((o) => [...o, { kategorija: k, zadaci: [''] }])
  }
  const makniOperaciju = (i) => setOperacije((o) => o.filter((_, idx) => idx !== i))
  const promijeniZadatak = (oi, zi, val) =>
    setOperacije((o) => o.map((op, idx) => idx !== oi ? op : { ...op, zadaci: op.zadaci.map((z, j) => j === zi ? val : z) }))
  const dodajZadatak = (oi) =>
    setOperacije((o) => o.map((op, idx) => idx !== oi ? op : { ...op, zadaci: [...op.zadaci, ''] }))
  const makniZadatak = (oi, zi) =>
    setOperacije((o) => o.map((op, idx) => idx !== oi ? op : { ...op, zadaci: op.zadaci.filter((_, j) => j !== zi) }))

  const spremi = async () => {
    setGreska('')
    if (!vozilo) { setGreska('Prvo pronađi kamion po garažnom broju.'); return }
    if (!voditeljId) { setGreska('Odaberi voditelja.'); return }
    setRadi(true)
    try {
      const cisteOperacije = operacije
        .map((op) => ({ kategorija: op.kategorija, zadaci: op.zadaci.map((z) => z.trim()).filter(Boolean) }))
        .filter((op) => op.kategorija)
      const n = await api.kreirajNalog({
        vozilo_id: vozilo.id,
        voditelj_id: Number(voditeljId),
        vozac_id: vozacId ? Number(vozacId) : null,
        prijava_id: prijavaId ? Number(prijavaId) : null,
        operacije: cisteOperacije,
      })
      nav(`/nalozi/${n.id}`, { replace: true })
    } catch (err) {
      setGreska(err.message); setRadi(false)
    }
  }

  return (
    <Layout naslov="Novi radni nalog" nazad={true}>
      {greska && <div className="greska">{greska}</div>}

      {/* Korak 1 — kamion */}
      <div className="sekcija-naslov">1. Kamion (garažni broj)</div>
      {!vozilo ? (
        <div className="karta">
          <div className="btn-red" style={{ marginTop: 0 }}>
            <input
              value={gb}
              onChange={(e) => setGb(e.target.value)}
              placeholder="npr. GB-500"
              onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), pronadji())}
              autoCapitalize="characters"
            />
            <button type="button" className="btn mali" onClick={pronadji} style={{ minWidth: 100 }}>Pronađi</button>
          </div>
          {gbGreska && <p className="meta" style={{ color: 'var(--crvena)', marginTop: 8 }}>{gbGreska}</p>}
        </div>
      ) : (
        <div className="karta">
          <div className="naslov-red">
            <div>
              <h3 style={{ margin: 0 }}>🚚 {vozilo.gb}</h3>
              <p className="meta" style={{ margin: '4px 0 0' }}>
                {[vozilo.marka, vozilo.model, vozilo.registracija].filter(Boolean).join(' · ') || '—'}
              </p>
            </div>
            <button type="button" className="btn sekund mali" onClick={() => { setVozilo(null); setGb('') }}>Promijeni</button>
          </div>
        </div>
      )}

      {/* Korak 2 — osobe (tek kad je kamion nađen) */}
      {vozilo && (
        <>
          <div className="sekcija-naslov">2. Voditelj i vozač</div>
          <div className="karta">
            <label style={{ marginTop: 0 }}>Voditelj</label>
            <select value={voditeljId} onChange={(e) => setVoditeljId(e.target.value)}>
              <option value="">— odaberi —</option>
              {voditelji.map((v) => <option key={v.id} value={v.id}>{v.ime}</option>)}
            </select>
            <label>Vozač (opcionalno)</label>
            <select value={vozacId} onChange={(e) => setVozacId(e.target.value)}>
              <option value="">— bez vozača —</option>
              {vozaci.map((v) => <option key={v.id} value={v.id}>{v.ime}</option>)}
            </select>
          </div>
        </>
      )}

      {/* Korak 3 — operacije (tek kad je kamion nađen) */}
      {vozilo && (
        <>
          <div className="sekcija-naslov">3. Operacije i zadaci</div>

          {operacije.map((op, oi) => (
            <div key={oi} className="karta">
              <div className="naslov-red">
                <h3 style={{ margin: 0 }}>{op.kategorija}</h3>
                <span className="x" onClick={() => makniOperaciju(oi)}>×</span>
              </div>
              {op.zadaci.map((z, zi) => (
                <div key={zi} className="btn-red" style={{ marginTop: 8 }}>
                  <input value={z} onChange={(e) => promijeniZadatak(oi, zi, e.target.value)} placeholder={`Zadatak ${zi + 1}`} />
                  {op.zadaci.length > 1 && <span className="x" onClick={() => makniZadatak(oi, zi)}>×</span>}
                </div>
              ))}
              <button type="button" className="btn sekund mali" style={{ marginTop: 8 }} onClick={() => dodajZadatak(oi)}>+ Zadatak</button>
            </div>
          ))}

          <div className="karta">
            <label style={{ marginTop: 0 }}>Dodaj operaciju (kategoriju)</label>
            <KategorijaPicker onOdaberi={dodajOperaciju} />
          </div>

          <button className="btn" onClick={spremi} disabled={radi} style={{ marginTop: 8 }}>
            {radi ? 'Kreiram…' : 'Kreiraj nalog'}
          </button>
        </>
      )}
    </Layout>
  )
}
