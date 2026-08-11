import { createContext, useContext, useEffect, useState } from 'react'
import { api, setToken } from './api'

const AuthCtx = createContext(null)

export function AuthProvider({ children }) {
  const [korisnik, setKorisnik] = useState(null)
  const [ucitavanje, setUcitavanje] = useState(true)

  useEffect(() => {
    const t = localStorage.getItem('token')
    if (!t) { setUcitavanje(false); return }
    api.me()
      .then(setKorisnik)
      .catch(() => setToken(null))
      .finally(() => setUcitavanje(false))
  }, [])

  const prijava = async (korisnicko_ime, lozinka) => {
    const r = await api.login(korisnicko_ime, lozinka)
    setToken(r.access_token)
    setKorisnik(r.korisnik)
    return r.korisnik
  }

  const odjava = () => {
    setToken(null)
    setKorisnik(null)
  }

  return (
    <AuthCtx.Provider value={{ korisnik, ucitavanje, prijava, odjava }}>
      {children}
    </AuthCtx.Provider>
  )
}

export const useAuth = () => useContext(AuthCtx)
