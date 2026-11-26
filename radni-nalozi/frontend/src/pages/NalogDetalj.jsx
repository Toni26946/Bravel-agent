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
import { CrtezOsovina } from './TestoviKocnica'
import { usePonisti } from '../ponisti'

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
  const { zabiljezi } = usePonisti()
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

  // Cijeli ekran greške samo kad se nalog nije ni učitao. Greška neke radnje (npr. zatvaranje
  // blokirano testom kočnica) stoji IZNAD naloga — prije je brisala cijelu stranicu (WhatsApp #411).
  if (!n) return <Layout naslov="Nalog" nazad={true}>{greska ? <div className="greska">{greska}</div> : <Spinner />}</Layout>

  const ciljevi = ciljeviStatusa(korisnik.uloga, n.status)

  const promijeniStatus = async (status) => {
    setGreska('')
    const stari = n.status
    try {
      await api.nalogStatus(id, status); ucitaj()
      // ↶ Poništi: vrati prethodni status (WhatsApp #377).
      zabiljezi({
        opis: `Status: ${t('status.' + status)}`,
        vrati: () => api.nalogStatus(id, stari), nakon: ucitaj, naGresku: setGreska,
      })
    } catch (e) { setGreska(e.message) }
  }

  const jeUrednik = korisnik.uloga === 'voditelj' || korisnik.uloga === 'poslovodja'
  const zapocniUredi = () => { setForma({ naslov: n.naslov || '', opis: n.opis || '' }); setUredi(true) }
  const spremiUredi = async () => {
    setGreska('')
    const staro = { naslov: n.naslov || '', opis: n.opis || '' }
    try {
      await api.azurirajNalog(id, { naslov: forma.naslov, opis: forma.opis }); setUredi(false); ucitaj()
      zabiljezi({ opis: 'Izmijenjen nalog', vrati: () => api.azurirajNalog(id, staro), nakon: ucitaj, naGresku: setGreska })
    }
    catch (e) { setGreska(e.message) }
  }

  return (
    <Layout naslov={n.broj} nazad={true}>
      {spojeno && (
        <div className="uspjeh">{t('nalog.spojeno')}</div>
      )}
      {greska && (
        <div className="greska" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ flex: 1 }}>{greska}</span>
          <button type="button" className="btn sekund mali" onClick={() => setGreska('')} title="Zatvori poruku">✕</button>
        </div>
      )}
      {/* Test kočnica koji blokira zatvaranje — razvrstava se odmah ovdje (WhatsApp #411) */}
      <TestoviZaRazvrstati nalog={n} jeUrednik={jeUrednik} nakon={() => { setGreska(''); ucitaj() }} naGresku={setGreska} />
      <ServisBanner s={servis} />
      <PreglediBanner v={pregled} />
      <div className="karta">
        <div className="naslov-red">
          {uredi
            ? <input className="pretraga-input" style={{ marginRight: 8 }} value={forma.naslov}
                onChange={(e) => setForma({ ...forma, naslov: e.target.value })} placeholder={t('nalog.naslovPh')} />
            : <h3>{n.naslov}</h3>}
          <Bedz vrsta={n.status} tekst={t('status.' + n.status)} />
          {n.valjci && <ValjciBedz kad={n.valjci} onClick={() => document.getElementById('valjci-rezultati')?.scrollIntoView({ behavior: 'smooth' })} />}
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

      {/* Testovi kočnica s Cartec valjaka vezani uz ovaj nalog */}
      <TestoviKocnicaBlok nalogId={n.id} />

      {/* Ispis naloga (vidljivo samo pri printanju) */}
      <NalogPrint n={n} servis={servis} pregled={pregled} />
    </Layout>
  )
}

