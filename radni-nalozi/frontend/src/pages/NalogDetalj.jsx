import { Fragment, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import {
  Bedz, KategorijaPicker, MikrofonGumb, Spinner, datum, datumVrijeme, useAutoOsvjezi, voziloLabel,
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
  const jeUrednik = uloga === 'voditelj' || uloga === 'poslovodja'
  return (jeUrednik ? voditelj : radnik)[status] || []
}

export default function NalogDetalj() {
  const { id } = useParams()
  const nav = useNavigate()
  const [params] = useSearchParams()
  const spojeno = params.get('spojeno') === '1'
  const { korisnik } = useAuth()
  const { t } = useT()
  const [n, setN] = useState(null)
  const [greska, setGreska] = useState('')
  const [radnici, setRadnici] = useState([])
  const [uredi, setUredi] = useState(false)
  const [forma, setForma] = useState({ naslov: '', opis: '' })

  const ucitaj = () => api.nalog(id).then(setN).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [id])
  // Tiho osvježavanje (bez spinnera/greške) svakih 20 s i na povratak u aplikaciju.
  useAutoOsvjezi(() => api.nalog(id).then(setN).catch(() => {}))
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

  const jeUrednik = korisnik.uloga === 'voditelj' || korisnik.uloga === 'poslovodja'
  const zapocniUredi = () => { setForma({ naslov: n.naslov || '', opis: n.opis || '' }); setUredi(true) }
  const spremiUredi = async () => {
    setGreska('')
    try { await api.azurirajNalog(id, { naslov: forma.naslov, opis: forma.opis }); setUredi(false); ucitaj() }
    catch (e) { setGreska(e.message) }
  }

  return (
    <Layout naslov={n.broj} nazad={true}>
      {spojeno && (
        <div className="uspjeh">{t('nalog.spojeno')}</div>
      )}
      {n.vozilo?.gb && <ServisBanner gb={n.vozilo.gb} />}
      <div className="karta">
        <div className="naslov-red">
          {uredi
            ? <input className="pretraga-input" style={{ marginRight: 8 }} value={forma.naslov}
                onChange={(e) => setForma({ ...forma, naslov: e.target.value })} placeholder={t('nalog.naslovPh')} />
            : <h3>{n.naslov}</h3>}
          <Bedz vrsta={n.status} tekst={t('status.' + n.status)} />
        </div>
        <p className="meta">
          {n.vozilo?.id ? (
            <button type="button" className="veza-vozilo" onClick={() => nav(`/vozila/${n.vozilo.id}`)}
              title={t('nalog.povijestVozila')}>
              🚚 {voziloLabel(n.vozilo)} <span className="veza-vozilo-ik">📖</span>
            </button>
          ) : <>🚚 {voziloLabel(n.vozilo)}</>}
        </p>
        {n.voditelj && <p className="meta">🧑‍🔧 {t('nalog.voditelj')}: <strong>{n.voditelj.ime}</strong></p>}
        {n.vozac && <p className="meta">🚛 {t('nalog.vozac')}: <strong>{n.vozac.ime}</strong></p>}
        {n.rok && <p className="meta">📅 {t('nalog.rok')}: <strong>{datum(n.rok)}</strong></p>}
        {uredi
          ? <textarea className="uredi-opis" value={forma.opis} rows={4}
              onChange={(e) => setForma({ ...forma, opis: e.target.value })} placeholder={t('nalog.opisPh')} />
          : (n.opis && <p style={{ margin: '12px 0', whiteSpace: 'pre-wrap' }}>{n.opis}</p>)}
        <p className="meta">{t('nalog.kreirao')}: <strong>{n.kreirao?.ime}</strong> · {datumVrijeme(n.kreiran)}</p>
        <div className="btn-red no-print" style={{ marginTop: 10 }}>
          {uredi ? (
            <>
              <button className="btn mali" onClick={spremiUredi}>{t('common.spremi')}</button>
              <button className="btn sekund mali" onClick={() => setUredi(false)}>{t('common.odustani')}</button>
            </>
          ) : (
            <>
              {jeUrednik && <button className="btn sekund mali" onClick={zapocniUredi}>✏️ {t('nalog.uredi')}</button>}
              {n.vozilo?.id && (
                <button className="btn sekund mali" onClick={() => nav(`/vozila/${n.vozilo.id}`)}>📖 {t('nalog.povijestVozila')}</button>
              )}
              <button className="btn sekund mali" onClick={() => window.print()}>🖨️ {t('nalog.ispisi')}</button>
            </>
          )}
        </div>
      </div>

      {/* Promjena statusa */}
      {ciljevi.length > 0 && (
        <>
          <div className="sekcija-naslov">{t('nalog.promijeniStatus')}</div>
          <div className="btn-red">
            {ciljevi.map((c) => (
              <button key={c} className="btn sekund mali" onClick={() => promijeniStatus(c)}>
                {t('status.' + c)}
              </button>
            ))}
          </div>
        </>
      )}

      {/* Operacije i zadaci */}
      <div className="sekcija-naslov">{t('nalog.operacijeIZadaci')}</div>
      <Operacije nalog={n} radnici={radnici} ucitaj={ucitaj} naGresku={setGreska} jeVoditelj={korisnik.uloga === 'voditelj' || korisnik.uloga === 'poslovodja'} />

      {/* Ispis naloga (vidljivo samo pri printanju) */}
      <NalogPrint n={n} />
    </Layout>
  )
}

