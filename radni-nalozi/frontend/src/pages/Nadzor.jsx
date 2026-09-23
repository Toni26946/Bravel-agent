import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api, medijUrl } from '../api'
import { Spinner, datum } from '../ui'
import { useT } from '../i18n'
import { useAuth } from '../auth'

function msVremena(s) {
  if (!s) return 0
  const imaZonu = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(s)
  return new Date(imaZonu ? s : s + 'Z').getTime()
}
function trajanje(sek) {
  const s = Math.max(0, Math.floor(sek))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60
  const p = (x) => String(x).padStart(2, '0')
  return h > 0 ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`
}
function trajanjeDugo(sek) {
  const s = Math.max(0, Math.floor(sek))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
  return h > 0 ? `${h} h ${m} min` : `${m} min`
}
function proteklo(z, sada) {
  const osnova = z.utroseno_sek || 0
  return z.zapoceto ? osnova + Math.max(0, (sada - msVremena(z.zapoceto)) / 1000) : osnova
}
// Vrijeme od zadnje prijave (trenutna sesija) — ne ukupno nakupljeno.
function sesija(z, sada) {
  return z.zapoceto ? Math.max(0, (sada - msVremena(z.zapoceto)) / 1000) : 0
}
function radiSe(n) {
  return n.operacije.some((op) => op.zadaci.some((z) => z.zapoceto))
}
// "Midhun Hari Ankudy" -> "Midhun Hari A."
function kratkoIme(ime) {
  const d = ime.trim().split(/\s+/)
  if (d.length <= 1) return ime
  return d.slice(0, -1).join(' ') + ' ' + d[d.length - 1][0] + '.'
}
// Popis radnika zadatka (podržava novi popis 'radnici' i stari 'zaduzeni').
function radniciZadatka(z) {
  if (z.radnici && z.radnici.length) return z.radnici
  return z.zaduzeni ? [z.zaduzeni] : []
}

// Zajednički dohvat aktivnih naloga + živi sat.
function useNadzor() {
  const [nalozi, setNalozi] = useState(null)
  const [greska, setGreska] = useState('')
  const [sada, setSada] = useState(Date.now())
  const osvjezi = useCallback(() => api.nadzor().then(setNalozi).catch((e) => setGreska(e.message)), [])
  useEffect(() => {
    osvjezi()
    const t = setInterval(osvjezi, 15000)
    return () => clearInterval(t)
  }, [osvjezi])
  useEffect(() => {
    const t = setInterval(() => setSada(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  return { nalozi, greska, sada, osvjezi }
}

// Trenutna (danas aktivna) odsutnost radnika ili null (istekla se ne broji).
function odsutnostSada(r) {
  if (!r.odsutnost_vrsta) return null
  const danas = new Date().toISOString().slice(0, 10)
  if (r.odsutnost_do && danas > r.odsutnost_do) return null
  return r.odsutnost_vrsta
}

// Oblačić radnika s padajućim izbornikom: dostupan / godišnji / bolovanje (+ razdoblje).
function RadnikChip({ r, onPromjena }) {
  const { t } = useT()
  const [otvoren, setOtvoren] = useState(false)
  const [nacin, setNacin] = useState(null)   // null | 'godisnji' | 'bolovanje'
  const [od, setOd] = useState(r.odsutnost_od || '')
  const [doDat, setDoDat] = useState(r.odsutnost_do || '')
  const [radi, setRadi] = useState(false)
  const status = odsutnostSada(r)

  const spremi = async (vrsta, odV, doV) => {
    setRadi(true)
    try {
      await api.postaviOdsutnost(r.id, { vrsta, od: odV || null, do: doV || null })
      setOtvoren(false); setNacin(null)
      onPromjena()
    } catch (_) { /* tiho */ } finally { setRadi(false) }
  }

  const boja = status === 'godisnji' ? 'go' : status === 'bolovanje' ? 'bo' : ''
  const emo = status === 'godisnji' ? '🌴 ' : status === 'bolovanje' ? '🤒 ' : ''
  const naslov = status && r.odsutnost_do
    ? `${t('ods.' + status)} do ${r.odsutnost_do}` : (status ? t('ods.' + status) : '')

  return (
    <span className="chip-wrap">
      <button type="button" className={'slobodni-chip ' + boja} title={naslov} onClick={() => setOtvoren((o) => !o)}>
        {emo}{r.ime}
      </button>
      {otvoren && (
        <div className="chip-menu">
          {!nacin ? (
            <>
              <button className="cm-opt" disabled={radi} onClick={() => spremi(null)}>✅ {t('ods.dostupan')}</button>
              <button className="cm-opt" onClick={() => setNacin('godisnji')}>🌴 {t('ods.godisnji')}</button>
              <button className="cm-opt" onClick={() => setNacin('bolovanje')}>🤒 {t('ods.bolovanje')}</button>
            </>
          ) : (
            <div className="cm-form">
              <div className="cm-naslov">{t('ods.' + nacin)}</div>
              <label>{t('ods.od')}</label>
              <input type="date" value={od} onChange={(e) => setOd(e.target.value)} />
              <label>{t('ods.do')}</label>
              <input type="date" value={doDat} onChange={(e) => setDoDat(e.target.value)} />
              <div className="btn-red" style={{ marginTop: 8 }}>
                <button className="btn mali" disabled={radi} onClick={() => spremi(nacin, od, doDat)}>{radi ? '…' : t('common.spremi')}</button>
                <button className="btn sekund mali" onClick={() => setNacin(null)}>{t('common.odustani')}</button>
              </div>
            </div>
          )}
        </div>
      )}
    </span>
  )
}

// Voditelj brzo dodaje novog radnika (ime → auto korisničko ime + lozinka za predaju).
function DodajRadnika({ onDodano }) {
  const { t } = useT()
  const [otvoren, setOtvoren] = useState(false)
  const [ime, setIme] = useState('')
  const [lozinka, setLozinka] = useState('radnik123')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const [rezultat, setRezultat] = useState(null)

  const dodaj = async () => {
    if (!ime.trim()) { setGreska(t('radnik.imeObavezno')); return }
    setRadi(true); setGreska('')
    try {
      const r = await api.uvozKorisnika(ime.trim(), 'radnik', lozinka.trim() || 'radnik123')
      if (r.dodano > 0 && r.korisnici?.length) {
        setRezultat({ ...r.korisnici[0], lozinka: r.lozinka })
        setIme(''); onDodano()
      } else {
        setGreska(t('radnik.vecPostoji'))
      }
    } catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }

  if (!otvoren) {
    return <button className="btn sekund mali" onClick={() => { setOtvoren(true); setRezultat(null) }}>➕ {t('radnik.dodaj')}</button>
  }
  return (
    <div className="dodaj-radnik">
      {rezultat ? (
        <div className="dr-ok">
          <div><b>✅ {t('radnik.dodan')}:</b> {rezultat.ime}</div>
          <div className="meta">{t('radnik.korisnicko')}: <b>{rezultat.korisnicko_ime}</b> · {t('radnik.lozinka')}: <b>{rezultat.lozinka}</b></div>
          <div className="btn-red" style={{ marginTop: 6 }}>
            <button className="btn mali" onClick={() => { setRezultat(null) }}>➕ {t('radnik.josJedan')}</button>
            <button className="btn sekund mali" onClick={() => { setOtvoren(false); setRezultat(null) }}>{t('common.zatvori')}</button>
          </div>
        </div>
      ) : (
        <>
          <input className="pretraga-input" placeholder={t('radnik.imePlaceholder')} value={ime} onChange={(e) => setIme(e.target.value)} autoFocus />
          <label className="meta" style={{ display: 'block', margin: '2px 0' }}>{t('radnik.pocLozinka')}</label>
          <input className="pretraga-input" value={lozinka} onChange={(e) => setLozinka(e.target.value)} />
          {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
          <div className="btn-red" style={{ marginTop: 4 }}>
            <button className="btn mali" disabled={radi} onClick={dodaj}>{radi ? '…' : t('radnik.spremiDodaj')}</button>
            <button className="btn sekund mali" disabled={radi} onClick={() => { setOtvoren(false); setGreska('') }}>{t('common.odustani')}</button>
          </div>
        </>
      )}
    </div>
  )
}

// --- Glavni izbornik: tablica tekućih radova (aktivni mjerači) ---------------
export function GlavniIzbornik() {
  const { t } = useT()
  const nav = useNavigate()
  const { korisnik } = useAuth()
  const { nalozi, greska, sada, osvjezi } = useNadzor()
  const [radiId, setRadiId] = useState(0)
  const [radnici, setRadnici] = useState([])

  const ucitajRadnike = useCallback(() => api.korisnici('radnik').then(setRadnici).catch(() => {}), [])
  useEffect(() => { ucitajRadnike() }, [ucitajRadnike])

  if (greska) return <Layout naslov={t('nadzor.izbornik')}><div className="greska">{greska}</div></Layout>
  if (!nalozi) return <Layout naslov={t('nadzor.izbornik')}><Spinner /></Layout>

  const tekuci = []
  nalozi.forEach((n) => n.operacije.forEach((op) => op.zadaci.forEach((z) => {
    if (z.zapoceto) tekuci.push({ n, op, z })
  })))
  tekuci.sort((a, b) => msVremena(a.z.zapoceto) - msVremena(b.z.zapoceto))

  // "Slobodni" = aktivni serviseri koji trenutno NEMAJU pokrenut mjerač.
  // Prijavljen je onaj tko ima pokrenut mjerač (isti oni koji su u tablici ispod),
  // pa radnici dodijeljeni na pauziranu/nezapočetu operaciju i dalje broje kao slobodni.
  const zauzetiIds = new Set()
  nalozi.forEach((n) => n.operacije.forEach((op) => op.zadaci.forEach((z) => {
    if (z.zapoceto) radniciZadatka(z).forEach((r) => zauzetiIds.add(r.id))
  })))
  const slobodni = radnici
    .filter((r) => r.aktivan !== false && r.prijavljuje_se !== false && !zauzetiIds.has(r.id))
    .sort((a, b) => a.ime.localeCompare(b.ime, 'hr'))

  const odjavi = async (n, z, e) => {
    e.stopPropagation()
    setRadiId(z.id)
    try { await api.odjavaZadatak(n.id, z.id); osvjezi() }
    catch (_) { /* tiho */ } finally { setRadiId(0) }
  }

  return (
    <Layout naslov={t('nadzor.izbornik')}>
      <div className="sekcija-glava">
        <div className="sekcija-naslov" style={{ marginTop: 0 }}>{t('nadzor.slobodni')} ({slobodni.length})</div>
        {korisnik?.uloga === 'voditelj' && <DodajRadnika onDodano={ucitajRadnike} />}
      </div>
      {slobodni.length === 0 ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('nadzor.sviZauzeti')}</p></div>
      ) : (
        <div className="slobodni-grid">
          {slobodni.map((r) => <RadnikChip key={r.id} r={r} onPromjena={ucitajRadnike} />)}
        </div>
      )}
      <div className="sekcija-naslov">{tekuci.length} {t('nadzor.uTijeku')}</div>
      {tekuci.length === 0 ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('nadzor.nemaTekucih')}</p></div>
      ) : (
        <div className="op-tablica" style={{ overflowX: 'auto' }}>
          <div className="tr-head">
            <div>{t('nadzor.vozilo')}</div><div>{t('nadzor.radnik')}</div>
            <div>{t('nadzor.operacija')}</div><div>{t('nadzor.trajanje')}</div><div></div>
          </div>
          {tekuci.map(({ n, op, z }) => (
            <div className="tr-red" key={z.id} onClick={() => nav(`/nalozi/${n.id}`)}>
              <div className="tr-voz">{n.vozilo?.gb}</div>
              <div className="tr-radnik">{radniciZadatka(z).map((r) => r.ime).join(', ') || '—'}</div>
              <div className="tr-oper"><span className="tr-op">{op.kategorija}:</span> {z.opis}</div>
              <div className="tr-traj">{trajanjeDugo(sesija(z, sada))}</div>
              <div className="tr-akcija">
                <button className="btn mali sekund" disabled={radiId === z.id} onClick={(e) => odjavi(n, z, e)}>
                  {radiId === z.id ? '…' : `⏻ ${t('nadzor.odjavi')}`}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Layout>
  )
}

// --- Vozila u radu: kartice po aktivnom nalogu -------------------------------
export function VozilaURadu() {
  const { t } = useT()
  const nav = useNavigate()
  const { nalozi, greska, sada } = useNadzor()

  if (greska) return <Layout naslov={t('nadzor.vozilaURadu')}><div className="greska">{greska}</div></Layout>
  if (!nalozi) return <Layout naslov={t('nadzor.vozilaURadu')}><Spinner /></Layout>

  // Prikaži samo naloge koji su stvarno "u radu" (ne otvorene ni završene).
  // Sortiraj: prvo oni na kojima netko trenutno radi (zeleni), pa ostali.
  const uRadu = nalozi
    .filter((n) => n.status === 'u_radu')
    .sort((a, b) => (radiSe(b) ? 1 : 0) - (radiSe(a) ? 1 : 0))

  return (
    <Layout naslov={t('nadzor.vozilaURadu')}>
      {uRadu.length === 0 ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('nadzor.nemaAktivnih')}</p></div>
      ) : (
        <div className="nad-grid">
          {uRadu.map((n) => (
            <KartaNaloga key={n.id} n={n} sada={sada} onClick={() => nav(`/nalozi/${n.id}`)} />
          ))}
        </div>
      )}
    </Layout>
  )
}

function KartaNaloga({ n, sada, onClick }) {
  const { t } = useT()
  const foto = n.vozilo?.slika || (n.fotografije && n.fotografije[0]?.putanja)
  const aktivan = radiSe(n)
  return (
    <div className={'nad-karta' + (aktivan ? ' radi' : '')} onClick={onClick}>
      <div className="nad-glava">
        <div className="nad-slika">
          {foto ? <img src={medijUrl(foto)} alt={n.vozilo?.gb} /> : <span className="nad-slika-ph">🚚</span>}
        </div>
        <div className="nad-info">
          <div className="nad-gb">{n.vozilo?.gb}</div>
          <div className="nad-meta">{datum(n.kreiran)}</div>
          {n.vozilo?.registracija && <div className="nad-meta">{n.vozilo.registracija}</div>}
          {n.voditelj && <div className="nad-vod">{n.voditelj.ime}</div>}
        </div>
      </div>
      <div className="nad-tijelo">
        <div className="nad-red nad-zaglavlje"><div>{t('nadzor.operacija')}</div><div>{t('nadzor.radnik')}</div></div>
        {n.operacije.length === 0 && <div className="nad-prazno">{t('nadzor.nemaOperacija')}</div>}
        {n.operacije.map((op) => op.zadaci.map((z) => {
          const radi = !!z.zapoceto
          return (
            <div className="nad-red" key={z.id}>
              <div className="nad-posao">
                <span className="nad-op">{op.kategorija}</span>
                {z.opis && <span className={'nad-opis ' + (z.gotovo ? 'ok' : 'nije')}>{z.opis}</span>}
              </div>
              <div className="nad-radnik">
                {radniciZadatka(z).map((r) => <span key={r.id} className="nad-ime">{kratkoIme(r.ime)}</span>)}
                {radi && <span className="nad-timer">{trajanje(sesija(z, sada))}</span>}
              </div>
            </div>
          )
        }))}
      </div>
    </div>
  )
}
