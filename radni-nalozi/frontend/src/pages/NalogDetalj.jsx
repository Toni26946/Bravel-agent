import { lazy, Suspense, useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import PovijestDijelova from '../PovijestDijelova'
import {
  Bedz, KategorijaPicker, MikrofonGumb, STATUS_NALOG, Spinner, datum, datumVrijeme, voziloLabel,
} from '../ui'

const Shema3D = lazy(() => import('../Shema3D'))

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
  const [params] = useSearchParams()
  const spojeno = params.get('spojeno') === '1'
  const { korisnik } = useAuth()
  const [n, setN] = useState(null)
  const [greska, setGreska] = useState('')
  const [radnici, setRadnici] = useState([])
  const [prikaziShemu, setPrikaziShemu] = useState(false)

  const ucitaj = () => api.nalog(id).then(setN).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [id])
  useEffect(() => {
    api.korisnici('radnik').then(setRadnici).catch(() => {})
  }, [])

  if (greska) return <Layout naslov="Nalog" nazad={true}><div className="greska">{greska}</div></Layout>
  if (!n) return <Layout naslov="Nalog" nazad={true}><Spinner /></Layout>

  const ciljevi = ciljeviStatusa(korisnik.uloga, n.status)

  const promijeniStatus = async (status) => {
    setGreska('')
    try { await api.nalogStatus(id, status); ucitaj() } catch (e) { setGreska(e.message) }
  }

  return (
    <Layout naslov={n.broj} nazad={true}>
      {spojeno && (
        <div className="uspjeh">🔗 Novi unos je spojen u ovaj postojeći nalog (kamion je već imao aktivan nalog).</div>
      )}
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

      {/* 3D shema kamiona */}
      <div className="sekcija-naslov">Shema kamiona</div>
      {!prikaziShemu ? (
        <button className="btn sekund" onClick={() => setPrikaziShemu(true)}>🧊 Prikaži 3D shemu</button>
      ) : (
        <Suspense fallback={<div className="karta"><Spinner /></div>}>
          <Shema3D nalog={n} />
        </Suspense>
      )}

      {/* Povijest dijelova na kamionu (ispod sheme) */}
      <div className="sekcija-naslov">Povijest dijelova (kamion {n.vozilo?.gb})</div>
      <PovijestDijelova vozilo={n.vozilo} nalogId={n.id} />

      {/* Povijest statusa */}
      <div className="sekcija-naslov">Povijest statusa</div>
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
      <div className="op-tablica">
        <div className="op-head"><div>Operacija</div><div>Radnik</div></div>
        {nalog.operacije.length === 0 && <div className="op-prazno">Još nema operacija.</div>}
        {nalog.operacije.map((op) => (
          <div key={op.id}>
            <div className="op-kat">
              <span>{op.kategorija}</span>
              <span className="x mini" onClick={() => wrap(api.obrisiOperaciju(nalog.id, op.id))}>×</span>
            </div>
            {op.zadaci.map((z) => (
              <div key={z.id} className="op-red">
                <div className="op-zad">
                  <input
                    type="checkbox"
                    checked={z.gotovo}
                    onChange={() => wrap(api.azurirajZadatak(nalog.id, z.id, { gotovo: !z.gotovo }))}
                  />
                  <span className={z.gotovo ? 'zad-gotov' : ''}>{z.opis}</span>
                  <span className="x mini" onClick={() => wrap(api.obrisiZadatak(nalog.id, z.id))}>×</span>
                </div>
                <div className="op-rad">
                  <select
                    className="rad-select"
                    value={z.zaduzeni?.id || ''}
                    onChange={(e) => wrap(api.azurirajZadatak(nalog.id, z.id, { zaduzeni_id: e.target.value ? Number(e.target.value) : null }))}
                  >
                    <option value="">—</option>
                    {radnici.map((r) => <option key={r.id} value={r.id}>{r.ime}</option>)}
                  </select>
                </div>
              </div>
            ))}
            <div className="op-dodaj">
              <DodajZadatak nalogId={nalog.id} opId={op.id} naGotovo={ucitaj} naGresku={naGresku} />
            </div>
          </div>
        ))}
      </div>

      <div className="karta" style={{ marginTop: 12 }}>
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
    <div className="btn-red" style={{ marginTop: 10, alignItems: 'stretch' }}>
      <input value={opis} onChange={(e) => setOpis(e.target.value)} placeholder="Novi zadatak"
        onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), spremi())} />
      <MikrofonGumb naslov="Diktiraj zadatak" onTekst={(t) => setOpis((v) => (v ? v + ' ' : '') + t)} />
      <button className="btn sekund mali" onClick={spremi} disabled={!opis.trim()}>+ Zadatak</button>
    </div>
  )
}