// --- Servisni banner u nalogu ------------------------------------------------
// Uvijek pokaže koliko još km do servisa; ako je dospjelo/uskoro — bode u oči.
function kmFmt(x) { try { return Math.round(x).toLocaleString('hr-HR') } catch (_) { return x } }

function ServisBanner({ gb }) {
  const { t } = useT()
  const [s, setS] = useState(null)
  useEffect(() => { api.servisVozila(gb).then(setS).catch(() => setS(null)) }, [gb])
  if (!s) return null

  const imaKm = s.km_preostalo !== null && s.km_preostalo !== undefined
  const imaVrijeme = s.preostalo_dana !== null && s.preostalo_dana !== undefined
  if (!imaKm && !imaVrijeme) return null

  // Dijelovi teksta za km i vrijeme.
  const kmTxt = !imaKm ? null
    : s.km_preostalo <= 0
      ? `🛣️ ${t('servisi.prekoraceno')} ${kmFmt(-s.km_preostalo)} km`
      : `🛣️ ${t('nalog.jos')} ${kmFmt(s.km_preostalo)} km ${t('nalog.doServisa')}`
  const vrTxt = !imaVrijeme ? null
    : s.preostalo_dana <= 0
      ? `🗓️ ${t('servisi.proslo')} ${Math.abs(s.preostalo_dana)} ${t('servisi.dana')}`
      : `🗓️ ${t('nalog.jos')} ${s.preostalo_dana} ${t('servisi.dana')}${s.iduci_datum ? ` (${datum(s.iduci_datum)})` : ''}`
  const detalji = [kmTxt, vrTxt].filter(Boolean).join('  ·  ')

  if (s.status === 'dospjelo') {
    return (
      <div className="servis-banner dospjelo">
        <div className="sb-naslov">⚠️ {t('nalog.servisDospio')}</div>
        <div className="sb-det">{detalji}</div>
      </div>
    )
  }
  if (s.status === 'uskoro') {
    return (
      <div className="servis-banner uskoro">
        <div className="sb-naslov">🟡 {t('nalog.servisUskoro')}</div>
        <div className="sb-det">{detalji}</div>
      </div>
    )
  }
  // OK / poznato: nenametljiva linija sa km do servisa.
  return (
    <div className="servis-banner ok">
      <span className="sb-naslov">🛢️ {t('nalog.servis')}:</span> {detalji}
    </div>
  )
}

