import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api, medijUrl } from '../api'
import { Spinner, datum } from '../ui'
import { useT } from '../i18n'

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
  useEffect(() => {
    const u = () => api.nadzor().then(setNalozi).catch((e) => setGreska(e.message))
    u()
    const t = setInterval(u, 15000)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    const t = setInterval(() => setSada(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  return { nalozi, greska, sada }
}

// --- Glavni izbornik: tablica tekućih radova (aktivni mjerači) ---------------
export function GlavniIzbornik() {
  const { t } = useT()
  const nav = useNavigate()
  const { nalozi, greska, sada } = useNadzor()

  if (greska) return <Layout naslov={t('nadzor.izbornik')}><div className="greska">{greska}</div></Layout>
  if (!nalozi) return <Layout naslov={t('nadzor.izbornik')}><Spinner /></Layout>

  const tekuci = []
  nalozi.forEach((n) => n.operacije.forEach((op) => op.zadaci.forEach((z) => {
    if (z.zapoceto) tekuci.push({ n, op, z })
  })))
  tekuci.sort((a, b) => msVremena(a.z.zapoceto) - msVremena(b.z.zapoceto))

  return (
    <Layout naslov={t('nadzor.izbornik')}>
      <div className="sekcija-naslov">{t('nadzor.tekuci')} <span className="nad-broj">{tekuci.length}</span></div>
      {tekuci.length === 0 ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>{t('nadzor.nemaTekucih')}</p></div>
      ) : (
        <div className="op-tablica" style={{ overflowX: 'auto' }}>
          <div className="tr-head">
            <div>{t('nadzor.vozilo')}</div><div>{t('nadzor.radnik')}</div>
            <div>{t('nadzor.operacija')}</div><div>{t('nadzor.trajanje')}</div>
          </div>
          {tekuci.map(({ n, op, z }) => (
            <div className="tr-red" key={z.id} onClick={() => nav(`/nalozi/${n.id}`)}>
              <div className="tr-voz">{n.vozilo?.gb}</div>
              <div className="tr-radnik">{radniciZadatka(z).map((r) => r.ime).join(', ') || '—'}</div>
              <div className="tr-oper"><span className="tr-op">{op.kategorija}:</span> {z.opis}</div>
              <div className="tr-traj">{trajanjeDugo(proteklo(z, sada))}</div>
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
  const uRadu = nalozi.filter((n) => n.status === 'u_radu')

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
                {radi && <span className="nad-timer">{trajanje(proteklo(z, sada))}</span>}
              </div>
            </div>
          )
        }))}
      </div>
    </div>
  )
}
