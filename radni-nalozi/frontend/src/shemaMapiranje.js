// Mapiranje kategorija operacija → zone na 3D shemi + izračun statusa zone iz naloga.

// Zone (dijelovi) koje shema poznaje. Ključ → čitljiv naziv.
export const ZONE = {
  kabina: 'Kabina',
  motor: 'Motor i pogon',
  osovine: 'Osovine i ovjes',
  kotaci: 'Kotači i gume',
  kocnice: 'Kočnice',
  sasija: 'Šasija i limarija',
  spremnik: 'Spremnici (gorivo/AdBlue)',
  sedlo: 'Sedlo / vučni sklop',
  hidraulika: 'Hidraulika / nadogradnja',
  elektrika: 'Elektrika i svjetla',
}

// Iz naziva kategorije (velika slova) pogodi zonu. Vraća ključ zone ili null.
export function zonaZaKategoriju(kategorija) {
  const k = (kategorija || '').toUpperCase()
  const ima = (...r) => r.some((s) => k.includes(s))

  if (ima('KOČNIC', 'KOCNIC', 'ABS', 'EBS', 'KLOBN')) return 'kocnice'
  if (ima('PNEUMATIK', 'KOTAČ', 'KOTAC', 'GUME', 'GLAVČIN', 'GLAVCIN', 'VULKANIZER')) return 'kotaci'
  if (ima('OSOVIN', 'OVJES', 'GIBNJ', 'ZRAČNI JASTUC', 'ZRACNI JASTUC', 'DIFERENCIJAL')) return 'osovine'
  if (ima('SEDL', 'VUČN', 'VUCN', 'RUDE', 'KUKE', 'ČELJUST', 'CELJUST')) return 'sedlo'
  if (ima('HIDRAUL', 'DIZALIC', 'RAZVODNIC', 'ŠKARE', 'SKARE')) return 'hidraulika'
  if (ima('REZERVOAR', 'GORIVO', 'AD-BLUE', 'ADBLUE', 'AD BLUE', 'SPREMNIK')) return 'spremnik'
  if (ima('ELEKTRIK', 'DIJAGNOSTIKA', 'RETROVIZOR', 'AKUMULATOR', 'KAMERE', 'SVJETL', 'RASVJET')) return 'elektrika'
  if (ima('MOTOR', 'INJEKTOR', 'VENTIL', 'HLADNJAK', 'INTERCOOLER', 'AUSPUH', 'ISPUŠN', 'ISPUSN',
          'MJENJAČ', 'MJENJAC', 'GETRIBA', 'RETARDER', 'DPF', 'KOMPRESOR', 'TURBO')) return 'motor'
  if (ima('KABIN', 'KLIMA', 'GRIJANJE', 'WEBASTO', 'UPRAVLJANJ')) return 'kabina'
  if (ima('LIMARIJA', 'ŠASIJ', 'SASIJ', 'BOJANJE', 'BLATOBRAN', 'BRANIK', 'BOČNA', 'BOCNA',
          'STRANICA', 'BRAVARIJ', 'NADOGRADNJA', 'LIMOVI')) return 'sasija'
  return null
}

// Status zone iz operacija naloga:
//   'neutral'   — nema pripadne operacije
//   'treba'     — ima posla, ništa nije gotovo
//   'djelomicno'— dio zadataka gotov
//   'gotovo'    — svi zadaci gotovi (ili operacija bez zadataka označena gotovom nemamo → 'treba')
export function statusiZona(operacije = []) {
  const agg = {} // zona → {ukupno, gotovo, ops}
  for (const op of operacije) {
    const zona = zonaZaKategoriju(op.kategorija)
    if (!zona) continue
    const a = agg[zona] || (agg[zona] = { ukupno: 0, gotovo: 0, ops: [] })
    a.ops.push(op)
    for (const z of op.zadaci || []) {
      a.ukupno += 1
      if (z.gotovo) a.gotovo += 1
    }
  }
  const rez = {}
  for (const [zona, a] of Object.entries(agg)) {
    if (a.ukupno === 0) rez[zona] = 'treba' // ima operaciju, nema (još) zadataka
    else if (a.gotovo === 0) rez[zona] = 'treba'
    else if (a.gotovo >= a.ukupno) rez[zona] = 'gotovo'
    else rez[zona] = 'djelomicno'
  }
  return rez
}

// Boje statusa (hex).
export const BOJA_STATUSA = {
  neutral: 0xc4cbd4,
  treba: 0xe8663a,      // narančasto-crveno — za napraviti
  djelomicno: 0xf2b01e, // žuto — djelomično
  gotovo: 0x35a35a,     // zeleno — gotovo
}
export const BOJA_STATUSA_CSS = {
  neutral: '#c4cbd4',
  treba: '#e8663a',
  djelomicno: '#f2b01e',
  gotovo: '#35a35a',
}
export const OZNAKA_STATUSA = {
  neutral: 'nema posla',
  treba: 'za napraviti',
  djelomicno: 'djelomično',
  gotovo: 'gotovo',
}
