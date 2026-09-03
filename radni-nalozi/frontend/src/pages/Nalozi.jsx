import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import { Bedz, Prazno, Spinner, datum, useAutoOsvjezi, voziloLabel } from '../ui'

const FILTERI = [
  { k: '', lk: 'filter.sve' },
  { k: 'otvoren', lk: 'filter.otvoreni' },
  { k: 'u_radu', lk: 'filter.uradu' },
  { k: 'gotov', lk: 'filter.gotovi' },
]

export default function Nalozi() {
  const { korisnik } = useAuth()
  const { t } = useT()
  const nav = useNavigate()
  const [lista, setLista] = useState(null)
  const [filter, setFilter] = useState('')
  const [greska, setGreska] = useState('')
  const [brisi, setBrisi] = useState(null) // nalog koji se potvrđuje za brisanje

  const jeVoditelj = korisnik.uloga === 'voditelj'
  const timerRef = useRef(null)
  const dugiRef = useRef(false)

  const ucitaj = () => {
    setLista(null)
    api.nalozi(filter).then(setLista).catch((e) => setGreska(e.message))
  }
  useEffect(() => { ucitaj() }, [filter])
  // Tiho osvježavanje (bez spinnera) svakih 20 s i na povratak u aplikaciju.
  useAutoOsvjezi(() => api.nalozi(filter).then(setLista).catch(() => {}))

  // Dugi pritisak (samo voditelj) → ponudi brisanje
  const start = (n) => {
    if (!jeVoditelj) return
    dugiRef.current = false
    timerRef.current = setTimeout(() => {
      dugiRef.current = true
      if (navigator.vibrate) navigator.vibrate(30)
      setBrisi(n)
    }, 500)
  }
  const kraj = () => clearTimeout(timerRef.current)
  const klik = (n) => {
    if (dugiRef.current) { dugiRef.current = false; return } // bio je dugi pritisak — ne otvaraj
    nav(`/nalozi/${n.id}`)
  }

  const obrisi = async () => {
    try {
      await api.obrisiNalog(brisi.id)
      setBrisi(null)
      ucitaj()
    } catch (e) {
      setGreska(e.message)
      setBrisi(null)
    }
  }

  const naslov = korisnik.uloga === 'radnik' ? t('nalozi.title.radnik') : t('nalozi.title.ostalo')

  return (
    <Layout naslov={naslov}>
      <div className="chips">
        {FILTERI.map((f) => (
          <span key={f.k} className={`chip ${filter === f.k ? 'akt' : ''}`} onClick={() => setFilter(f.k)}>{t(f.lk)}</span>
        ))}
      </div>

      {greska && <div className="greska">{greska}</div>}
      {jeVoditelj && lista?.length > 0 && (
        <p className="meta" style={{ marginTop: 0 }}>{t('nalozi.savjetBrisi')}</p>
      )}
      {lista === null ? (
        <Spinner />
      ) : lista.length === 0 ? (
        <Prazno emo="🔧" tekst={t('nalozi.prazno')} />
      ) : (
        lista.map((n) => (
          <div
            key={n.id}
            className="karta klik"
            onClick={() => klik(n)}
            onTouchStart={() => start(n)}
            onTouchEnd={kraj}
            onTouchMove={kraj}
            onMouseDown={() => start(n)}
            onMouseUp={kraj}
            onMouseLeave={kraj}
            onContextMenu={(e) => { if (jeVoditelj) { e.preventDefault(); setBrisi(n) } }}
          >
            <div className="naslov-red">
              <div>
                <p className="meta" style={{ margin: 0 }}>{n.broj}</p>
                <h3>{n.naslov}</h3>
              </div>
              <Bedz vrsta={n.status} tekst={t('status.' + n.status)} />
            </div>
            <p className="meta">🚚 {voziloLabel(n.vozilo)}</p>
            {n.rok && <p className="meta">📅 {t('nalozi.rok')}: {datum(n.rok)}</p>}
            {(n.voditelj || n.vozac) && (
              <p className="meta">
                {n.voditelj && <>🧑‍🔧 {n.voditelj.ime}</>}
                {n.vozac && <> &nbsp; 🚛 {n.vozac.ime}</>}
              </p>
            )}
          </div>
        ))
      )}

      {/* Potvrda brisanja */}
      {brisi && (
        <div className="sheet-bg" onClick={() => setBrisi(null)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>{t('nalozi.obrisatiNalog')}</h3>
            <p className="meta">{brisi.broj} · {brisi.naslov}</p>
            <p className="meta" style={{ marginBottom: 16 }}>🚚 {voziloLabel(brisi.vozilo)} — {t('nalozi.brisanjeTrajno')}</p>
            <button className="btn opasno" onClick={obrisi}>{t('nalozi.obrisiNalog')}</button>
            <button className="btn sekund" onClick={() => setBrisi(null)} style={{ marginTop: 8 }}>{t('common.odustani')}</button>
          </div>
        </div>
      )}
    </Layout>
  )
}
