import { Fragment, useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import {
  Bedz, KategorijaPicker, MikrofonGumb, Spinner, datum, datumVrijeme, voziloLabel,
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
  const [params] = useSearchParams()
  const spojeno = params.get('spojeno') === '1'
  const { korisnik } = useAuth()
  const { t } = useT()
  const [n, setN] = useState(null)
  const [greska, setGreska] = useState('')
  const [radnici, setRadnici] = useState([])

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
        <div className="uspjeh">{t('nalog.spojeno')}</div>
      )}
      <div className="karta">
        <div className="naslov-red">
          <h3>{n.naslov}</h3>
          <Bedz vrsta={n.status} tekst={t('status.' + n.status)} />
        </div>
        <p className="meta">🚚 {voziloLabel(n.vozilo)}</p>
        {n.voditelj && <p className="meta">🧑‍🔧 {t('nalog.voditelj')}: <strong>{n.voditelj.ime}</strong></p>}
        {n.vozac && <p className="meta">🚛 {t('nalog.vozac')}: <strong>{n.vozac.ime}</strong></p>}
        {n.rok && <p className="meta">📅 {t('nalog.rok')}: <strong>{datum(n.rok)}</strong></p>}
        {n.opis && <p style={{ margin: '12px 0', whiteSpace: 'pre-wrap' }}>{n.opis}</p>}
        <p className="meta">{t('nalog.kreirao')}: <strong>{n.kreirao?.ime}</strong> · {datumVrijeme(n.kreiran)}</p>
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
      <Operacije nalog={n} radnici={radnici} ucitaj={ucitaj} naGresku={setGreska} jeVoditelj={korisnik.uloga === 'voditelj'} />
    </Layout>
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

function OperacijaBlok({ nalog, op, radnici, wrap, ucitaj, naGresku, sada, jeVoditelj }) {
  const { t } = useT()
  const [dodaje, setDodaje] = useState(false)
  return (
    <div className="op2">
      <div className="op2-kat">
        <span className="op2-ime">{op.kategorija}</span>
        {jeVoditelj && <span className="op2-plus" onClick={() => setDodaje((v) => !v)}>＋</span>}
        {jeVoditelj && <span className="x" onClick={() => wrap(api.obrisiOperaciju(nalog.id, op.id))}>×</span>}
      </div>
      <div className="op2-kat-r" />
      {op.zadaci.map((z) => {
        const radi = !!z.zapoceto
        const osnova = z.utroseno_sek || 0
        const proteklo = radi ? osnova + Math.max(0, (sada - msVremena(z.zapoceto)) / 1000) : osnova
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
              {jeVoditelj ? (
                <select
                  className="rad-select"
                  value={z.zaduzeni?.id || ''}
                  onChange={(e) => wrap(api.azurirajZadatak(nalog.id, z.id, { zaduzeni_id: e.target.value ? Number(e.target.value) : null }))}
                >
                  <option value="">—</option>
                  {radnici.map((r) => <option key={r.id} value={r.id}>{r.ime}</option>)}
                </select>
              ) : (
                <span className="rad-tekst">{z.zaduzeni?.ime || '—'}</span>
              )}
            </div>
            <div className="op2-mj">
              {!z.gotovo && (
                <button
                  className={'mj-btn' + (radi ? ' radi' : '')}
                  onClick={() => wrap(api.zadatakMjerac(nalog.id, z.id, radi ? 'stop' : 'start'))}
                  title={radi ? t('op.mjeracPauza') : t('op.mjeracStart')}
                >
                  {radi ? '⏸' : '▶'} <span className="mj-vrijeme">{trajanje(proteklo)}</span>
                </button>
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
