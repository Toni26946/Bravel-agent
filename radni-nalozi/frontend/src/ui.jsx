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
  'Elektrika 2', 'KOČNICE 1', 'BOČNA ZAŠTITA I BRANIK 2', 'DIJELOVI DIZALICE 2', 'DIJELOVI OVJESA 2', 'ŠASIJA 2',
  'KOTAČI 2', 'DIJELOVI OVJESA 3', 'ŠASIJA 3', 'BOČNA ZAŠTITA', 'DIJELOVI OVJESA, GIBNJEVI, ZRAČNI JASTUCI 2', 'RAZNO 3',
  'HLADNJAK VODE I INTERCOOLER', 'REZERVOARI', 'Odlazak na teren', 'KONTROLA KOČNICA I KLOBNI', 'MOTOR 2', 'TEREN Bad Soden',
  'AUSPUH-ISPUŠNI SUSTAV', 'AD-BLUE', 'POSLOVOĐE', 'KONTROLA ISPRAVNOSTI', 'RAZNO 4', 'ABS/EBS',
  'akumulatori', 'RETROVIZORI', 'REGISTRACIJA', 'vulkanizer', 'RAD U RADIONI VRBOVEC', 'GETRIBA DEMONTAŽA/MONTAŽA',
  'LJEPLJENJE BROJEVA', 'DIJELOVI DIZALICE 3', 'PNEUMATIKA 2', 'KONTROLA DPF FILTERA', 'SOBA 1', 'SOBA 2',
  'SOBA 3', 'SOBA 4', 'SOBA 5', 'SOBA 6', 'SOBA 7', 'SOBA 8', 'SOBA 9',
  'ČIŠĆENJE BREZANI', 'ČIŠĆENJE SOBE U PROLAZU', 'ČIŠĆENJE GREDA', 'ČIŠĆENJE CELINE', 'ČIŠĆENJE RADIONA',
  'ČIŠĆENJE UPRAVA', 'ČIŠĆENJE CENTAR STAN', 'OBILAZAK OKO OBJEKTA', 'PRANJE VEŠA', 'OPIK', 'KAMERE',
  'ČIŠĆENJE KAMIONA', 'ČIŠĆENJE PARKINGA STROJEM', 'ČIŠĆENJE MALOG AUTA', 'SOBA 10', 'SOBA 11', 'SOBA 12',
  'KONTROLA KOMPRESORA, TE PO POTREBI REPARATURA', 'ELEKTRIKA 3', 'RADOVI RADIONA OPIK', 'CJELOKUPNA KONTROLA', 'PRANJE VOZILA', 'ŠPUR',
  'ČIŠĆENJE I ZBRINJAVANJE MATERIJALA NAKON ZAVRŠETKA', 'INJEKTORI', 'Gume', 'Kuka za vuču prikolice', 'Pranje hladnjaka',
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
