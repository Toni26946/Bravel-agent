// ↶ PONIŠTI — povrat radnje unazad (WhatsApp prijava #377, Veljko: „ako kliknem zabunom
// na ovaj × da mogu ispraviti pogrešku i vratiti se korak ili više nazad").
//
// Dvije vrste radnji:
// 1. BRISANJE (odgodi): ništa se ne briše odmah — stavka se samo sakrije, a pravo brisanje
//    na serveru ide tek nakon ODGODA_MS. Do tad „Poništi" samo vrati stavku (server nije ni
//    dirnut, pa se ne gube ni vremena radnika ni povijest). Pri odlasku sa stranice/zatvaranju
//    kartice sva odgođena brisanja se odmah izvrše (fetch s keepalive).
// 2. IZMJENA (zabiljezi): radnja je već spremljena, a uz nju se pamti obrnuta radnja (stari
//    tekst, stari status, kvačica natrag). „Poništi" je izvrši.
// Radnje se slažu u stog (najnovija gore) — svaki klik na „Poništi" vraća jedan korak.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

export const ODGODA_MS = 10000          // koliko dugo se brisanje može poništiti
const IZMJENA_MS = 120000               // koliko dugo se pamti izmjena za poništavanje
const MAX_KORAKA = 15

const Ctx = createContext(null)
let brojac = 0

export function PonistiProvider({ children }) {
  const [stog, setStog] = useState([])            // [{id, opis, vrsta, do}]
  const [skriveni, setSkriveni] = useState(() => new Set())
  const radnje = useRef(new Map())                // id → {izvrsi, vrati, kljuc, timer}
  const [, setOtkucaj] = useState(0)

  const makni = useCallback((id) => {
    radnje.current.delete(id)
    setStog((s) => s.filter((r) => r.id !== id))
  }, [])

  // Pravo brisanje na serveru (nakon isteka odgode ili pri odlasku sa stranice).
  const izvrsiBrisanje = useCallback((id) => {
    const r = radnje.current.get(id)
    if (!r) return
    clearTimeout(r.timer)
    makni(id)
    Promise.resolve()
      .then(() => r.izvrsi())
      .then(() => r.nakon && r.nakon())
      .catch((e) => {
        // Brisanje nije prošlo → stavka se opet pokaže i javi se greška.
        setSkriveni((s) => { const n = new Set(s); n.delete(r.kljuc); return n })
        r.naGresku && r.naGresku(e.message || String(e))
      })
      .finally(() => setSkriveni((s) => { if (!s.has(r.kljuc)) return s; const n = new Set(s); n.delete(r.kljuc); return n }))
  }, [makni])

  // Brisanje s odgodom. kljuc = oznaka stavke koju stranica ne smije prikazati (npr. 'zad:12').
  const odgodi = useCallback(({ opis, kljuc, izvrsi, nakon, naGresku }) => {
    const id = ++brojac
    setSkriveni((s) => new Set(s).add(kljuc))
    const timer = setTimeout(() => izvrsiBrisanje(id), ODGODA_MS)
    radnje.current.set(id, { vrsta: 'brisanje', izvrsi, nakon, naGresku, kljuc, timer })
    setStog((s) => [{ id, opis, vrsta: 'brisanje', do: Date.now() + ODGODA_MS }, ...s].slice(0, MAX_KORAKA))
  }, [izvrsiBrisanje])

  // Već spremljena izmjena + obrnuta radnja.
  const zabiljezi = useCallback(({ opis, vrati, nakon, naGresku }) => {
    const id = ++brojac
    const timer = setTimeout(() => makni(id), IZMJENA_MS)
    radnje.current.set(id, { vrsta: 'izmjena', vrati, nakon, naGresku, timer })
    setStog((s) => {
      const novi = [{ id, opis, vrsta: 'izmjena', do: Date.now() + IZMJENA_MS }, ...s]
      // Stare izmjene preko granice ispadaju (brisanja se nikad ne izbacuju — moraju se izvršiti).
      return novi.filter((r, i) => i < MAX_KORAKA || r.vrsta === 'brisanje')
    })
  }, [makni])

  // Poništi NAJNOVIJI korak.
  const ponisti = useCallback(() => {
    const vrh = stog[0]
    if (!vrh) return
    const r = radnje.current.get(vrh.id)
    makni(vrh.id)
    if (!r) return
    clearTimeout(r.timer)
    if (r.vrsta === 'brisanje') {
      setSkriveni((s) => { const n = new Set(s); n.delete(r.kljuc); return n })
    } else {
      Promise.resolve()
        .then(() => r.vrati())
        .then(() => r.nakon && r.nakon())
        .catch((e) => r.naGresku && r.naGresku(e.message || String(e)))
    }
  }, [stog, makni])

  const zatvori = useCallback(() => {
    // „✕" samo skloni traku: odgođena brisanja se izvrše odmah, izmjene se zaborave.
    for (const r of stog) {
      if (r.vrsta === 'brisanje') izvrsiBrisanje(r.id)
      else makni(r.id)
    }
  }, [stog, izvrsiBrisanje, makni])

  // Odbrojavanje na traci (samo dok ima odgođenih brisanja).
  const imaBrisanja = stog.some((r) => r.vrsta === 'brisanje')
  useEffect(() => {
    if (!imaBrisanja) return
    const t = setInterval(() => setOtkucaj((x) => x + 1), 1000)
    return () => clearInterval(t)
  }, [imaBrisanja])

  // Zatvaranje kartice / aplikacije → odgođena brisanja odmah na server.
  useEffect(() => {
    const isprazni = () => {
      for (const [id, r] of radnje.current) if (r.vrsta === 'brisanje') izvrsiBrisanje(id)
    }
    window.addEventListener('pagehide', isprazni)
    return () => window.removeEventListener('pagehide', isprazni)
  }, [izvrsiBrisanje])

  const vrh = stog[0]
  const preostalo = vrh && vrh.vrsta === 'brisanje' ? Math.max(0, Math.ceil((vrh.do - Date.now()) / 1000)) : null

  return (
    <Ctx.Provider value={{ odgodi, zabiljezi, skriveni }}>
      {children}
      {vrh && (
        <div className="ponisti-traka" role="status">
          <span className="ponisti-opis">
            {vrh.opis}
            {preostalo != null && <span className="ponisti-sek"> · {preostalo} s</span>}
          </span>
          <button type="button" className="ponisti-gumb" onClick={ponisti}>
            ↶ Poništi{stog.length > 1 ? ` (${stog.length})` : ''}
          </button>
          <button type="button" className="ponisti-x" onClick={zatvori} aria-label="Zatvori">✕</button>
        </div>
      )}
    </Ctx.Provider>
  )
}

// Bez providera (npr. u testu ili zasebnoj aplikaciji) radnje se izvrše odmah, bez poništavanja.
const BEZ = {
  odgodi: ({ izvrsi, nakon, naGresku }) => {
    Promise.resolve().then(izvrsi).then(() => nakon && nakon()).catch((e) => naGresku && naGresku(e.message))
  },
  zabiljezi: () => {},
  skriveni: new Set(),
}

export function usePonisti() {
  return useContext(Ctx) || BEZ
}
