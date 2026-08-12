import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import { Spinner } from './ui'

import Login from './pages/Login'
import Profil from './pages/Profil'
import Prijave from './pages/Prijave'
import NovaPrijava from './pages/NovaPrijava'
import PrijavaDetalj from './pages/PrijavaDetalj'
import Nalozi from './pages/Nalozi'
import NoviNalog from './pages/NoviNalog'
import NalogDetalj from './pages/NalogDetalj'
import Steta from './pages/Steta'
import Sifrarnik from './pages/Sifrarnik'
import VoziloDetalj from './pages/VoziloDetalj'

function pocetna(uloga) {
  if (uloga === 'vozac') return '/prijave'
  return '/nalozi'
}

function Zasticeno({ uloge, children }) {
  const { korisnik, ucitavanje } = useAuth()
  if (ucitavanje) return <Spinner />
  if (!korisnik) return <Navigate to="/prijava" replace />
  if (uloge && !uloge.includes(korisnik.uloga)) return <Navigate to={pocetna(korisnik.uloga)} replace />
  return children
}

export default function App() {
  const { korisnik, ucitavanje } = useAuth()
  if (ucitavanje) return <Spinner />

  return (
    <Routes>
      <Route path="/prijava" element={korisnik ? <Navigate to={pocetna(korisnik.uloga)} replace /> : <Login />} />

      {/* Vozač + voditelj: prijave kvarova */}
      <Route path="/prijave" element={<Zasticeno uloge={['vozac', 'voditelj']}><Prijave /></Zasticeno>} />
      <Route path="/prijave/nova" element={<Zasticeno uloge={['vozac', 'voditelj']}><NovaPrijava /></Zasticeno>} />
      <Route path="/prijave/:id" element={<Zasticeno uloge={['vozac', 'voditelj']}><PrijavaDetalj /></Zasticeno>} />

      {/* Nalozi: voditelj (svi) + radnik (dodijeljeni) */}
      <Route path="/nalozi" element={<Zasticeno uloge={['voditelj', 'radnik']}><Nalozi /></Zasticeno>} />
      <Route path="/nalozi/novi" element={<Zasticeno uloge={['voditelj']}><NoviNalog /></Zasticeno>} />
      <Route path="/nalozi/:id" element={<Zasticeno uloge={['voditelj', 'radnik']}><NalogDetalj /></Zasticeno>} />

      {/* Šteta: voditelj */}
      <Route path="/steta" element={<Zasticeno uloge={['voditelj']}><Steta /></Zasticeno>} />

      {/* Kamion (detalj + povijest dijelova): voditelj + radnik */}
      <Route path="/vozila/:id" element={<Zasticeno uloge={['voditelj', 'radnik']}><VoziloDetalj /></Zasticeno>} />

      {/* Šifrarnik: voditelj */}
      <Route path="/sifrarnik" element={<Zasticeno uloge={['voditelj']}><Sifrarnik /></Zasticeno>} />

      <Route path="/profil" element={<Zasticeno><Profil /></Zasticeno>} />

      <Route path="*" element={<Navigate to={korisnik ? pocetna(korisnik.uloga) : '/prijava'} replace />} />
    </Routes>
  )
}