// Oznaka da je nalog (vozilo) bio na valjcima — klik vodi na rezultate.
export function ValjciBedz({ kad, onClick }) {
  const d = (() => { try { return new Date(kad).toLocaleDateString('hr-HR', { day: '2-digit', month: '2-digit' }) } catch { return '' } })()
  return (
    <span onClick={onClick} title="Vozilo je bilo na valjcima — rezultati kočenja su u nalogu"
      style={{ display: 'inline-block', marginLeft: 6, padding: '2px 8px', borderRadius: 999, fontSize: 12, fontWeight: 700,
        background: '#fff3e0', color: '#e65100', border: '1px solid #ffb74d', cursor: onClick ? 'pointer' : 'default', whiteSpace: 'nowrap' }}>
      🛞 valjci {d}
    </span>
  )
}

// --- Nerazvrstani testovi kočnica koji bi mogli biti ovog naloga ---------------
// Dok takav test postoji, nalog se ne može zatvoriti (server vraća 409). Umjesto da
// korisnik traži stranicu „Testovi kočnica", ovdje vidi test i jednim klikom ga veže
// na ovaj nalog (isti API kao na stranici Testovi kočnica) ili ode na tu stranicu.
function TestoviZaRazvrstati({ nalog, jeUrednik, nakon, naGresku }) {
  const nav = useNavigate()
  const [testovi, setTestovi] = useState([])
  const [radi, setRadi] = useState(null)
  const ucitajT = () => api.testoviKocnica({ status: 'otvoreni' })
    .then((sv) => setTestovi((sv || []).filter((t) =>
      t.nalog?.id === nalog.id || (t.kandidati || []).some((k) => k.id === nalog.id))))
    .catch(() => setTestovi([]))
  useEffect(() => { if (jeUrednik) ucitajT() }, [nalog.id, nalog.status, jeUrednik])
  if (!jeUrednik || !testovi.length) return null
  const vezi = async (t) => {
    setRadi(t.id)
    try { await api.testKocnicaVezi(t.id, nalog.id); await ucitajT(); nakon() }
    catch (e) { naGresku(e.message) }
    finally { setRadi(null) }
  }
  const kad = (d) => { try { return new Date(d).toLocaleString('hr-HR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) } catch { return '' } }
  return (
    <div className="karta" style={{ borderLeft: '4px solid var(--crvena)' }}>
      <b>🛞 Test kočnica čeka odabir vozila</b>
      <div className="meta" style={{ margin: '4px 0 8px' }}>
        Dok test nije razvrstan, nalog se ne može zatvoriti. Ako je test rađen na ovom vozilu, veži ga na ovaj nalog.
      </div>
      {testovi.map((t) => (
        <div key={t.id} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, padding: '6px 0', borderTop: '1px solid #e3e7ee' }}>
          <span style={{ flex: '1 1 200px' }}>
            {kad(t.pocetak)}{t.osovina > 0 && ` · ${t.osovina} ${t.osovina === 1 ? 'osovina' : 'osovine'}`}
            {t.napomena && <span style={{ color: 'var(--crvena)', marginLeft: 6 }}>{t.napomena}</span>}
          </span>
          <button type="button" className="btn mali" disabled={radi === t.id} onClick={() => vezi(t)}>
            {radi === t.id ? '…' : `✅ Ovo je ${nalog.vozilo?.gb ? 'GB ' + nalog.vozilo.gb : 'ovo vozilo'}`}
          </button>
          <button type="button" className="btn sekund mali" onClick={() => nav('/testovi-kocnica')}>Drugo vozilo →</button>
        </div>
      ))}
    </div>
  )
}

// --- Testovi kočnica (Cartec valjci) vezani uz nalog ---------------------------
function TestoviKocnicaBlok({ nalogId }) {
  const [testovi, setTestovi] = useState([])
  useEffect(() => { api.testoviKocnica({ nalogId }).then(setTestovi).catch(() => setTestovi([])) }, [nalogId])
  if (!testovi.length) return null
  return (
    <>
      <div className="sekcija-naslov" id="valjci-rezultati">🛞 Valjci — rezultati kočenja</div>
      {testovi.map((t) => (
        <div key={t.id} className="card">
          <b>{new Date(t.pocetak).toLocaleString('hr-HR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</b>
          {t.status !== 'vezan' && <span style={{ color: 'var(--crvena)', marginLeft: 8 }}>{t.napomena || 'čeka potvrdu'}</span>}
          <CrtezOsovina mjerenja={t.mjerenja} />
        </div>
      ))}
    </>
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
  const pon = usePonisti()
  const wrap = (p) => p.then(ucitaj).catch((e) => naGresku(e.message))
  const dodajOp = (kat) => {
    const k = (kat || '').trim()
    if (!k) return
    wrap(api.dodajOperaciju(nalog.id, k).then((op) => {
      // ↶ Poništi dodavanje = obriši upravo dodanu operaciju.
      if (op && op.id) pon.zabiljezi({
        opis: `Dodana operacija „${k}"`,
        vrati: () => api.obrisiOperaciju(nalog.id, op.id), nakon: ucitaj, naGresku,
      })
    }))
  }
  // Operacije koje čekaju odgođeno brisanje (↶ Poništi) se ne prikazuju.
  const operacije = nalog.operacije.filter((op) => !pon.skriveni.has('op:' + op.id))

  return (
    <>
      <div className="op-tablica">
        <div className="op-head"><div>{t('op.operacija')}</div><div>{t('op.radnik')}</div></div>
        {operacije.length === 0 && <div className="op-prazno">{t('op.nemaOperacija')}</div>}
        {operacije.map((op) => (
          <OperacijaBlok key={op.id} nalog={nalog} op={op} radnici={radnici} wrap={wrap} ucitaj={ucitaj} naGresku={naGresku} sada={sada} jeVoditelj={jeVoditelj} pon={pon} />
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

function OperacijaBlok({ nalog, op, radnici, wrap, ucitaj, naGresku, sada, jeVoditelj, pon }) {
  const { t } = useT()
  const [dodaje, setDodaje] = useState(false)
  // ↶ Poništi (WhatsApp #377): × ne briše odmah nego s odgodom; izmjene pamte staru vrijednost.
  const kratko = (tx) => { const s = (tx || '').trim(); return s.length > 40 ? s.slice(0, 40) + '…' : s }
  const obrisiOp = () => pon.odgodi({
    opis: `Obrisana operacija „${kratko(op.kategorija)}"`, kljuc: 'op:' + op.id,
    izvrsi: () => api.obrisiOperaciju(nalog.id, op.id), nakon: ucitaj, naGresku,
  })
  const obrisiZad = (z) => pon.odgodi({
    opis: `Obrisan zadatak „${kratko(z.opis)}"`, kljuc: 'zad:' + z.id,
    izvrsi: () => api.obrisiZadatak(nalog.id, z.id), nakon: ucitaj, naGresku,
  })
  const izmijeni = (p, opis, vrati) => wrap(p.then(() => pon.zabiljezi({ opis, vrati, nakon: ucitaj, naGresku })))
  const zadaci = op.zadaci.filter((z) => !pon.skriveni.has('zad:' + z.id))
  return (
    <div className="op2">
      <div className="op2-kat">
        <TekstUredivi
          vrijednost={op.kategorija}
          editable={jeVoditelj}
          prikazKlasa="op2-ime"
          onSpremi={(v) => izmijeni(api.azurirajOperaciju(nalog.id, op.id, { kategorija: v }),
            `Preimenovana operacija „${kratko(v)}"`, () => api.azurirajOperaciju(nalog.id, op.id, { kategorija: op.kategorija }))}
        />
        {jeVoditelj && <span className="op2-plus" onClick={() => setDodaje((v) => !v)}>＋</span>}
        {jeVoditelj && <span className="x" onClick={obrisiOp}>×</span>}
      </div>
      <div className="op2-kat-r" />
      {zadaci.map((z) => {
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
                onChange={() => izmijeni(api.azurirajZadatak(nalog.id, z.id, { gotovo: !z.gotovo }),
                  `${z.gotovo ? 'Zadatak ponovno otvoren' : 'Zadatak označen gotovim'}: „${kratko(z.opis)}"`,
                  () => api.azurirajZadatak(nalog.id, z.id, { gotovo: z.gotovo }))}
              />
              <TekstUredivi
                vrijednost={z.opis}
                editable={jeVoditelj}
                prikazKlasa={z.gotovo ? 'zad-gotov' : ''}
                onSpremi={(v) => izmijeni(api.azurirajZadatak(nalog.id, z.id, { opis: v }),
                  `Izmijenjen zadatak „${kratko(v)}"`, () => api.azurirajZadatak(nalog.id, z.id, { opis: z.opis }))}
              />
              {jeVoditelj && <span className="x" onClick={(e) => { e.preventDefault(); e.stopPropagation(); obrisiZad(z) }}>×</span>}
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
              {(jeVoditelj || z.video_status) && <VideoUpute z={z} jeVoditelj={jeVoditelj} />}
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

// 📺 Upute iz videa: poslovođa/voditelj zalijepi YouTube link uz zadatak → sustav iz
// titlova složi korake, dijelove, alat, momente i upozorenja (mehaničar ih vidi na /z/).
const ytLink = (id, t) => `https://youtu.be/${encodeURIComponent(id)}${t ? `?t=${Math.round(t)}` : ''}`
const vrijemeVidea = (s) => {
  s = Math.max(0, Math.round(s || 0))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60
  return (h ? `${h}:${String(m).padStart(2, '0')}` : m) + ':' + String(x).padStart(2, '0')
}

function VideoUpute({ z, jeVoditelj }) {
  const [otvoreno, setOtvoreno] = useState(false)
  const [v, setV] = useState(null)          // podaci s API-ja
  const [unos, setUnos] = useState('')
  const [salje, setSalje] = useState(false)
  const [greska, setGreska] = useState('')
  const status = v ? (v.nema ? null : v.status) : z.video_status

  const ucitajV = () => api.videoUpute(z.id).then(setV).catch((e) => setGreska(e.message))
  useEffect(() => { if (otvoreno && !v) ucitajV() }, [otvoreno]) // eslint-disable-line react-hooks/exhaustive-deps
  // Dok se slaže (~20–60 s) — provjeravaj svakih 5 s.
  useEffect(() => {
    if (status !== 'obrada') return undefined
    const t = setInterval(ucitajV, 5000)
    return () => clearInterval(t)
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps

  const posalji = async (e) => {
    e?.preventDefault()
    const url = unos.trim()
    if (!url) return
    setSalje(true); setGreska('')
    try { setV(await api.videoUputePostavi(z.id, url)); setUnos('') } catch (er) { setGreska(er.message) }
    setSalje(false)
  }
  const obrisi = async () => {
    if (!window.confirm('Ukloniti upute iz videa s ovog zadatka?')) return
    try { await api.videoUputeObrisi(z.id); setV({ nema: true }) } catch (er) { setGreska(er.message) }
  }

  const oznaka = status === 'gotovo' ? '📺 Upute iz videa'
    : status === 'obrada' ? '📺 Slažem upute iz videa…'
      : status === 'greska' ? '📺 Upute: greška' : '📺 + Video upute'
  const u = v?.upute
  return (
    <div className={'vu-blok' + (otvoreno ? ' otv' : '')}>
      <button type="button" className={'vu-gumb' + (status ? ' vu-' + status : '')} onClick={() => setOtvoreno((o) => !o)}>
        {oznaka} {otvoreno ? '▴' : '▾'}
      </button>
      {otvoreno && (
        <div className="vu-panel">
          {greska && <div className="vu-gr">{greska}</div>}
          {status === 'obrada' && <div className="vu-info">⏳ Čitam titlove i slažem korake — traje do minute.</div>}
          {status === 'greska' && <div className="vu-gr">{v?.greska}</div>}
          {status === 'gotovo' && u && (
            <div className="vu-upute">
              <div className="vu-nasl">{u.naslov}</div>
              {u.sazetak && <div className="vu-saz">{u.sazetak}</div>}
              {u.upozorenja?.length > 0 && (
                <div className="vu-upoz"><b>⚠️ Pazi:</b><ul>{u.upozorenja.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
              )}
              <div className="vu-pod">Koraci</div>
              <ol className="vu-kor">
                {u.koraci.map((k, i) => (
                  <li key={i}>
                    <a className="vu-t" href={ytLink(v.video_id, k.t)} target="_blank" rel="noreferrer">▶ {vrijemeVidea(k.t)}</a> {k.opis}
                    {k.slika && <a href={ytLink(v.video_id, k.t)} target="_blank" rel="noreferrer"><img className="vu-img" src={medijUrl(k.slika)} alt="" loading="lazy" /></a>}
                  </li>
                ))}
              </ol>
              {u.dijelovi?.length > 0 && (<>
                <div className="vu-pod">Dijelovi</div>
                <ul>{u.dijelovi.map((d, i) => <li key={i}>{d.naziv}{d.kolicina ? ` · ${d.kolicina}` : ''}{d.oe && <span className="vu-oe"> OE {d.oe}</span>}</li>)}</ul>
              </>)}
              {u.alat?.length > 0 && (<>
                <div className="vu-pod">Alat</div>
                <ul>{u.alat.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </>)}
              {u.momenti?.length > 0 && (<>
                <div className="vu-pod">Momenti pritezanja</div>
                <ul>{u.momenti.map((m, i) => <li key={i}>{m.sto}: <b>{m.vrijednost}</b></li>)}</ul>
              </>)}
              <a className="vu-video" href={ytLink(v.video_id, 0)} target="_blank" rel="noreferrer">▶ {v.naslov || 'Pogledaj video'}</a>
            </div>
          )}
          {jeVoditelj && (
            <form className="vu-unos" onSubmit={posalji}>
              <input type="url" inputMode="url" placeholder="Zalijepi YouTube link (npr. zamjena pločica Scania R450)"
                value={unos} onChange={(e) => setUnos(e.target.value)} />
              <button type="submit" className="vu-btn" disabled={salje || !unos.trim()}>
                {salje ? 'Šaljem…' : status ? 'Zamijeni video' : 'Složi upute'}
              </button>
              {status && <button type="button" className="vu-btn vu-btn-sivi" onClick={obrisi}>Ukloni</button>}
            </form>
          )}
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

// Unos novog zadatka u operaciju (WhatsApp prijava #353: „neće prihvatiti zadatak").
// - <form> + onSubmit: tipka „Enter/Gotovo" na Android tipkovnicama (Samsung) ne šalje
//   uvijek keydown 'Enter' (dok je riječ u prijedlogu dolazi kao 'Unidentified'), a
//   submit forme radi uvijek.
// - Tekst se čita iz samog polja (ref), ne samo iz stanja — diktat/prijedlog tipkovnice
//   zna ostati u polju a da stanje još nije ažurirano.
// - Dok se sprema piše „Spremam…", a greška ostaje ISPOD polja (s tekstom), umjesto da
//   klik izgleda kao da ništa nije napravio.
function DodajZadatak({ nalogId, opId, naGotovo }) {
  const { t } = useT()
  const [opis, setOpis] = useState('')
  const [sprema, setSprema] = useState(false)
  const [greska, setGreska] = useState('')
  const poljeRef = useRef(null)
  const spremi = async (e) => {
    if (e) e.preventDefault()
    if (sprema) return
    const tekst = ((poljeRef.current && poljeRef.current.value) || opis || '').trim()
    if (!tekst) { setGreska('Upiši opis zadatka.'); return }
    setSprema(true); setGreska('')
    try { await api.dodajZadatak(nalogId, opId, tekst); setOpis(''); naGotovo() }
    catch (err) { setGreska(err.message || 'Zadatak nije spremljen — pokušaj ponovno.') }
    finally { setSprema(false) }
  }
  return (
    <form onSubmit={spremi} style={{ marginTop: 10 }}>
      <div className="btn-red" style={{ alignItems: 'stretch' }}>
        <input ref={poljeRef} value={opis} onChange={(e) => { setOpis(e.target.value); setGreska('') }}
          placeholder={t('op.noviZadatak')} enterKeyHint="done" />
        <MikrofonGumb naslov={t('op.diktirajZadatak')} onTekst={(tekst) => setOpis((v) => (v ? v + ' ' : '') + tekst)} />
        <button type="submit" className="btn sekund mali" disabled={sprema}>
          {sprema ? 'Spremam…' : t('op.zadatak')}
        </button>
      </div>
      {greska && <div className="greska" style={{ marginTop: 6 }}>{greska}</div>}
    </form>
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
  // ↶ Poništi (WhatsApp #377): brisanje s odgodom.
  const pon = usePonisti()
  const vidljivo = lista && lista.filter((x) => !pon.skriveni.has('nar:' + x.id))
  const obrisi = (id) => {
    const st = (lista || []).find((x) => x.id === id)
    pon.odgodi({
      opis: `Obrisana narudžba „${(st && (st.naziv || st.kataloski)) || 'dio'}"`, kljuc: 'nar:' + id,
      izvrsi: () => api.obrisiNarudzbu(id), nakon: ucitaj, naGresku,
    })
  }

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

        {vidljivo === null ? <Spinner /> : vidljivo.length === 0 ? <p className="meta" style={{ marginTop: 10 }}>Još nema upisanih dijelova za naručiti.</p> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 10 }}>
            <tbody>
              {vidljivo.map((i) => (
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
  // ↶ Poništi (WhatsApp #377): brisanje s odgodom.
  const pon = usePonisti()
  const vidljivo = lista && lista.filter((x) => !pon.skriveni.has('izd:' + x.id))
  const obrisi = (id) => {
    const st = (lista || []).find((x) => x.id === id)
    pon.odgodi({
      opis: `Obrisan dio „${(st && st.artikl_naziv) || 'dio'}"`, kljuc: 'izd:' + id,
      izvrsi: () => api.obrisiIzdatnicu(nalogId, id), nakon: ucitaj, naGresku,
    })
  }
  const eur = (n) => (n == null ? '—' : Number(n).toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €')
  const ukupno = (vidljivo || []).reduce((a, i) => a + (i.iznos || 0), 0)

  return (
    <>
      <div className="sekcija-naslov">🧰 Utrošeni dijelovi {gb ? `· GB ${gb}` : ''}</div>
      <div className="karta">
        <div style={{ position: 'relative' }}>
          <input value={q} placeholder="šifra, naziv ili kat. broj dijela (Apross)…" onChange={(e) => run(e.target.value)} onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              // Enter = uzmi prvi pogodak (kod unosa po šifri to je točna šifra)
              if (e.key !== 'Enter' || !rez.length) return
              e.preventDefault()
              const a = rez[0]
              if (/^\d+$/.test(q.trim()) && String(a.sifra) !== q.trim()) return   // stari rezultati (još se traži)
              setArtikl(a); setQ(a.naziv); setOpen(false)
            }}
            style={{ width: '100%', boxSizing: 'border-box' }} />
          {open && q.trim() && (
            <div style={{ position: 'absolute', zIndex: 20, background: 'var(--karta, #fff)', border: '1px solid var(--line, #ccc)', borderRadius: 8, width: '100%', maxHeight: 200, overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,.12)' }}>
              {rez.map((a, i) => (
                <div key={i} onClick={() => { setArtikl(a); setQ(a.naziv); setOpen(false) }} style={{ padding: '6px 8px', cursor: 'pointer', borderTop: i ? '1px solid var(--line, #eee)' : 'none', fontSize: 13 }}>
                  <b style={{ color: 'var(--muted, #666)', marginRight: 6 }}>{a.sifra}</b>{a.naziv}{a.kataloskiBroj ? ` · ${a.kataloskiBroj}` : ''}
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
        {!gb && <p className="meta" style={{ color: 'var(--crvena)' }}>Nalog nema vozilo — izdatnica se neće vezati na GB.</p>}

        {vidljivo === null ? <Spinner /> : vidljivo.length === 0 ? <p className="meta" style={{ marginTop: 10 }}>Još nema utrošenih dijelova.</p> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 10 }}>
            <tbody>
              {vidljivo.map((i) => (
                <tr key={i.id} style={{ borderTop: '1px solid var(--line, #eee)' }}>
                  <td style={{ padding: '4px 6px' }}>{i.artikl_naziv}{i.kataloski ? <span className="meta"> · {i.kataloski}</span> : ''}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right', whiteSpace: 'nowrap' }}>{i.kolicina} {i.jmj}{i.cijena != null ? ` × ${eur(i.cijena)} = ${eur(i.iznos)}` : ''}</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {i.apross_broj
                      ? <span className="meta" style={{ color: 'var(--zelena, green)' }} title="Poslano u Apross">✓ #{i.apross_broj}</span>
                      : <span className="x" style={{ cursor: 'pointer' }} onClick={() => obrisi(i.id)}>×</span>}
                  </td>
                </tr>
              ))}
              <tr><td style={{ padding: '6px', fontWeight: 700 }}>Ukupno</td><td style={{ padding: '6px', textAlign: 'right', fontWeight: 700 }}>{eur(ukupno)}</td><td /></tr>
            </tbody>
          </table>
        )}
        {vidljivo && vidljivo.some((i) => !i.apross_broj) && (
          <IzdatnicaApross nalogId={nalogId} brojNeposlanih={lista.filter((i) => !i.apross_broj).length} onPoslano={ucitaj} naGresku={naGresku} />
        )}
      </div>
    </>
  )
}

// Slanje neposlanih utrošenih dijelova u Apross kao JEDNE izdatnice na teret vozila
// (mjesto troška = garažni broj — šifra mjesta troška u Aprossu je GB; može se i ručno odabrati).
function IzdatnicaApross({ nalogId, brojNeposlanih, onPoslano, naGresku }) {
  const [otv, setOtv] = useState(false)
  const [prip, setPrip] = useState(null)
  const [skl, setSkl] = useState([])
  const [sklId, setSklId] = useState('')
  const [mt, setMt] = useState(null)
  const [mtQ, setMtQ] = useState('')
  const [mtRez, setMtRez] = useState([])
  const [datum, setDatum] = useState(() => new Date().toISOString().slice(0, 10))
  const [radi, setRadi] = useState(false)
  const [poruka, setPoruka] = useState('')

  useEffect(() => {
    if (!otv) return
    api.arossIzdatnicaPriprema(nalogId).then((d) => { setPrip(d); if (d && d.mjesto_troska) setMt(d.mjesto_troska) }).catch((e) => naGresku(e.message))
    if (skl.length === 0) api.arossSkladistaPopis().then((d) => {
      setSkl(d || [])
      // Zadano: skladište „Roba" (dijelovi), ako postoji.
      const roba = (d || []).find((s) => (s.naziv || '').toLowerCase() === 'roba')
      if (roba && !sklId) setSklId(String(roba.sifra))
    }).catch(() => {})
  }, [otv, nalogId])

  const traziMt = async (v) => {
    setMtQ(v)
    if (!v.trim()) return setMtRez([])
    try { setMtRez(await api.arossMjestaTroska(v)) } catch { setMtRez([]) }
  }
  const posalji = async () => {
    if (!sklId) return naGresku('Odaberi skladište.')
    if (!mt) return naGresku('Odaberi mjesto troška (vozilo).')
    setRadi(true); setPoruka('')
    try {
      const r = await api.arossPosaljiIzdatnicu({ nalog_id: nalogId, sifra_skladista: Number(sklId), sifra_mjesta_troska: mt.sifra, datum })
      setPoruka(`✓ Poslano u Apross — izdatnica #${r.erp_broj_izdatnice}${r.erp_mjesto_troska ? ' · ' + r.erp_mjesto_troska : ''}`)
      setOtv(false); onPoslano && onPoslano()
    } catch (e) { naGresku(e.message) } finally { setRadi(false) }
  }

  return (
    <div style={{ marginTop: 10, borderTop: '1px solid var(--line, #eee)', paddingTop: 8 }}>
      {poruka && <div className="meta" style={{ color: 'var(--zelena, green)', marginBottom: 6 }}>{poruka}</div>}
      <div style={{ cursor: 'pointer', fontWeight: 700 }} onClick={() => setOtv(!otv)}>📤 Pošalji u Apross ({brojNeposlanih}) {otv ? '▾' : '▸'}</div>
      {otv && (
        <div style={{ marginTop: 8 }}>
          {prip && !prip.povezano && <p className="meta" style={{ color: 'var(--crvena)' }}>Apross nije povezan (Šifrarnik → Integracije).</p>}
          {prip && prip.bez_sifre > 0 && <p className="meta">{prip.bez_sifre} stavki nema Apross šifru — one se ne šalju.</p>}
          <label className="meta">Skladište</label>
          <select value={sklId} onChange={(e) => setSklId(e.target.value)} style={{ width: '100%', marginBottom: 8 }}>
            <option value="">— odaberi skladište —</option>
            {skl.map((s) => <option key={s.sifra} value={s.sifra}>{s.naziv}</option>)}
          </select>
          <label className="meta">Mjesto troška (vozilo)</label>
          {mt
            ? <div style={{ marginBottom: 8 }}><b>GB {mt.sifra} · {mt.naziv}</b>{mt.sektor ? <span className="meta"> · {mt.sektor}</span> : ''} <span className="x" style={{ cursor: 'pointer', marginLeft: 6 }} onClick={() => { setMt(null); setMtQ('') }}>promijeni</span></div>
            : (
              <div style={{ position: 'relative', marginBottom: 8 }}>
                {prip && prip.povezano && !prip.mjesto_troska && <p className="meta" style={{ color: 'var(--crvena)', margin: '0 0 4px' }}>{prip.gb ? `GB ${prip.gb}` : 'Vozilo'} nije pronađen među mjestima troška u Aprossu — odaberi ručno.</p>}
                <input value={mtQ} placeholder="traži GB ili registraciju…" onChange={(e) => traziMt(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} />
                {mtRez.length > 0 && (
                  <div style={{ position: 'absolute', zIndex: 20, background: 'var(--karta, #fff)', border: '1px solid var(--line, #ccc)', borderRadius: 8, width: '100%', maxHeight: 200, overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,.12)' }}>
                    {mtRez.map((m) => (
                      <div key={m.sifra} onClick={() => { setMt(m); setMtRez([]) }} style={{ padding: '6px 8px', cursor: 'pointer', borderTop: '1px solid var(--line, #eee)', fontSize: 13 }}>
                        <b>GB {m.sifra}</b> · {m.naziv}{m.sektor ? ` · ${m.sektor}` : ''}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          <label className="meta">Datum</label>
          <input type="date" value={datum} onChange={(e) => setDatum(e.target.value)} style={{ width: '100%', boxSizing: 'border-box', marginBottom: 8 }} />
          <button className="btn" disabled={radi || !sklId || !mt} onClick={posalji}>{radi ? 'Šaljem…' : '📤 Pošalji izdatnicu'}</button>
          <p className="meta" style={{ marginBottom: 0 }}>Svi neposlani dijelovi idu kao jedna izdatnica; Apross vraća broj, a poslane stavke se više ne mogu brisati.</p>
        </div>
      )}
    </div>
  )
}
