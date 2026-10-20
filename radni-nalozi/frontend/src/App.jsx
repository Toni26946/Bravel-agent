import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import { Spinner } from './ui'

import Login from './pages/Login'
import Profil from './pages/Profil'
import Prijave from './pages/Prijave'
import NovaPrijava from './pages/NovaPrijava'
import PrijavaDetalj from './pages/PrijavaDetalj'
import Nalozi from './pages/Nalozi'
import { GlavniIzbornik, VozilaURadu } from './pages/Nadzor'
import IzasliIzRadione from './pages/IzasliIzRadione'
import NezaduzenaVozila from './pages/NezaduzenaVozila'
import Vozila from './pages/Vozila'
import SpremneSlepe from './pages/SpremneSlepe'
import EvidencijaPrikapcanja from './pages/EvidencijaPrikapcanja'
import Servisi from './pages/Servisi'
import Parkiranje from './pages/Parkiranje'
import NoviNalog from './pages/NoviNalog'
import NalogDetalj from './pages/NalogDetalj'
import Zaduzenja from './pages/Zaduzenja'
import ZaduzenjeDetalj from './pages/ZaduzenjeDetalj'
import Vozaci from './pages/Vozaci'
import Poslovodja from './pages/Poslovodja'
import MojUcinak from './pages/MojUcinak'
import Steta from './pages/Steta'
import Sifrarnik from './pages/Sifrarnik'
import VoziloDetalj from './pages/VoziloDetalj'
import Skladiste from './pages/Skladiste'
import SkladisteDashboard from './pages/SkladisteDashboard'
import EvidencijaRV from './pages/EvidencijaRV'
import Plan from './pages/Plan'
import MojaRadiona from './pages/MojaRadiona'

function pocetna(uloga) {
  if (uloga === 'vozac') return '/prijave'
  // Skladištar: njegov ekran je skladište (primke otpremnica).
  if (uloga === 'skladistar') return '/skladiste'
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

      {/* Nadzor: Glavni izbornik (tekući radovi) + Vozila u radu */}
      <Route path="/izbornik" element={<Zasticeno uloge={['voditelj', 'poslovodja', 'radnik']}><GlavniIzbornik /></Zasticeno>} />
      <Route path="/vozila-u-radu" element={<Zasticeno uloge={['voditelj', 'poslovodja', 'radnik']}><VozilaURadu /></Zasticeno>} />
      <Route path="/izasli" element={<Zasticeno uloge={['voditelj', 'poslovodja', 'radnik']}><IzasliIzRadione /></Zasticeno>} />
      <Route path="/vozila" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><Vozila /></Zasticeno>} />
      <Route path="/spremne" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><SpremneSlepe /></Zasticeno>} />
      <Route path="/nezaduzena" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><NezaduzenaVozila /></Zasticeno>} />
      <Route path="/parkiranje" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><Parkiranje /></Zasticeno>} />
      <Route path="/prikapcanje" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><EvidencijaPrikapcanja /></Zasticeno>} />
      <Route path="/servisi" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><Servisi /></Zasticeno>} />

      {/* Nalozi: voditelj/poslovođa (svi, kreiranje/uređivanje) + radnik (dodijeljeni) */}
      <Route path="/nalozi" element={<Zasticeno uloge={['voditelj', 'poslovodja', 'radnik']}><Nalozi /></Zasticeno>} />
      <Route path="/nalozi/novi" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><NoviNalog /></Zasticeno>} />
      <Route path="/nalozi/:id" element={<Zasticeno uloge={['voditelj', 'poslovodja', 'radnik']}><NalogDetalj /></Zasticeno>} />

      {/* Zaduženje kamiona/prikolica: voditelj + poslovođa */}
      <Route path="/zaduzenja" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><Zaduzenja /></Zasticeno>} />
      <Route path="/zaduzenja/novo" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><ZaduzenjeDetalj novo /></Zasticeno>} />
      <Route path="/zaduzenja/:id" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><ZaduzenjeDetalj /></Zasticeno>} />

      {/* Šifrarnik vozača: voditelj + poslovođa */}
      <Route path="/vozaci" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><Vozaci /></Zasticeno>} />

      {/* AI Poslovođa (norme, učinak, postavke): voditelj + poslovođa */}
      <Route path="/poslovodja" element={<Zasticeno uloge={['voditelj', 'poslovodja']}><Poslovodja /></Zasticeno>} />
      <Route path="/moj-ucinak" element={<Zasticeno uloge={['voditelj', 'poslovodja', 'radnik']}><MojUcinak /></Zasticeno>} />

      {/* Plan radione (pregled) — SAMO vlasnik (ai_poslovodja = 'toni') */}
      <Route path="/plan" element={<Zasticeno uloge={['voditelj', 'poslovodja']}>{korisnik?.ai_poslovodja ? <Plan /> : <Navigate to={pocetna(korisnik?.uloga)} replace />}</Zasticeno>} />

      {/* Šteta: voditelj */}
      <Route path="/steta" element={<Zasticeno uloge={['voditelj']}><Steta /></Zasticeno>} />

      {/* Skladište (primke otpremnica): skladištar + voditelj + poslovođa */}
      <Route path="/skladiste" element={<Zasticeno uloge={['skladistar', 'voditelj', 'poslovodja']}><Skladiste /></Zasticeno>} />
      <Route path="/skladiste/dashboard" element={<Zasticeno uloge={['skladistar', 'voditelj', 'poslovodja']}><SkladisteDashboard /></Zasticeno>} />

      {/* Evidencija radnog vremena: skladištar + voditelj + poslovođa */}
      <Route path="/evidencija" element={<Zasticeno uloge={['skladistar', 'voditelj', 'poslovodja']}><EvidencijaRV /></Zasticeno>} />

      {/* Kamion (detalj + povijest dijelova): voditelj + poslovođa + radnik */}
      <Route path="/vozila/:id" element={<Zasticeno uloge={['voditelj', 'poslovodja', 'radnik']}><VoziloDetalj /></Zasticeno>} />

      {/* Šifrarnik: voditelj */}
      <Route path="/sifrarnik" element={<Zasticeno uloge={['voditelj']}><Sifrarnik /></Zasticeno>} />
      <Route path="/radnici" element={<Zasticeno uloge={['voditelj']}><Sifrarnik pocetniTab="korisnici" /></Zasticeno>} />
      <Route path="/moja-radiona" element={<Zasticeno uloge={['radnik', 'voditelj', 'poslovodja']}><MojaRadiona /></Zasticeno>} />

      <Route path="/profil" element={<Zasticeno><Profil /></Zasticeno>} />

      <Route path="*" element={<Navigate to={korisnik ? pocetna(korisnik.uloga) : '/prijava'} replace />} />
    </Routes>
  )
}
