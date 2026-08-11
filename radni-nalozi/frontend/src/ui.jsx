// Zajedničke oznake, prijevodi i male komponente.

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

// Predefinirane kategorije operacija (voditelj može dodati i vlastitu)
export const KATEGORIJE = ['Motor', 'Pneumatika', 'Bojanje', 'Elektrika', 'Kočnice', 'Razno']

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
