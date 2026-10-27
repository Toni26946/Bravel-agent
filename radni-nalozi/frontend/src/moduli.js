// Katalog modula (kartica izbornika) za uređivanje dopuštenja po korisniku.
// `txt` je ključ prijevoda; `literal:true` znači da je `txt` već gotov tekst.
// Napomena: "/evidencija" (Radno vrijeme) se vodi posebno (samo Marina i Akshay),
// pa nije u ovom katalogu.
export const MODULI = [
  { key: '/plan', ikona: '📋', txt: 'Plan radione', literal: true },
  { key: '/izbornik', ikona: '🗂️', txt: 'tab.izbornik' },
  { key: '/vozila-u-radu', ikona: '🚚', txt: 'tab.vozilaURadu' },
  { key: '/nalozi', ikona: '🔧', txt: 'tab.nalozi' },
  { key: '/izasli', ikona: '🛣️', txt: 'tab.izasli' },
  { key: '/skladiste', ikona: '📦', txt: 'tab.skladiste' },
  { key: '/skladiste/dashboard', ikona: '📊', txt: 'skl.dashboard' },
  { key: '/zaduzenja', ikona: '🧾', txt: 'tab.zaduzenja' },
  { key: '/vozaci', ikona: '🧑‍✈️', txt: 'tab.vozaci' },
  { key: '/radnici', ikona: '👷', txt: 'tab.radnici' },
  { key: '/pregledi', ikona: '🗓️', txt: 'tab.pregledi' },
  { key: '/steta', ikona: '💥', txt: 'tab.steta' },
  { key: '/prijave', ikona: '📋', txt: 'tab.prijave' },
  { key: '/moja-radiona', ikona: '🛠️', txt: 'Moja radiona', literal: true },
  { key: '/moj-ucinak', ikona: '🏆', txt: 'tab.mojUcinak' },
]

// Koji moduli su relevantni (vidljivi po zadanom) za koju ulogu — za prikaz u uređivaču.
export const MODULI_ULOGA = {
  voditelj: ['/izbornik', '/vozila-u-radu', '/nalozi', '/izasli', '/skladiste', '/skladiste/dashboard', '/zaduzenja', '/vozaci', '/radnici', '/pregledi', '/steta'],
  poslovodja: ['/izbornik', '/vozila-u-radu', '/nalozi', '/skladiste', '/skladiste/dashboard', '/zaduzenja', '/vozaci', '/pregledi'],
  skladistar: ['/skladiste', '/skladiste/dashboard'],
  radnik: ['/moja-radiona', '/moj-ucinak', '/nalozi'],
  vozac: ['/prijave'],
}

export function moduliZaUlogu(uloga) {
  const keys = MODULI_ULOGA[uloga] || []
  return MODULI.filter((m) => keys.includes(m.key))
}
