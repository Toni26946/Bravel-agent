import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import {
  Bedz, KategorijaPicker, STATUS_NALOG, Spinner, datum, datumVrijeme, voziloLabel,
} from '../ui'

// Dozvoljeni sljedeći statusi po ulozi i trenutnom statusu.
function ciljeviStatusa(uloga, status) {
  const radnik = {
    otvoren: ['u_radu', 'ceka_dijelove'],
    u_radu: ['ceka_dijelove', 'gotov'],
    ceka_dijelove: ['u_radu', 'gotov'],
    gotov: ['u_radu'],
    zatvoren: [],
  }
  const voditelj = {
    otvoren: ['u_radu', 'ceka_dijelove', 'zatvoren'],
    u_radu: ['ceka_dijelove', 'gotov', 'zatvoren'],
    ceka_dijelove: ['u_radu', 'gotov', 'zatvoren'],
    gotov: ['zatvoren', 'u_radu'],
    zatvoren: ['u_radu'],
  }
  return (uloga === 'voditelj' ? voditelj : radnik)[status] || []
}

export default function NalogDetalj() {
  const { id } = useParams()
  const { korisnik } = useAuth()
  const [n, setN] = useState(null)
  const [greska, setGreska] = useState('')
  const [radnici, setRadnici] = useState([])
  const [urediDodjele, setUrediDodjele] = useState(false)

  const ucitaj = () => api.nalog(id).then(setN).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [id])
  useEffect(() => {
    api.korisnici('radnik').then(setRadnici).catch(() => {})
  }, [])

  if (greska) return <Layout naslov="Nalog" nazad={true}><div className="greska">{greska}</div></Layout>
  if (!n) return <Layout naslov="Nalog" nazad={true}><Spinner /></Layout>

  const jeVoditelj = korisnik.uloga === 'voditelj'
  const ciljevi = ciljeviStatusa(korisnik.uloga, n.status)

  const promijeniStatus = async (status) => {
    setGreska('')
    try { await api.nalogStatus(id, status); ucitaj() } catch (e) { setGreska(e.message) }
  }

  const ukupnoSati = n.radni_sati.reduce((s, r) => s + r.sati, 0)

  return (
    <Layout naslov={n.broj} nazad={true}>
      <div className="karta">
        <div className="naslov-red">
          <h3>{n.naslov}</h3>
          <Bedz vrsta={n.status} tekst={STATUS_NALOG[n.status]} />
        </div>
        <p className="meta">🚚 {voziloLabel(n.vozilo)}</p>
        {n.voditelj && <p className="meta">🧑‍🔧 Voditelj: <strong>{n.voditelj.ime}</strong></p>}
        {n.vozac && <p className="meta">🚛 Vozač: <strong>{n.vozac.ime}</strong></p>}
        {n.rok && <p className="meta">📅 Rok: <strong>{datum(n.rok)}</strong></p>}
        {n.opis && <p style={{ margin: '12px 0', whiteSpace: 'pre-wrap' }}>{n.opis}</p>}
        <p className="meta">Kreirao: <strong>{n.kreirao?.ime}</strong> · {datumVrijeme(n.kreiran)}</p>
      </div>

      {/* Promjena statusa */}
      {ciljevi.length > 0 && (
        <>
          <div className="sekcija-naslov">Promijeni status</div>
          <div className="btn-red">
            {ciljevi.map((c) => (
              <button key={c} className="btn sekund mali" onClick={() => promijeniStatus(c)}>
                {STATUS_NALOG[c]}
              </button>
            ))}
          </div>
        </>
      )}

      {/* Operacije i zadaci */}
      <div className="sekcija-naslov">Operacije i zadaci</div>
      <Operacije nalog={n} radnici={radnici} ucitaj={ucitaj} naGresku={setGreska} />

      {/* Dodijeljeni radnici */}
      <div className="sekcija-naslov">Dodijeljeni radnici</div>
      <div className="karta">
        {n.dodijeljeni.length === 0 ? (
          <p className="meta" style={{ margin: 0 }}>Nitko još nije dodijeljen.</p>
        ) : (
          <p style={{ margin: 0 }}>{n.dodijeljeni.map((r) => r.ime).join(', ')}</p>
        )}
        {jeVoditelj && (
          <>
            <button className="btn sekund mali" style={{ marginTop: 12 }} onClick={() => setUrediDodjele((v) => !v)}>
              {urediDodjele ? 'Zatvori' : 'Uredi dodjele'}
            </button>
            {urediDodjele && (
              <DodjeleUreditelj
                nalogId={id}
                radnici={radnici}
                pocetni={n.dodijeljeni.map((r) => r.id)}
                naGotovo={() => { setUrediDodjele(false); ucitaj() }}
                naGresku={setGreska}
              />
            )}
          </>
        )}
      </div>

      {/* Radni sati */}
      <div className="sekcija-naslov">Radni sati {ukupnoSati > 0 && `· ukupno ${ukupnoSati.toFixed(1)} h`}</div>
      <div className="karta">
        {n.radni_sati.length === 0 && <p className="meta" style={{ margin: 0 }}>Nema upisanih sati.</p>}
        {n.radni_sati.map((r) => (
          <div key={r.id} className="stavka">
            <div>
              <strong>{r.sati} h</strong> · {r.radnik?.ime}
              <div className="meta">{r.opis || '—'} · {datum(r.datum)}</div>
            </div>
            {(jeVoditelj || r.radnik?.id === korisnik.id) && (
              <span className="x" onClick={async () => { await api.obrisiSat(id, r.id); ucitaj() }}>×</span>
            )}
          </div>
        ))}
        <DodajSate nalogId={id} naGotovo={ucitaj} naGresku={setGreska} />
      </div>

      {/* Dijelovi */}
      <div className="sekcija-naslov">Ugrađeni dijelovi</div>
      <div className="karta">
        {n.dijelovi.length === 0 && <p className="meta" style={{ margin: 0 }}>Nema upisanih dijelova.</p>}
        {n.dijelovi.map((d) => (
          <div key={d.id} className="stavka">
            <div>
              <strong>{d.naziv}</strong>
              <div className="meta">{d.kolicina} {d.jedinica}{d.cijena != null ? ` · ${d.cijena} €` : ''}</div>
            </div>
            <span className="x" onClick={async () => { await api.obrisiDio(id, d.id); ucitaj() }}>×</span>
          </div>
        ))}
        <DodajDio nalogId={id} naGotovo={ucitaj} naGresku={setGreska} />
      </div>

      {/* Povijest */}
      <div className="sekcija-naslov">Povijest</div>
      <div className="karta">
        {n.povijest.map((p) => (
          <div key={p.id} className="stavka">
            <div>
              <strong>{p.stari_status ? `${STATUS_NALOG[p.stari_status] || p.stari_status} → ` : ''}{STATUS_NALOG[p.novi_status] || p.novi_status}</strong>
              <div className="meta">{p.promijenio?.ime}{p.napomena ? ` · ${p.napomena}` : ''}</div>
            </div>
            <span className="meta">{datumVrijeme(p.kreiran)}</span>
          </div>
        ))}
      </div>
    </Layout>
  )
}

