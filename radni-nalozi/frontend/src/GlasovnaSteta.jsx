import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { GOVOR_JEZIK, useT } from './i18n'

// Normalizacija GB-a za usporedbu (makni sve osim slova/brojki).
const norm = (s) => (s || '').toString().toLowerCase().replace(/[^a-z0-9čćžšđ]/gi, '')
const digits = (s) => (s || '').toString().replace(/\D/g, '')

function nadjiVozilo(vozila, gb) {
  if (!gb) return null
  const n = norm(gb)
  const d = digits(gb)
  return (
    vozila.find((v) => norm(v.gb) === n) ||
    (d && vozila.find((v) => digits(v.gb) === d)) ||
    null
  )
}

function nadjiOsobu(popis, ime) {
  if (!ime) return null
  const t = ime.trim().toLowerCase()
  return (
    popis.find((o) => o.ime.toLowerCase() === t) ||
    popis.find((o) => o.ime.toLowerCase().includes(t) || t.includes(o.ime.toLowerCase())) ||
    null
  )
}

// Glasovni (AI) unos štete — izgovori cijelu štetu, AI izvuče kamion, vozača i opis.
export default function GlasovnaSteta({ vozila, vozaci, onPopuni, onZatvori }) {
  const { t, jezik } = useT()
  const [tekst, setTekst] = useState('')
  const [slusa, setSlusa] = useState(false)
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const recRef = useRef(null)
  const accRef = useRef('')
  const sessRef = useRef('')
  const zeliRef = useRef(false)

  const Podrzano = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)

  // Kratka sesija (continuous=false) koja se sama ponovno pokreće dok slušamo.
  const pokreniSesiju = () => {
    const R = window.SpeechRecognition || window.webkitSpeechRecognition
    const rec = new R()
    rec.lang = GOVOR_JEZIK[jezik] || 'hr-HR'
    rec.continuous = false
    rec.interimResults = true
    sessRef.current = ''
    rec.onresult = (e) => {
      let s = ''
      for (let i = 0; i < e.results.length; i++) s += e.results[i][0].transcript + ' '
      sessRef.current = s.trim()
      setTekst((accRef.current + ' ' + sessRef.current).replace(/\s+/g, ' ').trim())
    }
    rec.onerror = (ev) => {
      if (ev && (ev.error === 'not-allowed' || ev.error === 'service-not-allowed')) {
        zeliRef.current = false
        setGreska('Mikrofon nije dopušten. Dopusti pristup mikrofonu u pregledniku.')
      }
    }
    rec.onend = () => {
      if (sessRef.current) {
        accRef.current = (accRef.current + ' ' + sessRef.current).replace(/\s+/g, ' ').trim()
        sessRef.current = ''
      }
      if (zeliRef.current) pokreniSesiju()
      else setSlusa(false)
    }
    recRef.current = rec
    try { rec.start() } catch (_) { /* ignore */ }
  }

  const pokreni = () => {
    if (!Podrzano) return
    if (slusa) { zeliRef.current = false; recRef.current && recRef.current.stop(); return }
    accRef.current = tekst ? tekst.trim() : ''
    zeliRef.current = true
    setSlusa(true)
    pokreniSesiju()
  }

  useEffect(() => {
    if (Podrzano) pokreni()
    return () => { zeliRef.current = false; try { recRef.current && recRef.current.stop() } catch (_) {} }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const popuni = async () => {
    if (!tekst.trim()) return
    setGreska(''); setRadi(true)
    zeliRef.current = false
    try { recRef.current && recRef.current.stop() } catch (_) {}
    try {
      const r = await api.glasovniParseStete(tekst, vozaci.map((v) => v.ime))
      const vozilo = nadjiVozilo(vozila, r.vozilo_gb)
      const vozac = nadjiOsobu(vozaci, r.vozac)
      onPopuni({
        vozilo,
        vozacId: vozac ? String(vozac.id) : '',
        opis: r.opis || '',
        napomene: [
          r.vozilo_gb && !vozilo ? t('glas.kamionNijeNadjen', { gb: r.vozilo_gb }) : '',
          r.vozac && !vozac ? t('glas.vozacNijePrepoznat', { ime: r.vozac }) : '',
        ].filter(Boolean),
      })
    } catch (e) {
      setGreska(e.message)
      setRadi(false)
    }
  }

  return (
    <div className="sheet-bg" onClick={onZatvori}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{t('glas.naslovSteta')}</h3>
        <p className="meta" style={{ marginTop: 0 }}>{t('glas.primjerSteta')}</p>
        {greska && <div className="greska">{greska}</div>}

        <textarea
          value={tekst}
          onChange={(e) => setTekst(e.target.value)}
          placeholder={Podrzano ? t('glas.ph') : t('glas.phNema')}
          style={{ minHeight: 120 }}
        />

        {Podrzano && (
          <button className={`btn ${slusa ? 'opasno' : 'sekund'}`} onClick={pokreni} style={{ marginTop: 8 }}>
            {slusa ? t('glas.zaustavi') : t('glas.nastavi')}
          </button>
        )}

        <button className="btn" onClick={popuni} disabled={radi || !tekst.trim()} style={{ marginTop: 8 }}>
          {radi ? t('glas.obradjujem') : t('glas.popuniStetu')}
        </button>
        <button className="btn sekund" onClick={onZatvori} style={{ marginTop: 8 }}>{t('common.odustani')}</button>
      </div>
    </div>
  )
}
