import { useEffect, useState } from 'react'
import { api } from './api'
import { useAuth } from './auth'

// Imenik telefona — SAMO ČITANJE. Izvor istine je Flota OS (tamo se brojevi uređuju);
// backend ih povlači uživo uz predmemoriju 5 min, pa ovdje uvijek piše isto što i u Floti.

// „Kovač Marko" == „marko KOVAC": bez dijakritike, mala slova, riječi sortirane (isto kao backend).
export function kljucImena(ime) {
  const s = String(ime || '').replace(/đ/g, 'd').replace(/Đ/g, 'D')
    .normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  return s.replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean).sort().join(' ')
}

// „+385912319143" → „+385 91 231 9143" (samo prikaz)
export function lijepBroj(b) {
  const m = String(b || '').match(/^\+385(\d{2})(\d{3})(\d{3,4})$/)
  return m ? `+385 ${m[1]} ${m[2]} ${m[3]}` : String(b || '')
}

// {kljucImena: {broj, kratki}} — SAMO imena s jednim jedinim brojem (siguran spoj; inače ništa).
export function brojeviPoImenu(zapisi) {
  const po = {}
  for (const z of zapisi || []) {
    const k = kljucImena(z.ime)
    if (!k) continue
    po[k] = po[k] || {}
    po[k][z.broj] = z.kratki
  }
  const out = {}
  for (const [k, v] of Object.entries(po)) {
    const brojevi = Object.keys(v)
    if (brojevi.length === 1) out[k] = { broj: brojevi[0], kratki: v[brojevi[0]] }
  }
  return out
}

// Hook za prikaz broja uz radnika drugdje u aplikaciji. Prazno ako korisnik nema pristup imeniku
// ili Flota ne odgovara — tada se jednostavno ništa ne prikazuje.
export function useBrojeviIzImenika() {
  const { korisnik } = useAuth()
  const [po, setPo] = useState({})
  const smije = !!korisnik?.imenik
  useEffect(() => {
    if (!smije) { setPo({}); return }
    let ziv = true
    api.imenik().then((d) => { if (ziv) setPo(brojeviPoImenu(d.zapisi)) }).catch(() => {})
    return () => { ziv = false }
  }, [smije])
  return po
}
