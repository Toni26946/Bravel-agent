// Ime zadnjeg vozača uz garažni broj — na svim ekranima (Veljko 26.11.2026., #433, #436).
// Kamion: vozač koji ga je zadnji vozio (Flota OS); priključno vozilo: vozač sa zadnjeg
// prikapčanja. Jedan dohvat za cijelu aplikaciju (keš 5 min), ekrani ga samo čitaju.
import { useEffect, useState } from 'react'
import { api } from './api'

const TTL = 5 * 60 * 1000
let mapa = null          // { gb: ime }
let vrijeme = 0
let u_tijeku = null
const slusaci = new Set()

const kljuc = (gb) => { const s = String(gb ?? '').trim(); return s.replace(/^0+/, '') || s }

function dohvati() {
  if (u_tijeku || (mapa && Date.now() - vrijeme < TTL)) return
  u_tijeku = api.zadnjiVozaci()
    .then((d) => {
      const m = {}
      for (const [gb, ime] of Object.entries(d || {})) if (ime) m[kljuc(gb)] = ime
      mapa = m
      vrijeme = Date.now()
      slusaci.forEach((f) => f(mapa))
    })
    .catch(() => { vrijeme = Date.now() - TTL + 60 * 1000 })   // greška → pokušaj opet za 1 min
    .finally(() => { u_tijeku = null })
}

// Mapa { gb: ime } (prazna dok se ne učita).
export function useZadnjiVozaci() {
  const [m, setM] = useState(mapa || {})
  useEffect(() => {
    slusaci.add(setM)
    dohvati()
    return () => { slusaci.delete(setM) }
  }, [])
  return m
}

export function imeZadnjegVozaca(m, gb) {
  return gb ? (m || {})[kljuc(gb)] || null : null
}

// Mali dodatak uz GB: „ · 🧑 Ime". `osim` = ime koje se već vidi (npr. vozač s naloga).
export default function ZadnjiVozac({ gb, osim, prefiks = ' · ', style }) {
  const m = useZadnjiVozaci()
  const ime = imeZadnjegVozaca(m, gb)
  if (!ime) return null
  if (osim && String(osim).trim().toLowerCase() === ime.trim().toLowerCase()) return null
  return <span className="zadnji-vozac" title="Zadnji vozač" style={{ fontWeight: 400, ...style }}>{prefiks}🧑 {ime}</span>
}
