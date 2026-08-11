import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { ULOGA } from './ui'

export default function Layout({ naslov, nazad, children, akcija }) {
  const { korisnik } = useAuth()
  const nav = useNavigate()

  const tabovi = []
  if (korisnik?.uloga === 'vozac') {
    tabovi.push({ do: '/prijave', ikona: '📋', txt: 'Prijave' })
  }
  if (korisnik?.uloga === 'voditelj') {
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: 'Nalozi' })
    tabovi.push({ do: '/prijave', ikona: '📋', txt: 'Prijave' })
    tabovi.push({ do: '/sifrarnik', ikona: '⚙️', txt: 'Šifrarnik' })
  }
  if (korisnik?.uloga === 'radnik') {
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: 'Nalozi' })
  }
  tabovi.push({ do: '/profil', ikona: '👤', txt: 'Profil' })

  return (
    <div className="app">
      <header className="topbar">
        {nazad && <span className="nazad" onClick={() => nav(nazad === true ? -1 : nazad)}>‹</span>}
        <h1>{naslov}</h1>
        {akcija}
        {!akcija && korisnik && <span className="uloga">{ULOGA[korisnik.uloga]}</span>}
      </header>
      <main className="sadrzaj">{children}</main>
      <nav className="tabbar">
        {tabovi.map((t) => (
          <NavLink key={t.do} to={t.do} className={({ isActive }) => (isActive ? 'akt' : '')}>
            <span className="ikona">{t.ikona}</span>
            {t.txt}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
