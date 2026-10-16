import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import { Bedz, MikrofonGumb, Prazno, Spinner, datum, useAutoOsvjezi, voziloLabel } from '../ui'

// bez kvačica + mala slova — pretraga neosjetljiva na dijakritike
const _norm = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')

const FILTERI = [
  { k: '', lk: 'filter.sve' },
  { k: 'otvoren', lk: 'filter.otvoreni' },
  { k: 'u_radu', lk: 'filter.uradu' },
  { k: 'gotov', lk: 'filter.gotovi' },
  { k: 'zatvoren', lk: 'filter.zatvoreni' },
]

// Životni ciklus naloga kao razine; „čeka dijelove" ide uz „u radu".
const RAZINA = { otvoren: 1, u_radu: 2, ceka_dijelove: 2, gotov: 3, zatvoren: 4 }
const RAZINA_FILTERA = { otvoren: 1, u_radu: 2, gotov: 3, zatvoren: 4 }

export default function Nalozi() {
  const { korisnik } = useAuth()
  const { t } = useT()
  const nav = useNavigate()
  const [lista, setLista] = useState(null)
  const [filter, setFilter] = useState('')
  const [samo, setSamo] = useState(false) // kvačica: samo odabrani status (bez nje = kumulativno)
  const [q, setQ] = useState('')
  const [greska, setGreska] = useState('')
  const [brisi, setBrisi] = useState(null) // nalog koji se potvrđuje za brisanje

  const jeVoditelj = korisnik.uloga === 'voditelj'
  const timerRef = useRef(null)
  const dugiRef = useRef(false)

  // Dohvati SVE naloge jednom; filtriranje i brojači idu na klijentu.
  const ucitaj = () => {
    setLista(null)
    api.nalozi('').then(setLista).catch((e) => setGreska(e.message))
  }
  useEffect(() => { ucitaj() }, [])
  // Tiho osvježavanje (bez spinnera) svakih 20 s i na povratak u aplikaciju.
  useAutoOsvjezi(() => api.nalozi('').then(setLista).catch(() => {}))

  // Broj naloga za pojedini čip (u_radu uključuje i „čeka dijelove").
  const brojZa = (k) => {
    if (!lista) return 0
    if (k === '') return lista.length
    return lista.filter((n) => RAZINA[n.status] === RAZINA_FILTERA[k]).length
  }
  // Prolazi li nalog kroz odabrani status-filter (kumulativno ili „samo").
  const poStatusu = (n) => {
    if (!filter) return true
    const sel = RAZINA_FILTERA[filter]
    const r = RAZINA[n.status]
    return samo ? r === sel : r <= sel
  }

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

  const nq = _norm(q.trim())
  const prikazana = !lista ? null : lista.filter((n) =>
    poStatusu(n) && (!nq || _norm(
      `${n.broj} ${n.naslov} ${n.vozilo?.gb || ''} ${n.vozilo?.registracija || ''} `
      + `${n.vozilo?.marka || ''} ${n.vozilo?.model || ''} ${n.voditelj?.ime || ''} ${n.vozac?.ime || ''}`
    ).includes(nq)))

  return (
    <Layout naslov={naslov}>
      <div className="polje-mik" style={{ marginBottom: 8 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('nalozi.trazi')} />
        <MikrofonGumb naslov={t('nalozi.trazi')} onTekst={(tekst) => setQ(tekst)} />
      </div>
      <div className="chips-red">
        <div className="chips">
          {FILTERI.map((f) => (
            <span key={f.k} className={`chip ${filter === f.k ? 'akt' : ''}`} onClick={() => setFilter(f.k)}>
              {t(f.lk)}{lista ? <b className="chip-br"> {brojZa(f.k)}</b> : null}
            </span>
          ))}
        </div>
        <label className="samo-tgl" title={t('filter.samoHint')}>
          <input type="checkbox" checked={samo} onChange={(e) => setSamo(e.target.checked)} />
          {t('filter.samo')}
        </label>
      </div>

      {greska && <div className="greska">{greska}</div>}
      {jeVoditelj && lista?.length > 0 && (
        <p className="meta" style={{ marginTop: 0 }}>{t('nalozi.savjetBrisi')}</p>
      )}
      {lista === null ? (
        <Spinner />
      ) : lista.length === 0 ? (
        <Prazno emo="🔧" tekst={t('nalozi.prazno')} />
      ) : prikazana.length === 0 ? (
        <div className="karta"><p className="meta" style={{ margin: 0 }}>
          {q.trim() ? t('sif.nemaRezultata', { q: q.trim() }) : t('nalozi.prazno')}
        </p></div>
      ) : (
        prikazana.map((n) => (
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