// --- Ispis radnog naloga -----------------------------------------------------
function NalogPrint({ n }) {
  const v = n.vozilo || {}
  return (
    <div className="nalog-print">
      <div className="np-head">
        <div className="np-tvrtka">
          <img className="np-logo-img" src="/bravel-logo.png" alt="Bravel d.o.o." />
          <div className="np-adresa">Bravel d.o.o. · Zagrebačka 146, 10340 Vrbovec</div>
        </div>
        <div className="np-kontakt">
          <div>Fakturiranje: +385 1 6539 991</div>
          <div>Računovodstvo: +385 1 6539 914</div>
          <div>fax: +385 1 2790 563</div>
          <div>e-mail: bravel@bravel.hr</div>
        </div>
      </div>

      <h2 className="np-naslov">Radni nalog: {n.broj}</h2>

      <div className="np-info">
        <div><span>Datum:</span> {datum(n.kreiran)}</div>
        <div><span>Garažni broj:</span> {v.gb || '—'}</div>
        <div><span>Registarska oznaka:</span> {v.registracija || '—'}</div>
        <div><span>Vozilo:</span> {[v.marka, v.model].filter(Boolean).join(' ') || '—'}</div>
        {n.voditelj && <div><span>Voditelj:</span> {n.voditelj.ime}</div>}
        {n.vozac && <div><span>Vozač:</span> {n.vozac.ime}</div>}
        {n.rok && <div><span>Predviđeni datum isporuke:</span> {datum(n.rok)}</div>}
      </div>

      {n.opis && (
        <div className="np-napomena"><span>Napomena:</span> {n.opis}</div>
      )}

      <div className="np-sekcija">Operacije</div>
      <table className="np-tablica">
        <thead>
          <tr><th className="np-rbr">#</th><th>Naziv</th><th>Opis</th></tr>
        </thead>
        <tbody>
          {n.operacije.length === 0 && (
            <tr><td colSpan={3} className="np-prazno">Nema operacija.</td></tr>
          )}
          {n.operacije.map((op, i) => {
            const opis = op.zadaci.map((z) => z.opis).filter(Boolean).join(' • ')
            return (
              <tr key={op.id}>
                <td className="np-rbr">{i + 1}</td>
                <td className="np-naziv">{op.kategorija}</td>
                <td>{opis || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <div className="np-potpisi">
        <div><div className="np-linija" />Vozilo predao</div>
        <div><div className="np-linija" />Vozilo preuzeo</div>
      </div>
    </div>
  )
}

// Pretvori vremensku oznaku u ms; ako nema zone, tretiraj kao UTC.
function msVremena(s) {
  if (!s) return 0
  const imaZonu = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(imaZonu ? s : s + 'Z').getTime()
}

// Formatiraj sekunde u čitljivo trajanje (h:mm:ss ili m:ss).
function trajanje(sek) {
  const s = Math.max(0, Math.floor(sek))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const pad = (x) => String(x).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(ss)}` : `${m}:${pad(ss)}`
}

// --- Operacije i zadaci ------------------------------------------------------
function Operacije({ nalog, radnici, ucitaj, naGresku, jeVoditelj }) {
  const { t } = useT()
  const [sada, setSada] = useState(Date.now())
  // Otkucaj svake sekunde da se živo mjerenje osvježava.
  useEffect(() => {
    const id = setInterval(() => setSada(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const wrap = (p) => p.then(ucitaj).catch((e) => naGresku(e.message))
  const dodajOp = (kat) => {
    const k = (kat || '').trim()
    if (!k) return
    wrap(api.dodajOperaciju(nalog.id, k))
  }

  return (
    <>
      <div className="op-tablica">
        <div className="op-head"><div>{t('op.operacija')}</div><div>{t('op.radnik')}</div></div>
        {nalog.operacije.length === 0 && <div className="op-prazno">{t('op.nemaOperacija')}</div>}
        {nalog.operacije.map((op) => (
          <OperacijaBlok key={op.id} nalog={nalog} op={op} radnici={radnici} wrap={wrap} ucitaj={ucitaj} naGresku={naGresku} sada={sada} jeVoditelj={jeVoditelj} />
        ))}
      </div>

      {jeVoditelj && (
        <div className="karta" style={{ marginTop: 12 }}>
          <label style={{ marginTop: 0 }}>{t('op.dodajOperaciju')}</label>
          <KategorijaPicker onOdaberi={dodajOp} />
        </div>
      )}
    </>
  )
}

// Tekst koji voditelj/poslovođa može urediti u mjestu (✏️ → input → ✓/✕).
function TekstUredivi({ vrijednost, editable, prikazKlasa, onSpremi }) {
  const [otvoren, setOtvoren] = useState(false)
  const [val, setVal] = useState(vrijednost)
  const spremi = () => {
    const v = (val || '').trim()
    if (v && v !== vrijednost) onSpremi(v)
    setOtvoren(false)
  }
  if (otvoren) {
    return (
      <span className="tu-uredi">
        <input
          className="tu-input"
          value={val}
          autoFocus
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') spremi(); if (e.key === 'Escape') setOtvoren(false) }}
        />
        <span className="tu-ik ok" onClick={spremi}>✓</span>
        <span className="tu-ik" onClick={() => { setVal(vrijednost); setOtvoren(false) }}>✕</span>
      </span>
    )
  }
  return (
    <>
      <span className={prikazKlasa}>{vrijednost}</span>
      {editable && <span className="tu-ol" onClick={(e) => { e.preventDefault(); setVal(vrijednost); setOtvoren(true) }}>✏️</span>}
    </>
  )
}

function OperacijaBlok({ nalog, op, radnici, wrap, ucitaj, naGresku, sada, jeVoditelj }) {
  const { t } = useT()
  const [dodaje, setDodaje] = useState(false)
  return (
    <div className="op2">
      <div className="op2-kat">
        <TekstUredivi
          vrijednost={op.kategorija}
          editable={jeVoditelj}
          prikazKlasa="op2-ime"
          onSpremi={(v) => wrap(api.azurirajOperaciju(nalog.id, op.id, { kategorija: v }))}
        />
        {jeVoditelj && <span className="op2-plus" onClick={() => setDodaje((v) => !v)}>＋</span>}
        {jeVoditelj && <span className="x" onClick={() => wrap(api.obrisiOperaciju(nalog.id, op.id))}>×</span>}
      </div>
      <div className="op2-kat-r" />
      {op.zadaci.map((z) => {
        const radi = !!z.zapoceto
        const osnova = z.utroseno_sek || 0
        // Živi prikaz = vrijeme od zadnje prijave (trenutna sesija), ne ukupno.
        const proteklo = radi ? Math.max(0, (sada - msVremena(z.zapoceto)) / 1000) : osnova
        return (
          <Fragment key={z.id}>
            <label className="op2-zad">
              <input
                type="checkbox"
                checked={z.gotovo}
                onChange={() => wrap(api.azurirajZadatak(nalog.id, z.id, { gotovo: !z.gotovo }))}
              />
              <span className={z.gotovo ? 'zad-gotov' : ''}>{z.opis}</span>
              {jeVoditelj && <span className="x" onClick={() => wrap(api.obrisiZadatak(nalog.id, z.id))}>×</span>}
            </label>
            <div className="op2-rad">
              <RadniciZadatka nalog={nalog} z={z} radnici={radnici} jeVoditelj={jeVoditelj} wrap={wrap} />
            </div>
            <div className="op2-mj">
              {/* Vrijeme teče automatski dok je radnik prijavljen — bez ručnih gumba. */}
              {!z.gotovo && radi && (
                <span className="mj-vrijeme-ro radi">⏱ {trajanje(proteklo)}</span>
              )}
              {!z.gotovo && !radi && osnova > 0 && (
                <span className="mj-vrijeme-ro">⏸ {trajanje(osnova)}</span>
              )}
              {z.gotovo && (
                <span className="mj-gotovo">
                  ✓ {t('op.zavrsenoU')} {datumVrijeme(z.zavrseno)}
                  {osnova > 0 && <> · ⏱ {trajanje(osnova)}</>}
                </span>
              )}
            </div>
          </Fragment>
        )
      })}
      {dodaje && (
        <div className="op2-dodaj">
          <DodajZadatak nalogId={nalog.id} opId={op.id} naGotovo={() => { setDodaje(false); ucitaj() }} naGresku={naGresku} />
        </div>
      )}
    </div>
  )
}

// Popis radnika na zadatku (može ih biti više). Voditelj dodaje/uklanja.
function RadniciZadatka({ nalog, z, radnici, jeVoditelj, wrap }) {
  const { t } = useT()
  const dodijeljeni = z.radnici && z.radnici.length ? z.radnici : (z.zaduzeni ? [z.zaduzeni] : [])
  const ids = dodijeljeni.map((r) => r.id)
  const postavi = (novi) => wrap(api.azurirajZadatak(nalog.id, z.id, { radnici_ids: novi }))
  // Ne nudi radnike koji se ne prijavljuju (npr. skladištar); već dodijeljeni ostaju vidljivi.
  const slobodni = radnici.filter((r) => !ids.includes(r.id) && r.prijavljuje_se !== false)

  if (!jeVoditelj) {
    return <span className="rad-tekst">{dodijeljeni.map((r) => r.ime).join(', ') || '—'}</span>
  }
  return (
    <div className="rad-multi">
      {dodijeljeni.map((r) => (
        <span key={r.id} className="rad-chip">
          {r.ime}
          <span className="rad-chip-x" onClick={() => postavi(ids.filter((x) => x !== r.id))}>×</span>
        </span>
      ))}
      {slobodni.length > 0 && (
        <select
          className="rad-select"
          value=""
          onChange={(e) => { if (e.target.value) postavi([...ids, Number(e.target.value)]) }}
        >
          <option value="">{t('op.dodajRadnika')}</option>
          {slobodni.map((r) => <option key={r.id} value={r.id}>{r.ime}</option>)}
        </select>
      )}
    </div>
  )
}

function DodajZadatak({ nalogId, opId, naGotovo, naGresku }) {
  const { t } = useT()
  const [opis, setOpis] = useState('')
  const spremi = async () => {
    if (!opis.trim()) return
    try { await api.dodajZadatak(nalogId, opId, opis.trim()); setOpis(''); naGotovo() }
    catch (e) { naGresku(e.message) }
  }
  return (
    <div className="btn-red" style={{ marginTop: 10, alignItems: 'stretch' }}>
      <input value={opis} onChange={(e) => setOpis(e.target.value)} placeholder={t('op.noviZadatak')}
        onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), spremi())} />
      <MikrofonGumb naslov={t('op.diktirajZadatak')} onTekst={(tekst) => setOpis((v) => (v ? v + ' ' : '') + tekst)} />
      <button className="btn sekund mali" onClick={spremi} disabled={!opis.trim()}>{t('op.zadatak')}</button>
    </div>
  )
}