// --- pod-komponente ----------------------------------------------------------
function DodjeleUreditelj({ nalogId, radnici, pocetni, naGotovo, naGresku }) {
  const [odabrani, setOdabrani] = useState(pocetni)
  const [radi, setRadi] = useState(false)
  const toggle = (id) => setOdabrani((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id]))
  const spremi = async () => {
    setRadi(true)
    try { await api.dodjele(nalogId, odabrani); naGotovo() }
    catch (e) { naGresku(e.message); setRadi(false) }
  }
  return (
    <div style={{ marginTop: 12 }}>
      {radnici.length === 0 && <p className="meta">Nema radnika.</p>}
      <div className="multi">
        {radnici.map((r) => (
          <span key={r.id} className={`opt ${odabrani.includes(r.id) ? 'akt' : ''}`} onClick={() => toggle(r.id)}>{r.ime}</span>
        ))}
      </div>
      <button className="btn mali" style={{ marginTop: 12 }} onClick={spremi} disabled={radi}>Spremi dodjele</button>
    </div>
  )
}

function DodajSate({ nalogId, naGotovo, naGresku }) {
  const [otvori, setOtvori] = useState(false)
  const [sati, setSati] = useState('')
  const [opis, setOpis] = useState('')
  if (!otvori) return <button className="btn sekund mali" style={{ marginTop: 12 }} onClick={() => setOtvori(true)}>+ Dodaj sate</button>
  const spremi = async () => {
    try {
      await api.dodajSate(nalogId, { sati: Number(sati), opis: opis || null })
      setSati(''); setOpis(''); setOtvori(false); naGotovo()
    } catch (e) { naGresku(e.message) }
  }
  return (
    <div style={{ marginTop: 12 }}>
      <input type="number" step="0.5" min="0" placeholder="Sati (npr. 2.5)" value={sati} onChange={(e) => setSati(e.target.value)} />
      <input placeholder="Opis rada (opcionalno)" value={opis} onChange={(e) => setOpis(e.target.value)} style={{ marginTop: 8 }} />
      <div className="btn-red">
        <button className="btn mali" onClick={spremi} disabled={!sati}>Spremi</button>
        <button className="btn sekund mali" onClick={() => setOtvori(false)}>Odustani</button>
      </div>
    </div>
  )
}

