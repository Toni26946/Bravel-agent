import { Fragment, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import Layout from '../Layout'
import { api, medijUrl } from '../api'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import {
  Bedz, KategorijaPicker, MikrofonGumb, Spinner, datum, datumVrijeme, useAutoOsvjezi, voziloLabel,
} from '../ui'
import { rokoviVozila, hrDatum, PRAG_USKORO } from '../pregledi'
import SlikaEditor from '../SlikaEditor'

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
  const [servis, setServis] = useState(null)
  const [pregled, setPregled] = useState(null)   // periodične provjere vozila (registar)
  const [lok, setLok] = useState(null)           // trenutna lokacija vozila (GPS → naziv mjesta)

  const ucitaj = () => api.nalog(id).then(setN).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [id])
  // Tiho osvježavanje (bez spinnera/greške) svakih 20 s i na povratak u aplikaciju.
  useAutoOsvjezi(() => api.nalog(id).then(setN).catch(() => {}))
  useEffect(() => {
    api.korisnici('radnik').then(setRadnici).catch(() => {})
  }, [])
  // Servisni status vozila (za banner na ekranu i u ispisu).
  const voziloGb = n?.vozilo?.gb
  useEffect(() => {
    if (!voziloGb) { setServis(null); return }
    api.servisVozila(voziloGb).then(setServis).catch(() => setServis(null))
  }, [voziloGb])
  // Periodične provjere (periodički/baždar taho/PP/registracija) — banner + ispis.
  useEffect(() => {
    if (!voziloGb) { setPregled(null); return }
    api.pregledVozila(voziloGb).then(setPregled).catch(() => setPregled(null))
  }, [voziloGb])
  // Trenutna lokacija vozila po GPS-u (naziv mjesta) — tiho, ako nema pozicije ostaje prazno.
  useEffect(() => {
    if (!voziloGb) { setLok(null); return }
    api.nalogLokacija(id).then(setLok).catch(() => setLok(null))
  }, [voziloGb, id])

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
      <ServisBanner s={servis} />
      <PreglediBanner v={pregled} />
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
        {lok?.mjesto && (
          <p className="meta">📍 {t('nalog.lokacija')}: <strong>{lok.mjesto}</strong>
            {typeof lok.udaljenost_m === 'number' && (
              <span> · {lok.udaljenost_m >= 1000
                ? (lok.udaljenost_m / 1000).toFixed(1).replace('.', ',') + ' km'
                : Math.round(lok.udaljenost_m) + ' m'} {t('nalog.odRadione')}</span>
            )}
          </p>
        )}
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

      {/* Dijelovi za naručiti → kartica „Narudžbe" (skladištar) */}
      <NarudzbeBlok nalogId={n.id} gb={n.vozilo?.gb} naGresku={setGreska} />

      {/* Utrošeni dijelovi (izdatnice) → vozilo / trošak po vozilu */}
      <IzdatniceBlok nalogId={n.id} gb={n.vozilo?.gb} naGresku={setGreska} />

      {/* Ispis naloga (vidljivo samo pri printanju) */}
      <NalogPrint n={n} servis={servis} pregled={pregled} />
    </Layout>
  )
}

// --- Servisni banner u nalogu ------------------------------------------------
// Uvijek pokaže koliko još km do servisa; ako je dospjelo/uskoro — bode u oči.
function kmFmt(x) { try { return Math.round(x).toLocaleString('hr-HR') } catch (_) { return x } }

// Zajednički izračun teksta (ekran + ispis). Vrati null ako nema km ni vremena.
function servisTekst(t, s) {
  if (!s) return null
  const imaKm = s.km_preostalo !== null && s.km_preostalo !== undefined
  const imaVrijeme = s.preostalo_dana !== null && s.preostalo_dana !== undefined
  if (!imaKm && !imaVrijeme) return null

  const kmTxt = !imaKm ? null
    : s.km_preostalo <= 0
      ? `${t('servisi.prekoraceno')} ${kmFmt(-s.km_preostalo)} km`
      : `${t('nalog.jos')} ${kmFmt(s.km_preostalo)} km ${t('nalog.doServisa')}`
  const vrTxt = !imaVrijeme ? null
    : s.preostalo_dana <= 0
      ? `${t('servisi.proslo')} ${Math.abs(s.preostalo_dana)} ${t('servisi.dana')}`
      : `${t('nalog.jos')} ${s.preostalo_dana} ${t('servisi.dana')}${s.iduci_datum ? ` (${datum(s.iduci_datum)})` : ''}`
  return { status: s.status, kmTxt, vrTxt }
}

