import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { KATEGORIJE } from './ui'

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

export default function GlasovniUnos({ vozila, voditelji, vozaci, onPopuni, onZatvori }) {
  const [tekst, setTekst] = useState('')
  const [slusa, setSlusa] = useState(false)
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const recRef = useRef(null)
  const baseRef = useRef('')
  const finalRef = useRef('')

  const Podrzano = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)

  const pokreni = () => {
    if (!Podrzano) return
    if (slusa) { recRef.current && recRef.current.stop(); return }
    const R = window.SpeechRecognition || window.webkitSpeechRecognition
    const rec = new R()
    rec.lang = 'hr-HR'
    rec.continuous = true
    rec.interimResults = true
    baseRef.current = tekst ? tekst.trim() + ' ' : ''
    finalRef.current = ''
    // Obrađuj SAMO nove rezultate (od resultIndex); finalne akumuliraj, međurezultat
    // pokaži privremeno — inače se tekst gomila i ponavlja.
    rec.onresult = (e) => {
      let interim = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        if (res.isFinal) finalRef.current += res[0].transcript + ' '
        else interim += res[0].transcript
      }
      setTekst((baseRef.current + finalRef.current + interim).replace(/\s+/g, ' ').trimStart())
    }
    rec.onerror = () => setSlusa(false)
    rec.onend = () => setSlusa(false)
    recRef.current = rec
    setSlusa(true)
    try { rec.start() } catch (_) { setSlusa(false) }
  }

  // Automatski počni slušati kad se otvori
  useEffect(() => {
    if (Podrzano) pokreni()
    return () => { try { recRef.current && recRef.current.stop() } catch (_) {} }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const popuni = async () => {
    if (!tekst.trim()) return
    setGreska(''); setRadi(true)
    try { recRef.current && recRef.current.stop() } catch (_) {}
    try {
      const r = await api.glasovniParse(
        tekst,
        KATEGORIJE,
        voditelji.map((v) => v.ime),
        vozaci.map((v) => v.ime),
      )
      const vozilo = nadjiVozilo(vozila, r.vozilo_gb)
      const voditelj = nadjiOsobu(voditelji, r.voditelj)
      const vozac = nadjiOsobu(vozaci, r.vozac)
      const operacije = (r.operacije || []).map((o) => ({
        kategorija: o.kategorija,
        zadaci: o.zadaci && o.zadaci.length ? o.zadaci : [''],
      }))
      onPopuni({
        vozilo,
        voditeljId: voditelj ? String(voditelj.id) : '',
        vozacId: vozac ? String(vozac.id) : '',
        operacije,
        napomene: [
          r.vozilo_gb && !vozilo ? `Kamion „${r.vozilo_gb}” nije pronađen — odaberi ručno.` : '',
          r.voditelj && !voditelj ? `Voditelj „${r.voditelj}” nije prepoznat.` : '',
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
        <h3 style={{ marginTop: 0 }}>🎙️ Glasovni unos naloga</h3>
        <p className="meta" style={{ marginTop: 0 }}>
          Reci npr.: <em>„Kamion 21, voditelj Marko, motor – zamjena ulja i filtera; kočnice – zamjena pločica.”</em>
        </p>
        {greska && <div className="greska">{greska}</div>}

        <textarea
          value={tekst}
          onChange={(e) => setTekst(e.target.value)}
          placeholder={Podrzano ? 'Ovdje se ispisuje što govoriš…' : 'Tvoj preglednik ne podržava govor — možeš upisati tekst.'}
          style={{ minHeight: 120 }}
        />

        {Podrzano && (
          <button className={`btn ${slusa ? 'opasno' : 'sekund'}`} onClick={pokreni} style={{ marginTop: 8 }}>
            {slusa ? '⏹ Zaustavi slušanje' : '🎤 Nastavi govoriti'}
          </button>
        )}

        <button className="btn" onClick={popuni} disabled={radi || !tekst.trim()} style={{ marginTop: 8 }}>
          {radi ? 'Obrađujem…' : '✨ Popuni nalog'}
        </button>
        <button className="btn sekund" onClick={onZatvori} style={{ marginTop: 8 }}>Odustani</button>
      </div>
    </div>
  )
}