function DodajDio({ nalogId, naGotovo, naGresku }) {
  const [otvori, setOtvori] = useState(false)
  const [naziv, setNaziv] = useState('')
  const [kolicina, setKolicina] = useState('1')
  const [jedinica, setJedinica] = useState('kom')
  const [cijena, setCijena] = useState('')
  if (!otvori) return <button className="btn sekund mali" style={{ marginTop: 12 }} onClick={() => setOtvori(true)}>+ Dodaj dio</button>
  const spremi = async () => {
    try {
      await api.dodajDio(nalogId, {
        naziv, kolicina: Number(kolicina) || 1, jedinica: jedinica || 'kom',
        cijena: cijena === '' ? null : Number(cijena),
      })
      setNaziv(''); setKolicina('1'); setCijena(''); setOtvori(false); naGotovo()
    } catch (e) { naGresku(e.message) }
  }
  return (
    <div style={{ marginTop: 12 }}>
      <input placeholder="Naziv dijela" value={naziv} onChange={(e) => setNaziv(e.target.value)} />
      <div className="btn-red" style={{ marginTop: 8 }}>
        <input type="number" step="0.5" placeholder="Kol." value={kolicina} onChange={(e) => setKolicina(e.target.value)} />
        <input placeholder="Jed." value={jedinica} onChange={(e) => setJedinica(e.target.value)} />
        <input type="number" step="0.01" placeholder="Cijena €" value={cijena} onChange={(e) => setCijena(e.target.value)} />
      </div>
      <div className="btn-red">
        <button className="btn mali" onClick={spremi} disabled={!naziv}>Spremi</button>
        <button className="btn sekund mali" onClick={() => setOtvori(false)}>Odustani</button>
      </div>
    </div>
  )
}

// --- Operacije i zadaci ------------------------------------------------------
function Operacije({ nalog, radnici, ucitaj, naGresku }) {
  const wrap = (p) => p.then(ucitaj).catch((e) => naGresku(e.message))
  const dodajOp = (kat) => {
    const k = (kat || '').trim()
    if (!k) return
    wrap(api.dodajOperaciju(nalog.id, k))
  }

  return (
    <>
      {nalog.operacije.length === 0 && (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>Još nema operacija.</p></div>
      )}

      {nalog.operacije.map((op) => {
        const gotovih = op.zadaci.filter((z) => z.gotovo).length
        return (
          <div key={op.id} className="karta">
            <div className="naslov-red">
              <h3 style={{ margin: 0 }}>
                {op.kategorija}
                {op.zadaci.length > 0 && <span className="meta" style={{ fontWeight: 400 }}> &nbsp;{gotovih}/{op.zadaci.length}</span>}
              </h3>
              <span className="x" onClick={() => wrap(api.obrisiOperaciju(nalog.id, op.id))}>×</span>
            </div>

            {op.zadaci.map((z) => (
              <div key={z.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--rub)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 10, margin: 0, cursor: 'pointer', flex: 1 }}>
                    <input
                      type="checkbox"
                      checked={z.gotovo}
                      onChange={() => wrap(api.azurirajZadatak(nalog.id, z.id, { gotovo: !z.gotovo }))}
                      style={{ width: 22, height: 22, flex: 'none' }}
                    />
                    <span style={{ textDecoration: z.gotovo ? 'line-through' : 'none', color: z.gotovo ? 'var(--sivo)' : 'inherit' }}>
                      {z.opis}
                    </span>
                  </label>
                  <span className="x" onClick={() => wrap(api.obrisiZadatak(nalog.id, z.id))}>×</span>
                </div>
                <select
                  value={z.zaduzeni?.id || ''}
                  onChange={(e) => wrap(api.azurirajZadatak(nalog.id, z.id, { zaduzeni_id: e.target.value ? Number(e.target.value) : null }))}
                  style={{ marginTop: 8, padding: '8px 10px', fontSize: 14 }}
                >
                  <option value="">👷 Nezaduženo</option>
                  {radnici.map((r) => <option key={r.id} value={r.id}>{r.ime}</option>)}
                </select>
              </div>
            ))}

            <DodajZadatak nalogId={nalog.id} opId={op.id} naGotovo={ucitaj} naGresku={naGresku} />
          </div>
        )
      })}

      <div className="karta">
        <label style={{ marginTop: 0 }}>Dodaj operaciju</label>
        <KategorijaPicker onOdaberi={dodajOp} />
      </div>
    </>
  )
}

function DodajZadatak({ nalogId, opId, naGotovo, naGresku }) {
  const [opis, setOpis] = useState('')
  const spremi = async () => {
    if (!opis.trim()) return
    try { await api.dodajZadatak(nalogId, opId, opis.trim()); setOpis(''); naGotovo() }
    catch (e) { naGresku(e.message) }
  }
  return (
    <div className="btn-red" style={{ marginTop: 10 }}>
      <input value={opis} onChange={(e) => setOpis(e.target.value)} placeholder="Novi zadatak"
        onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), spremi())} />
      <button className="btn sekund mali" onClick={spremi} disabled={!opis.trim()}>+ Zadatak</button>
    </div>
  )
}