function ServisBanner({ s }) {
  const { t } = useT()
  const info = servisTekst(t, s)
  if (!info) return null
  const detalji = [info.kmTxt && `🛣️ ${info.kmTxt}`, info.vrTxt && `🗓️ ${info.vrTxt}`].filter(Boolean).join('  ·  ')

  if (info.status === 'dospjelo') {
    return (
      <div className="servis-banner dospjelo">
        <div className="sb-naslov">⚠️ {t('nalog.servisDospio')}</div>
        <div className="sb-det">{detalji}</div>
      </div>
    )
  }
  if (info.status === 'uskoro') {
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

// Servisni redak za ispis naloga (crno-bijelo; okvir + podebljano kad dospije/blizu).
function ServisPrint({ s }) {
  const { t } = useT()
  const info = servisTekst(t, s)
  if (!info) return null
  const detalji = [info.kmTxt, info.vrTxt].filter(Boolean).join(' · ')
  const naslov = info.status === 'dospjelo' ? `⚠ ${t('nalog.servisDospio')}`
    : info.status === 'uskoro' ? t('nalog.servisUskoro')
    : t('nalog.servis')
  const klasa = 'np-servis' + (info.status === 'dospjelo' ? ' dospjelo' : info.status === 'uskoro' ? ' uskoro' : '')
  return <div className={klasa}><span>{naslov}:</span> {detalji}</div>
}

// --- Banner periodičnih provjera u nalogu ------------------------------------
// Pokaže sve rokove (periodički/baždar taho/PP/registracija); ako je nešto
// isteklo ili istječe ≤14 dana — jako se označi (kao servis).
function stanjeRoka(dana) {
  if (dana == null) return 'nepoznato'
  if (dana < 0) return 'isteklo'
  if (dana <= PRAG_USKORO) return 'uskoro'
  return 'ok'
}
function PreglediBanner({ v }) {
  const { t } = useT()
  if (!v) return null
  const rokovi = rokoviVozila(v).filter((r) => r.istek)
  if (rokovi.length === 0) return null
  const hitni = rokovi.filter((r) => r.dana != null && r.dana <= PRAG_USKORO)
  const najgore = hitni.some((r) => r.dana < 0) ? 'isteklo' : hitni.length ? 'uskoro' : 'ok'

  const redak = (r) => {
    const st = stanjeRoka(r.dana)
    const kada = r.dana < 0 ? t('pv.isteklo') : `${r.dana} ${t('pv.dana')}`
    return (
      <span key={r.k} className={'pvb-cip ' + st}>
        {t(r.txt)}: <strong>{hrDatum(r.istek)}</strong> · {kada}
      </span>
    )
  }

  if (najgore === 'ok') {
    // Ništa hitno — nenametljiva linija sa svim rokovima.
    return (
      <div className="pregledi-banner ok">
        <span className="pvb-naslov">🗓️ {t('nalog.pregledi')}:</span>
        <span className="pvb-cipovi">{rokovi.map(redak)}</span>
      </div>
    )
  }
  return (
    <div className={'pregledi-banner ' + najgore}>
      <div className="pvb-naslov">
        {najgore === 'isteklo' ? '⚠️ ' : '🟡 '}
        {najgore === 'isteklo' ? t('nalog.pregledDospio') : t('nalog.pregledUskoro')}
      </div>
      <div className="pvb-cipovi">{rokovi.map(redak)}</div>
    </div>
  )
}

// Redak periodičnih provjera za ispis (crno-bijelo; podebljano kad dospije/blizu).
function PreglediPrint({ v }) {
  const { t } = useT()
  if (!v) return null
  const rokovi = rokoviVozila(v).filter((r) => r.istek)
  if (rokovi.length === 0) return null
  const hitno = rokovi.some((r) => r.dana != null && r.dana <= PRAG_USKORO)
  const isteklo = rokovi.some((r) => r.dana != null && r.dana < 0)
  const detalji = rokovi.map((r) => `${t(r.txt)}: ${hrDatum(r.istek)}${r.dana < 0 ? ` (${t('pv.isteklo')})` : ''}`).join(' · ')
  const klasa = 'np-servis' + (isteklo ? ' dospjelo' : hitno ? ' uskoro' : '')
  return <div className={klasa}><span>{t('nalog.pregledi')}:</span> {detalji}</div>
}

// --- Ispis radnog naloga -----------------------------------------------------
function NalogPrint({ n, servis, pregled }) {
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

      <ServisPrint s={servis} />
      <PreglediPrint v={pregled} />

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
  // stop: spriječi da klik (npr. unutar <label> zadatka) prebaci checkbox "gotovo".
  const stop = (e) => { e.preventDefault(); e.stopPropagation() }
  const spremi = (e) => {
    if (e) stop(e)
    const v = (val || '').trim()
    if (v && v !== vrijednost) onSpremi(v)
    setOtvoren(false)
  }
  if (otvoren) {
    return (
      <span className="tu-uredi" onClick={stop}>
        <input
          className="tu-input"
          value={val}
          autoFocus
          onClick={stop}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') spremi(e); if (e.key === 'Escape') { stop(e); setOtvoren(false) } }}
        />
        <span className="tu-ik ok" onClick={spremi}>✓</span>
        <span className="tu-ik" onClick={(e) => { stop(e); setVal(vrijednost); setOtvoren(false) }}>✕</span>
      </span>
    )
  }
  return (
    <>
      <span className={prikazKlasa}>{vrijednost}</span>
      {editable && <span className="tu-ol" onClick={(e) => { stop(e); setVal(vrijednost); setOtvoren(true) }}>✏️</span>}
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
              <TekstUredivi
                vrijednost={z.opis}
                editable={jeVoditelj}
                prikazKlasa={z.gotovo ? 'zad-gotov' : ''}
                onSpremi={(v) => wrap(api.azurirajZadatak(nalog.id, z.id, { opis: v }))}
              />
              {jeVoditelj && <span className="x" onClick={(e) => { e.preventDefault(); e.stopPropagation(); wrap(api.obrisiZadatak(nalog.id, z.id)) }}>×</span>}
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
                  {z.zavrsio && <> · <b>označio: {z.zavrsio.ime}</b></>}
                </span>
              )}
              {z.vremena && z.vremena.length > 0 && (
                <div className="mj-radnici">
                  {z.vremena.map((zr) => {
                    const rad = !!zr.zapoceto
                    const sek = (zr.utroseno_sek || 0) + (rad ? Math.max(0, (sada - msVremena(zr.zapoceto)) / 1000) : 0)
                    if (sek <= 0 && !rad) return null
                    return (
                      <span key={zr.radnik_id} className={'mj-radnik' + (rad ? ' radi' : '')}>
                        {rad ? '⏱' : ''} {zr.radnik?.ime || ''} · {trajanje(sek)}
                      </span>
                    )
                  })}
                </div>
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

// Popis radnika na zadatku — SAMO prikaz. Dodjela/skidanje radnika (prijava) radi
// se isključivo u Planu (dispečer), ne na nalogu.
function RadniciZadatka({ z }) {
  const dodijeljeni = z.radnici && z.radnici.length ? z.radnici : (z.zaduzeni ? [z.zaduzeni] : [])
  return <span className="rad-tekst">{dodijeljeni.map((r) => r.ime).join(', ') || '—'}</span>
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

// --- Utrošeni dijelovi (izdatnice) na nalogu → vozilo / trošak po vozilu ---
// Oznake statusa narudžbe (dio za naručiti)
const NAR_STATUS = {
  trazeno: { t: '🟠 za naručiti', c: '#b45309', b: '#fff2db' },
  naruceno: { t: '🔵 naručeno', c: '#1d4ed8', b: '#e5edff' },
  stiglo: { t: '🟢 stiglo', c: '#047857', b: '#dcfce7' },
}
function NarStatusBadge({ s }) {
  const o = NAR_STATUS[s] || NAR_STATUS.trazeno
  return <span style={{ fontSize: 11, fontWeight: 700, color: o.c, background: o.b, borderRadius: 999, padding: '2px 8px', whiteSpace: 'nowrap' }}>{o.t}</span>
}

// Unos dijelova za naručiti iz radnog naloga (ide u karticu „Narudžbe" skladištara).
function NarudzbeBlok({ nalogId, gb, naGresku }) {
  const [lista, setLista] = useState(null)
  const [naziv, setNaziv] = useState('')
  const [kataloski, setKataloski] = useState('')
  const [kol, setKol] = useState('1')
  const [jmj, setJmj] = useState('kom')
  const [napomena, setNapomena] = useState('')
  const [fotke, setFotke] = useState([])
  const [radi, setRadi] = useState(false)
  const [slanjeSlike, setSlanjeSlike] = useState(false)
  const [editorRed, setEditorRed] = useState([])   // poslikane fotke koje čekaju označavanje
  const fileRef = useRef(null)

  const ucitaj = () => api.narudzbeNaloga(nalogId).then(setLista).catch((e) => naGresku(e.message))
  useEffect(() => { ucitaj() }, [nalogId])

  // Nakon slikanja NE šaljemo odmah — prvo otvorimo editor da korisnik zaokruži što je slikao.
  const dodajSliku = (e) => {
    const files = Array.from(e.target.files || [])
    if (fileRef.current) fileRef.current.value = ''
    if (!files.length) return
    setEditorRed(files)
  }
  const posaljiFajl = async (f) => {
    setSlanjeSlike(true)
    try {
      const fd = new FormData(); fd.append('slika', f)
      const r = await api.narudzbaFoto(fd)
      if (r && r.foto) setFotke((p) => [...p, r.foto])
    } catch (err) { naGresku(err.message) } finally { setSlanjeSlike(false) }
  }
  const editorGotovo = async (f) => { await posaljiFajl(f); setEditorRed((red) => red.slice(1)) }
  const editorPreskoci = () => setEditorRed((red) => red.slice(1))
  const makniSliku = (i) => setFotke((p) => p.filter((_, j) => j !== i))

  const dodaj = async () => {
    const nz = naziv.trim()
    const k = Number(kol); if (!(k > 0)) return naGresku('Količina mora biti veća od 0.')
    // Naziv nije obavezan — ali mora postojati bar nešto (naziv/kataloški/napomena/slika).
    if (!nz && !kataloski.trim() && !napomena.trim() && fotke.length === 0)
      return naGresku('Upiši barem naziv, kataloški broj, napomenu ili dodaj sliku.')
    setRadi(true)
    try {
      await api.dodajNarudzbu(nalogId, { naziv: nz, kataloski: kataloski.trim() || null, kolicina: k, jmj: jmj.trim() || 'kom', napomena: napomena.trim() || null, fotografije: fotke })
      setNaziv(''); setKataloski(''); setKol('1'); setJmj('kom'); setNapomena(''); setFotke([]); ucitaj()
    } catch (e) { naGresku(e.message) } finally { setRadi(false) }
  }
  const obrisi = async (id) => { try { await api.obrisiNarudzbu(id); ucitaj() } catch (e) { naGresku(e.message) } }

  return (
    <>
      {editorRed.length > 0 && (
        <SlikaEditor key={editorRed.length} file={editorRed[0]} onGotovo={editorGotovo} onOdustani={editorPreskoci} />
      )}
      <div className="sekcija-naslov">📦 Dijelovi za naručiti {gb ? `· GB ${gb}` : ''}</div>
      <div className="karta">
        <input value={naziv} placeholder="što treba naručiti (naziv dijela, opcijski)…" onChange={(e) => setNaziv(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} />
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <div style={{ flex: 2 }}><label className="meta">Kataloški broj</label><input value={kataloski} onChange={(e) => setKataloski(e.target.value)} placeholder="opcijski" style={{ width: '100%', boxSizing: 'border-box' }} /></div>
          <div style={{ flex: 1 }}><label className="meta">Količina</label><input type="number" step="any" value={kol} onChange={(e) => setKol(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} /></div>
          <div style={{ width: 70 }}><label className="meta">JMJ</label><input value={jmj} onChange={(e) => setJmj(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} /></div>
        </div>
        <input value={napomena} placeholder="napomena (opcijski)…" onChange={(e) => setNapomena(e.target.value)} style={{ width: '100%', boxSizing: 'border-box', marginTop: 8 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" multiple onChange={dodajSliku} style={{ display: 'none' }} />
          <button className="btn mali" type="button" disabled={slanjeSlike} onClick={() => fileRef.current && fileRef.current.click()}>{slanjeSlike ? 'Učitavam…' : '📷 Poslikaj dio'}</button>
          {fotke.map((f, i) => (
            <span key={i} style={{ position: 'relative', display: 'inline-block' }}>
              <img src={medijUrl(f)} alt="" style={{ width: 44, height: 44, objectFit: 'cover', borderRadius: 6, border: '1px solid var(--line, #ddd)' }} />
              <span onClick={() => makniSliku(i)} style={{ position: 'absolute', top: -6, right: -6, background: '#000', color: '#fff', borderRadius: 999, width: 18, height: 18, fontSize: 12, lineHeight: '18px', textAlign: 'center', cursor: 'pointer' }}>×</span>
            </span>
          ))}
          <button className="btn mali" style={{ marginLeft: 'auto' }} disabled={radi} onClick={dodaj}>➕ Dodaj u narudžbe</button>
        </div>

        {lista === null ? <Spinner /> : lista.length === 0 ? <p className="meta" style={{ marginTop: 10 }}>Još nema upisanih dijelova za naručiti.</p> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 10 }}>
            <tbody>
              {lista.map((i) => (
                <tr key={i.id} style={{ borderTop: '1px solid var(--line, #eee)' }}>
                  <td style={{ padding: '4px 6px' }}>
                    {i.naziv || <em className="meta">bez naziva</em>}{i.kataloski ? <span className="meta"> · {i.kataloski}</span> : ''}
                    {i.napomena ? <div className="meta">{i.napomena}</div> : null}
                    {(i.fotografije || []).length > 0 && (
                      <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                        {i.fotografije.map((f, j) => (
                          <a key={j} href={medijUrl(f)} target="_blank" rel="noreferrer"><img src={medijUrl(f)} alt="" style={{ width: 36, height: 36, objectFit: 'cover', borderRadius: 4, border: '1px solid var(--line, #ddd)' }} /></a>
                        ))}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: '4px 6px', textAlign: 'right', whiteSpace: 'nowrap' }}>{i.kolicina} {i.jmj}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right' }}><NarStatusBadge s={i.status} /></td>
                  <td style={{ padding: '4px 6px', textAlign: 'right' }}>{i.status === 'trazeno' ? <span className="x" style={{ cursor: 'pointer' }} onClick={() => obrisi(i.id)}>×</span> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}

function IzdatniceBlok({ nalogId, gb, naGresku }) {
  const [lista, setLista] = useState(null)
  const [artikl, setArtikl] = useState(null)
  const [q, setQ] = useState('')
  const [rez, setRez] = useState([])
  const [open, setOpen] = useState(false)
  const [kol, setKol] = useState('1')
  const [cijena, setCijena] = useState('')
  const [radi, setRadi] = useState(false)
  const tref = useRef(null)

  const ucitaj = () => api.izdatnice(nalogId).then(setLista).catch((e) => naGresku(e.message))
  useEffect(() => { ucitaj() }, [nalogId])

  const run = (v) => {
    setQ(v); setArtikl(null); setOpen(true)
    clearTimeout(tref.current)
    tref.current = setTimeout(async () => { try { setRez(await api.arossArtikliTrazi(v)) } catch { setRez([]) } }, 300)
  }
  const kreirajNovi = async () => {
    if (!q.trim()) return
    try { const r = await api.arossKreirajArtikl({ naziv: q.trim() }); if (r && r.artikl) { setArtikl(r.artikl); setQ(r.artikl.naziv); setRez([]); setOpen(false) } }
    catch (e) { naGresku(e.message) }
  }
  const dodaj = async () => {
    if (!artikl) return naGresku('Odaberi artikl iz Aprossa.')
    const k = Number(kol); if (!(k > 0)) return naGresku('Količina mora biti veća od 0.')
    setRadi(true)
    try {
      await api.dodajIzdatnicu(nalogId, { artikl_sifra: artikl.sifra, artikl_naziv: artikl.naziv, kataloski: artikl.kataloskiBroj || null, jmj: artikl.jmj || 'kom', kolicina: k, cijena: cijena === '' ? null : Number(cijena) })
      setArtikl(null); setQ(''); setRez([]); setKol('1'); setCijena(''); ucitaj()
    } catch (e) { naGresku(e.message) } finally { setRadi(false) }
  }
  const obrisi = async (id) => { try { await api.obrisiIzdatnicu(nalogId, id); ucitaj() } catch (e) { naGresku(e.message) } }
  const eur = (n) => (n == null ? '—' : Number(n).toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €')
  const ukupno = (lista || []).reduce((a, i) => a + (i.iznos || 0), 0)

  return (
    <>
      <div className="sekcija-naslov">🧰 Utrošeni dijelovi {gb ? `· GB ${gb}` : ''}</div>
      <div className="karta">
        <div style={{ position: 'relative' }}>
          <input value={q} placeholder="traži dio (Apross artikl / kat. broj)…" onChange={(e) => run(e.target.value)} onFocus={() => setOpen(true)} style={{ width: '100%', boxSizing: 'border-box' }} />
          {open && q.trim() && (
            <div style={{ position: 'absolute', zIndex: 20, background: 'var(--karta, #fff)', border: '1px solid var(--line, #ccc)', borderRadius: 8, width: '100%', maxHeight: 200, overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,.12)' }}>
              {rez.map((a, i) => (
                <div key={i} onClick={() => { setArtikl(a); setQ(a.naziv); setOpen(false) }} style={{ padding: '6px 8px', cursor: 'pointer', borderTop: i ? '1px solid var(--line, #eee)' : 'none', fontSize: 13 }}>
                  {a.naziv}{a.kataloskiBroj ? ` · ${a.kataloskiBroj}` : ''}
                </div>
              ))}
              <div onClick={kreirajNovi} style={{ padding: '7px 8px', cursor: 'pointer', borderTop: '1px solid var(--line, #eee)', fontSize: 13, color: 'var(--plava, #2563eb)', fontWeight: 600 }}>➕ Kreiraj novi artikl: „{q.trim()}"</div>
            </div>
          )}
        </div>
        {artikl && <div className="meta" style={{ color: 'var(--zelena, green)', marginTop: 4 }}>✓ {artikl.naziv} (šifra {artikl.sifra})</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <div style={{ flex: 1 }}><label className="meta">Količina</label><input type="number" step="any" value={kol} onChange={(e) => setKol(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} /></div>
          <div style={{ flex: 1 }}><label className="meta">Cijena (EUR)</label><input type="number" step="any" value={cijena} onChange={(e) => setCijena(e.target.value)} placeholder="opcijski" style={{ width: '100%', boxSizing: 'border-box' }} /></div>
          <div style={{ alignSelf: 'flex-end' }}><button className="btn mali" disabled={radi || !artikl} onClick={dodaj}>➕ Dodaj</button></div>
        </div>
        {!gb && <p className="meta" style={{ color: 'var(--crveno)' }}>Nalog nema vozilo — izdatnica se neće vezati na GB.</p>}

        {lista === null ? <Spinner /> : lista.length === 0 ? <p className="meta" style={{ marginTop: 10 }}>Još nema utrošenih dijelova.</p> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 10 }}>
            <tbody>
              {lista.map((i) => (
                <tr key={i.id} style={{ borderTop: '1px solid var(--line, #eee)' }}>
                  <td style={{ padding: '4px 6px' }}>{i.artikl_naziv}{i.kataloski ? <span className="meta"> · {i.kataloski}</span> : ''}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right', whiteSpace: 'nowrap' }}>{i.kolicina} {i.jmj}{i.cijena != null ? ` × ${eur(i.cijena)} = ${eur(i.iznos)}` : ''}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right' }}><span className="x" style={{ cursor: 'pointer' }} onClick={() => obrisi(i.id)}>×</span></td>
                </tr>
              ))}
              <tr><td style={{ padding: '6px', fontWeight: 700 }}>Ukupno</td><td style={{ padding: '6px', textAlign: 'right', fontWeight: 700 }}>{eur(ukupno)}</td><td /></tr>
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
