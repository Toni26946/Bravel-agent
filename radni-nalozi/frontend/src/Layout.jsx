import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { api } from './api'
import { useT } from './i18n'

export default function Layout({ naslov, nazad, children, akcija }) {
  const { korisnik } = useAuth()
  const { t } = useT()
  const nav = useNavigate()
  const lok = useLocation()
  // Natrag: gumb u zaglavlju i hardverska/preglednicka tipka Back rade istu stvar.
  const idiNazad = () => {
    if (typeof nazad === 'function') nazad()
    else if (nazad) nav(nazad === true ? -1 : nazad)
  }
  const nazadRef = useRef(idiNazad)
  nazadRef.current = idiNazad
  useEffect(() => {
    if (!nazad) return
    // Gurni "cuvar" u povijest pa prvi Back pokrene isto sto i gumb (ne izlazi iz appa).
    window.history.pushState(null, '', window.location.href)
    const naBack = () => nazadRef.current()
    window.addEventListener('popstate', naBack)
    return () => window.removeEventListener('popstate', naBack)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // Lijevi izbornik: skupljen (samo ikone) ili raširen (ikone + tekst). Pamti se.
  const [navOtvoren, setNavOtvoren] = useState(() => {
    try { const v = localStorage.getItem('nav_otvoren'); if (v !== null) return v === '1' } catch (_) { /* */ }
    return false   // zadano skupljeno; otvara/zatvara se SAMO ☰ gumbom kraj loga
  })
  const toggleNav = () => setNavOtvoren((o) => {
    const n = !o
    try { localStorage.setItem('nav_otvoren', n ? '1' : '0') } catch (_) { /* */ }
    return n
  })
  const zatvoriNaUsko = () => { if (typeof window !== 'undefined' && window.innerWidth < 760) setNavOtvoren(false) }
  // Otvorene grupe (padajući podizbornici) — pamti se.
  const [grupeOtvorene, setGrupeOtvorene] = useState(() => {
    try { return JSON.parse(localStorage.getItem('nav_grupe') || '{}') } catch (_) { return {} }
  })
  const toggleGrupa = (id) => setGrupeOtvorene((g) => {
    const n = { ...g, [id]: !g[id] }
    try { localStorage.setItem('nav_grupe', JSON.stringify(n)) } catch (_) { /* */ }
    return n
  })

  // Pažnja voditelja: brojevi za crvene oznake na karticama (Spremne, Izašli, Prijave).
  const [paznja, setPaznja] = useState({})
  const voditeljski = korisnik?.uloga === 'voditelj' || korisnik?.uloga === 'poslovodja'
  useEffect(() => {
    if (!voditeljski) { setPaznja({}); return }
    let ziv = true
    const uc = () => api.paznja().then((p) => { if (ziv) setPaznja(p || {}) }).catch(() => {})
    uc()
    const id = setInterval(uc, 60000)
    return () => { ziv = false; clearInterval(id) }
  }, [voditeljski])
  const paznjaZa = (putanja) => {
    const m = { '/spremne': paznja.spremne, '/izasli': paznja.izasli, '/prijave': paznja.prijave }
    return m[putanja] || 0
  }
  // Plutajući "+" za novi nalog — svugdje osim na stranicama prijava
  // (ondje je vlastiti "+" za novu prijavu) i na samoj stranici kreiranja.
  const prikaziPlus = (korisnik?.uloga === 'voditelj' || korisnik?.uloga === 'poslovodja')
    && !lok.pathname.startsWith('/prijave')
    && lok.pathname !== '/nalozi/novi'

  const tabovi = []
  const grupaVozila = (jeVoditelj) => ({
    grupa: 'vozila', ikona: '🚙', txt: t('tab.vozila'),
    djeca: [
      { do: '/vozila', ikona: '📋', txt: t('tab.popisVozila') },
      ...(jeVoditelj ? [{ do: '/sifrarnik', ikona: '📖', txt: t('tab.sifrarnik') }] : []),
      { do: '/nezaduzena', ikona: '🛻', txt: t('tab.nezaduzena') },
      { do: '/spremne', ikona: '🟢', txt: t('tab.spremne') },
      { do: '/prikapcanje', ikona: '🔗', txt: t('tab.prikapcanje') },
      { do: '/servisi', ikona: '🛢️', txt: t('tab.servisi') },
    ],
  })
  if (korisnik?.uloga === 'vozac') {
    tabovi.push({ do: '/prijave', ikona: '📋', txt: t('tab.prijave') })
  }
  if (korisnik?.uloga === 'voditelj') {
    tabovi.push({ do: '/izbornik', ikona: '🗂️', txt: t('tab.izbornik') })
    tabovi.push({ do: '/vozila-u-radu', ikona: '🚚', txt: t('tab.vozilaURadu') })
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
    tabovi.push({ do: '/izasli', ikona: '🛣️', txt: t('tab.izasli') })
    tabovi.push(grupaVozila(true))
    tabovi.push({ do: '/skladiste', ikona: '📦', txt: t('tab.skladiste') })
    tabovi.push({ do: '/skladiste/dashboard', ikona: '📊', txt: t('skl.dashboard') })
    tabovi.push({ do: '/evidencija', ikona: '🕒', txt: t('tab.evidencija') })
    tabovi.push({ do: '/zaduzenja', ikona: '🧾', txt: t('tab.zaduzenja') })
    tabovi.push({ do: '/vozaci', ikona: '🧑‍✈️', txt: t('tab.vozaci') })
    if (korisnik.ai_poslovodja) tabovi.push({ do: '/poslovodja', ikona: '🧠', txt: t('tab.poslovodja') })
    tabovi.push({ do: '/steta', ikona: '💥', txt: t('tab.steta') })
  }
  if (korisnik?.uloga === 'poslovodja') {
    tabovi.push({ do: '/izbornik', ikona: '🗂️', txt: t('tab.izbornik') })
    tabovi.push({ do: '/vozila-u-radu', ikona: '🚚', txt: t('tab.vozilaURadu') })
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
    tabovi.push(grupaVozila(false))
    tabovi.push({ do: '/skladiste', ikona: '📦', txt: t('tab.skladiste') })
    tabovi.push({ do: '/skladiste/dashboard', ikona: '📊', txt: t('skl.dashboard') })
    tabovi.push({ do: '/evidencija', ikona: '🕒', txt: t('tab.evidencija') })
    tabovi.push({ do: '/zaduzenja', ikona: '🧾', txt: t('tab.zaduzenja') })
    tabovi.push({ do: '/vozaci', ikona: '🧑‍✈️', txt: t('tab.vozaci') })
    if (korisnik.ai_poslovodja) tabovi.push({ do: '/poslovodja', ikona: '🧠', txt: t('tab.poslovodja') })
  }
  if (korisnik?.uloga === 'skladistar') {
    tabovi.push({ do: '/skladiste', ikona: '📦', txt: t('tab.skladiste') })
    tabovi.push({ do: '/skladiste/dashboard', ikona: '📊', txt: t('skl.dashboard') })
    tabovi.push({ do: '/evidencija', ikona: '🕒', txt: t('tab.evidencija') })
  }
  if (korisnik?.uloga === 'radnik') {
    tabovi.push({ do: '/moj-ucinak', ikona: '🏆', txt: t('tab.mojUcinak') })
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
  }
  // Voditelju Profil ide gore desno (u zaglavlje), ostalima u izbornik.
  if (korisnik?.uloga !== 'voditelj') {
    tabovi.push({ do: '/profil', ikona: '👤', txt: t('tab.profil') })
  }

  return (
    <div className={'app' + (navOtvoren ? ' nav-open' : '')}>
      <header className="topbar">
        <button className="nav-toggle" onClick={toggleNav} aria-label={t('nav.izbornik')} title={t('nav.izbornik')}>☰</button>
        <img src="/bravel-logo.png" alt="Bravel" className="topbar-logo" />
        {nazad && (
          <button type="button" className="nazad" onClick={idiNazad} aria-label={t('nav.natrag')}>
            <span className="nazad-ikona" aria-hidden="true">‹</span>
            <span className="nazad-txt">{t('nav.natrag')}</span>
          </button>
        )}
        <h1>{naslov}</h1>
        {akcija}
        {!akcija && korisnik && <span className="uloga">{t('uloga.' + korisnik.uloga)}</span>}
        {korisnik?.uloga === 'voditelj' && (
          <NavLink to="/profil" title={t('tab.profil')}
            className={({ isActive }) => 'topbar-profil' + (isActive ? ' akt' : '')}>
            <span className="tp-ikona">👤</span>
            <span className="tp-txt">{t('tab.profil')}</span>
          </NavLink>
        )}
      </header>
      <nav className="tabbar">
        {tabovi.map((item) => {
          if (!item.djeca) {
            const n = paznjaZa(item.do)
            return (
              <NavLink key={item.do} to={item.do} onClick={zatvoriNaUsko}
                className={({ isActive }) => (isActive ? 'akt' : '') + (n > 0 ? ' paznja' : '')}>
                <span className="ikona">{item.ikona}</span>
                <span className="txt">{item.txt}</span>
                {n > 0 && <span className="nav-badge">{n}</span>}
              </NavLink>
            )
          }
          const djetetAktivno = item.djeca.some((d) => lok.pathname === d.do || lok.pathname.startsWith(d.do + '/'))
          const otvorena = grupeOtvorene[item.grupa] ?? djetetAktivno
          const grupaPaznja = item.djeca.reduce((s, d) => s + paznjaZa(d.do), 0)
          return (
            <div key={item.grupa} className={'nav-grupa' + (otvorena ? ' otv' : '')}>
              <button type="button"
                className={'nav-grupa-glava' + (djetetAktivno ? ' akt' : '') + (grupaPaznja > 0 ? ' paznja' : '')}
                onClick={() => toggleGrupa(item.grupa)} aria-expanded={otvorena}>
                <span className="ikona">{item.ikona}</span>
                <span className="txt">{item.txt}</span>
                {grupaPaznja > 0 && !otvorena && <span className="nav-badge">{grupaPaznja}</span>}
                <span className="nav-strelica" aria-hidden="true">{otvorena ? '▾' : '▸'}</span>
              </button>
              {otvorena && item.djeca.map((d) => {
                const dn = paznjaZa(d.do)
                return (
                  <NavLink key={d.do} to={d.do} onClick={zatvoriNaUsko}
                    className={({ isActive }) => 'nav-dijete' + (isActive ? ' akt' : '') + (dn > 0 ? ' paznja' : '')}>
                    <span className="ikona">{d.ikona}</span>
                    <span className="txt">{d.txt}</span>
                    {dn > 0 && <span className="nav-badge">{dn}</span>}
                  </NavLink>
                )
              })}
            </div>
          )
        })}
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
