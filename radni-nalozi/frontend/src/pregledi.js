// Zajednički pomoćnici za periodične provjere vozila (kartica „Pregledi vozila"
// i banner u radnom nalogu). Rok = zadnji datum + interval (mj.); registracija
// je samo datum isteka.

// datum + N mjeseci → ISO (YYYY-MM-DD)
export function dodajMjesece(iso, mj) {
  if (!iso || !mj) return null
  const d = new Date(iso + 'T00:00:00')
  if (isNaN(d)) return null
  const dan = d.getDate()
  d.setMonth(d.getMonth() + Number(mj))
  if (d.getDate() < dan) d.setDate(0) // prelio mjesec → zadnji dan prethodnog
  return d.toISOString().slice(0, 10)
}

export function danaDo(iso) {
  if (!iso) return null
  const d = new Date(iso + 'T00:00:00')
  if (isNaN(d)) return null
  const danas = new Date(); danas.setHours(0, 0, 0, 0)
  return Math.round((d - danas) / 86400000)
}

export function hrDatum(iso) {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  if (isNaN(d)) return iso
  return d.toLocaleDateString('hr-HR')
}

// Razred boje po broju dana do isteka (siva = nepoznato).
export function klasa(dana) {
  if (dana == null) return 'pv-siva'
  if (dana < 0) return 'pv-crvena'
  if (dana <= 30) return 'pv-naranca'
  return 'pv-zelena'
}

// Definicije provjera: `do` = polje „vrijedi do" (upisuje se izravno s potvrde —
// Toni 25.11.2026.: tehnički piše različite datume, „+3 mj." nije dobro);
// datum-polje + interval ostaju samo kao rezerva za stare zapise. `txt` je ključ prijevoda.
export const PROVJERE = [
  { k: 'periodicki', do: 'periodicki_do', dp: 'periodicki_datum', ip: 'periodicki_int', zad: 3, txt: 'pv.periodicki' },
  { k: 'taho', do: 'taho_do', dp: 'taho_datum', ip: 'taho_int', zad: 24, txt: 'pv.taho' },
  { k: 'pp', do: 'pp_do', dp: 'pp_datum', ip: 'pp_int', zad: 12, txt: 'pv.pp' },
  { k: 'reg', do: 'registracija_istek', dp: null, ip: null, zad: null, txt: 'pv.reg' },
]

// Datum do kad provjera vrijedi: upisani „vrijedi do", inače (stari zapis) datum + interval.
export function istekZa(v, p) {
  if (v[p.do]) return v[p.do]
  if (!p.dp) return null
  return dodajMjesece(v[p.dp], v[p.ip] || p.zad)
}

// Svi rokovi vozila s brojem dana (za banner). Prag „uskoro" = ≤14 dana.
export const PRAG_USKORO = 14
export function rokoviVozila(v) {
  return PROVJERE.map((p) => {
    const istek = istekZa(v, p)
    return { k: p.k, txt: p.txt, istek, dana: danaDo(istek) }
  })
}
