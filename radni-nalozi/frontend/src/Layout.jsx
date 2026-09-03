import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { useT } from './i18n'

export default function Layout({ naslov, nazad, children, akcija }) {
  const { korisnik } = useAuth()
  const { t } = useT()
  const nav = useNavigate()

  const tabovi = []
  if (korisnik?.uloga === 'vozac') {
    tabovi.push({ do: '/prijave', ikona: '📋', txt: t('tab.prijave') })
  }
  if (korisnik?.uloga === 'voditelj') {
    tabovi.push({ do: '/izbornik', ikona: '🗂️', txt: t('tab.izbornik') })
    tabovi.push({ do: '/vozila-u-radu', ikona: '🚚', txt: t('tab.vozilaURadu') })
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
    tabovi.push({ do: '/prijave', ikona: '📋', txt: t('tab.prijave') })
    tabovi.push({ do: '/steta', ikona: '💥', txt: t('tab.steta') })
    tabovi.push({ do: '/sifrarnik', ikona: '⚙️', txt: t('tab.sifrarnik') })
  }
  if (korisnik?.uloga === 'radnik') {
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
  }
  tabovi.push({ do: '/profil', ikona: '👤', txt: t('tab.profil') })

  return (
    <div className="app">
      <header className="topbar">
        {nazad && <span className="nazad" onClick={() => nav(nazad === true ? -1 : nazad)}>‹</span>}
        <h1>{naslov}</h1>
        {akcija}
        {!akcija && korisnik && <span className="uloga">{t('uloga.' + korisnik.uloga)}</span>}
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
