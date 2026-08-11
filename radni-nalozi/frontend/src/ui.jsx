// Zajedničke oznake, prijevodi i male komponente.
import { useState } from 'react'

export const STATUS_NALOG = {
  otvoren: 'Otvoren',
  u_radu: 'U radu',
  ceka_dijelove: 'Čeka dijelove',
  gotov: 'Gotov',
  zatvoren: 'Zatvoren',
}
export const STATUS_PRIJAVA = {
  nova: 'Nova',
  u_obradi: 'U obradi',
  zatvorena: 'Zatvorena',
}
export const PRIORITET = {
  nizak: 'Nizak',
  srednji: 'Srednji',
  visok: 'Visok',
  hitan: 'Hitan',
}
export const HITNOST = {
  niska: 'Niska',
  srednja: 'Srednja',
  visoka: 'Visoka',
}
export const ULOGA = {
  vozac: 'Vozač',
  voditelj: 'Voditelj',
  radnik: 'Radnik',
}

// Predefinirane kategorije operacija (može se utipkati i vlastita)
export const KATEGORIJE = [
  'MOTOR', 'MJENJAČ', 'DIFERENCIJAL', 'PNEUMATIKA', 'ELEKTRIKA', 'KOTAČI',
  'BLATOBRANI 1', 'KOČNICE 2', 'IZRADA HIDRAULIČNIH CRIJEVA', 'SERVIS', 'PODMAZIVANJE', 'NADOGRADNJA',
  'LIMARIJA', 'SUSTAV UPRAVLJANJA', 'KLIMA', 'RETARDER', 'DIJAGNOSTIKA-ELEKTRIKA', 'BRAVARIJA',
  'LIMOVI PODA ŠLEPE', 'BOČNA ZAŠTITA I BRANIK', 'PREDNJA STRANICA', 'ŠASIJA', 'JASTUCI I ŠTICE', 'BOJANJE',
  'GLAVČINE KOTAČA', 'HIDRAULIKA', 'DIJELOVI DIZALICE', 'DIJELOVI OVJESA, GIBNJEVI, ZRAČNI JASTUCI', 'GORIVO', 'GETRIBA',
  'REPARATURA SEDLA, VUČNE KUKE, RUDE', 'MATERIJAL ZA TEREN', 'KOČNICE 3', 'BLATOBRANI 3', 'REPARATURA ČELJUSTI', 'BOJANJE 2',
  'VANJSKI RADOVI', 'PRIJEVOZ VOZILA', 'Teren', 'DIFERENCIJAL 2', 'Škare za dizalice', 'HIDRAULIKA 3',
  'Brzi posmaci jastuka štica', 'WEBASTO I GRIJANJE', 'Razvodnici hidraulični', 'Čišćenje radionice',
  'Prikopčavanje, otkopčavanje, dovažanje i odvažanje', 'RAZNO',
  'Gablec', 'LIMARIJA2', 'LIMARIJA3', 'LIMARIJA4', 'BLATOBRANI 2', 'Blombiranje hidrauličnih ventila',
  'PODEŠAVANJE VENTILA MOTORA', 'HIDRAULIKA 2', 'DIJAGNOSTIKA ELEKTRIKA 2', 'RAZNO 2', 'JASTUCI I ŠTICE 2', 'Bravarija 2',
]

// Pretraživi odabir kategorije (utipkaj za filtriranje; može i vlastita).
export function KategorijaPicker({ onOdaberi, placeholder = 'Dodajte operaciju…' }) {
  const [q, setQ] = useState('')
  const [fokus, setFokus] = useState(false)
  const upit = q.trim().toLowerCase()
  const filt = upit ? KATEGORIJE.filter((k) => k.toLowerCase().includes(upit)) : KATEGORIJE
  const tocna = KATEGORIJE.some((k) => k.toLowerCase() === upit)
  const odaberi = (k) => { onOdaberi(k); setQ(''); setFokus(false) }
  return (
    <div style={{ position: 'relative' }}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setFokus(true)}
        onBlur={() => setTimeout(() => setFokus(false), 150)}
        placeholder={placeholder}
      />
      {fokus && (
        <div className="kat-lista">
          {filt.map((k) => (
            <div key={k} className="kat-opcija" onMouseDown={() => odaberi(k)}>{k}</div>
          ))}
          {q.trim() && !tocna && (
            <div className="kat-opcija kat-custom" onMouseDown={() => odaberi(q.trim())}>＋ Dodaj „{q.trim()}”</div>
          )}
          {filt.length === 0 && !q.trim() && (
            <div className="kat-opcija" style={{ color: 'var(--sivo)' }}>Nema kategorija.</div>
          )}
        </div>
      )}
    </div>
  )
}

export function Bedz({ vrsta, tekst }) {
  return <span className={`bedz b-${vrsta}`}>{tekst}</span>
}

export function Spinner() {
  return (
    <div className="centar">
      <div className="spinner" />
    </div>
  )
}

export function Prazno({ emo = '📭', tekst }) {
  return (
    <div className="prazno">
      <span className="emo">{emo}</span>
      {tekst}
    </div>
  )
}

export function datum(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('hr-HR', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
export function datumVrijeme(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('hr-HR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function voziloLabel(v) {
  if (!v) return '—'
  const dodatak = [v.marka, v.registracija].filter(Boolean).join(' · ')
  return dodatak ? `${v.gb} (${dodatak})` : v.gb
}
