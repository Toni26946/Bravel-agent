import { useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { useT } from './i18n'

export default function Layout({ naslov, nazad, children, akcija }) {
  const { korisnik } = useAuth()
  const { t } = useT()
  const nav = useNavigate()
  const lok = useLocation()
  // Lijevi izbornik: skupljen (samo ikone) ili raširen (ikone + tekst). Pamti se.
  const [navOtvoren, setNavOtvoren] = useState(() => {
    try { const v = localStorage.getItem('nav_otvoren'); if (v !== null) return v === '1' } catch (_) { /* */ }
    return typeof window !== 'undefined' && window.innerWidth >= 860
  })
  const toggleNav = () => setNavOtvoren((o) => {
    const n = !o
    try { localStorage.setItem('nav_otvoren', n ? '1' : '0') } catch (_) { /* */ }
    return n
  })
  const zatvoriNaUsko = () => { if (typeof window !== 'undefined' && window.innerWidth < 760) setNavOtvoren(false) }
  // Plutajući "+" za novi nalog — svugdje osim na stranicama prijava
  // (ondje je vlastiti "+" za novu prijavu) i na samoj stranici kreiranja.
  const prikaziPlus = (korisnik?.uloga === 'voditelj' || korisnik?.uloga === 'poslovodja')
    && !lok.pathname.startsWith('/prijave')
    && lok.pathname !== '/nalozi/novi'

  const tabovi = []
  if (korisnik?.uloga === 'vozac') {
    tabovi.push({ do: '/prijave', ikona: '📋', txt: t('tab.prijave') })
  }
  if (korisnik?.uloga === 'voditelj') {
    tabovi.push({ do: '/izbornik', ikona: '🗂️', txt: t('tab.izbornik') })
    tabovi.push({ do: '/vozila-u-radu', ikona: '🚚', txt: t('tab.vozilaURadu') })
    tabovi.push({ do: '/izasli', ikona: '🛣️', txt: t('tab.izasli') })
    tabovi.push({ do: '/vozila', ikona: '🚙', txt: t('tab.vozila') })
    tabovi.push({ do: '/spremne', ikona: '🟢', txt: t('tab.spremne') })
    tabovi.push({ do: '/nezaduzena', ikona: '🛻', txt: t('tab.nezaduzena') })
    tabovi.push({ do: '/parkiranje', ikona: '🅿️', txt: t('tab.parkiranje') })
    tabovi.push({ do: '/prikapcanje', ikona: '🔗', txt: t('tab.prikapcanje') })
    tabovi.push({ do: '/zaduzenja', ikona: '🧾', txt: t('tab.zaduzenja') })
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
    tabovi.push({ do: '/prijave', ikona: '📋', txt: t('tab.prijave') })
    tabovi.push({ do: '/steta', ikona: '💥', txt: t('tab.steta') })
    tabovi.push({ do: '/sifrarnik', ikona: '📖', txt: t('tab.sifrarnik') })
  }
  if (korisnik?.uloga === 'poslovodja') {
    tabovi.push({ do: '/izbornik', ikona: '🗂️', txt: t('tab.izbornik') })
    tabovi.push({ do: '/vozila-u-radu', ikona: '🚚', txt: t('tab.vozilaURadu') })
    tabovi.push({ do: '/vozila', ikona: '🚙', txt: t('tab.vozila') })
    tabovi.push({ do: '/spremne', ikona: '🟢', txt: t('tab.spremne') })
    tabovi.push({ do: '/nezaduzena', ikona: '🛻', txt: t('tab.nezaduzena') })
    tabovi.push({ do: '/parkiranje', ikona: '🅿️', txt: t('tab.parkiranje') })
    tabovi.push({ do: '/prikapcanje', ikona: '🔗', txt: t('tab.prikapcanje') })
    tabovi.push({ do: '/zaduzenja', ikona: '🧾', txt: t('tab.zaduzenja') })
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
  }
  if (korisnik?.uloga === 'radnik') {
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
  }
  tabovi.push({ do: '/profil', ikona: '👤', txt: t('tab.profil') })

  return (
    <div className={'app' + (navOtvoren ? ' nav-open' : '')}>
      <header className="topbar">
        <button className="nav-toggle" onClick={toggleNav} aria-label={t('nav.izbornik')} title={t('nav.izbornik')}>☰</button>
        {nazad && <span className="nazad" onClick={() => nav(nazad === true ? -1 : nazad)}>‹</span>}
        <h1>{naslov}</h1>
        {akcija}
        {!akcija && korisnik && <span className="uloga">{t('uloga.' + korisnik.uloga)}</span>}
      </header>
      <nav className="tabbar">
        {tabovi.map((t) => (
          <NavLink key={t.do} to={t.do} onClick={zatvoriNaUsko} className={({ isActive }) => (isActive ? 'akt' : '')}>
            <span className="ikona">{t.ikona}</span>
            <span className="txt">{t.txt}</span>
          </NavLink>
        ))}
      </nav>
      {navOtvoren && <div className="nav-backdrop" onClick={toggleNav} />}
      <main className="sadrzaj">{children}</main>
      {prikaziPlus && (
        <button className="fab-novi" onClick={() => nav('/nalozi/novi')} title={t('noviNalog.title')} aria-label={t('noviNalog.title')}>
          +
        </button>
      )}
    </div>
  )
}
