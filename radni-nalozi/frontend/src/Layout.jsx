import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { api } from './api'
import { useT } from './i18n'
import { MODULI } from './moduli'

// Jedinstven redoslijed kartica u izborniku — isti za SVE korisnike.
const NAV_RED = [
  '/plan', 'grupa:plan',
  '/izbornik', '/vozila-u-radu', '/nalozi', '/izasli',
  '/samostalno', '/moja-radiona', '/moj-ucinak', '/prijave',
  'grupa:vozila', 'grupa:skladiste', '/skladiste', '/skladiste/dashboard', '/evidencija',
  '/zaduzenja', '/slobodni-vozaci', '/radnici', '/pregledi', '/poslovodja', '/steta',
  '/imenik', '/profil',
]

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
  // 🔒 Zaključan (Toni 25.11.2026.): ostaje raširen i klik na karticu ga ne skuplja
  // (samo na računalu — na mobitelu je izbornik panel preko sadržaja pa se uvijek zatvara).
  const mobitel = () => typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(max-width: 760px)').matches
  const [zakljucan, setZakljucan] = useState(() => {
    try { return localStorage.getItem('nav_zakljucan') === '1' } catch (_) { return false }
  })
  const [navOtvoren, setNavOtvoren] = useState(() => {
    try {
      if (localStorage.getItem('nav_zakljucan') === '1' && !mobitel()) return true
      const v = localStorage.getItem('nav_otvoren'); if (v !== null) return v === '1'
    } catch (_) { /* */ }
    return false   // zadano skupljeno; otvara/zatvara se ☰ gumbom kraj loga
  })
  const postaviZakljucan = (z) => {
    try { localStorage.setItem('nav_zakljucan', z ? '1' : '0') } catch (_) { /* */ }
    setZakljucan(z)
  }
  const toggleNav = () => setNavOtvoren((o) => {
    const n = !o
    try { localStorage.setItem('nav_otvoren', n ? '1' : '0') } catch (_) { /* */ }
    if (!n && !mobitel()) postaviZakljucan(false)   // ručno skupljen na računalu = otključan
    return n
  })
  // Klik na pravu karticu zatvori (skupi) izbornik — na svim širinama. Grupe
  // (padajući podizbornici) ga NE zatvaraju (vidi toggleGrupa dolje).
  // localStorage se piše ODMAH, ne u updateru: svaka stranica ima svoj <Layout>, pa se
  // kod prelaska na drugu karticu stari odmontira prije nego mu se updater izvrši —
  // nova stranica bi pročitala „otvoreno" i izbornik bi ostao (trebao je drugi klik, #319).
  const zatvoriNav = () => {
    if (zakljucan && !mobitel()) return   // 🔒 zaključan izbornik ostaje otvoren
    try { localStorage.setItem('nav_otvoren', '0') } catch (_) { /* */ }
    setNavOtvoren(false)
  }
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
  // Radnik: badge "za potvrdu" na „Moja radiona".
  const [mojeZaPotvrdu, setMojeZaPotvrdu] = useState(0)
  const jeRadnik = korisnik?.uloga === 'radnik'
  useEffect(() => {
    if (!jeRadnik) { setMojeZaPotvrdu(0); return }
    let ziv = true
    const uc = () => api.planMoje().then((d) => {
      if (ziv) setMojeZaPotvrdu((d.ops || []).filter((o) => o.status === 'ceka' || o.status === 'pauza').length)
    }).catch(() => {})
    uc()
    const id = setInterval(uc, 30000)
    return () => { ziv = false; clearInterval(id) }
  }, [jeRadnik])
  const paznjaZa = (putanja) => {
    const m = { '/spremne': paznja.spremne, '/izasli': paznja.izasli, '/prijave': paznja.prijave, '/moja-radiona': mojeZaPotvrdu }
    return m[putanja] || 0
  }
  // Plutajući "+" za novi nalog — svugdje osim na stranicama prijava
  // (ondje je vlastiti "+" za novu prijavu) i na samoj stranici kreiranja.
  const prikaziPlus = (korisnik?.uloga === 'voditelj' || korisnik?.uloga === 'poslovodja')
    && !lok.pathname.startsWith('/prijave')
    && lok.pathname !== '/nalozi/novi'

  // Pristup Planu radione: vlasnik (ai_poslovodja) ILI kome je dodijeljen modul '/plan'.
  const planPristup = !!(korisnik?.ai_poslovodja
    || (Array.isArray(korisnik?.moduli) && korisnik.moduli.includes('/plan')))

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
  // Plan radione (grupa): dnevni radni pregledi. (Plan je zasebna direktna kartica iznad.)
  const grupaPlan = () => ({
    grupa: 'plan', ikona: '📋', txt: 'Pregled radova',
    djeca: [
      { do: '/izbornik', ikona: '🗂️', txt: t('tab.izbornik') },
      { do: '/vozila-u-radu', ikona: '🚚', txt: t('tab.vozilaURadu') },
      { do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') },
      { do: '/izasli', ikona: '🛣️', txt: t('tab.izasli') },
      { do: '/testovi-kocnica', ikona: '🛞', txt: 'Testovi kočnica' },
    ],
  })
  // Skladište (grupa): Stanje · Primke · Izdatnice · Naručeni dijelovi · Evidencija dijelova.
  const grupaSkladiste = () => ({
    grupa: 'skladiste', ikona: '📦', txt: t('tab.skladiste'),
    djeca: [
      { do: '/skladiste', ikona: '📦', txt: t('skl.stanjeTab'), end: true },
      { do: '/skladiste/primke', ikona: '📥', txt: t('skl.primkeTab') },
      { do: '/skladiste/izdatnice', ikona: '📤', txt: t('skl.izdatniceTab') },
      { do: '/skladiste/narudzbe', ikona: '🛒', txt: t('skl.narudzbeTab') },
      { do: '/skladiste/dashboard', ikona: '📊', txt: t('skl.dashboard') },
    ],
  })
  if (korisnik?.uloga === 'vozac') {
    tabovi.push({ do: '/prijave', ikona: '📋', txt: t('tab.prijave') })
  }
  if (korisnik?.uloga === 'voditelj') {
    if (planPristup) tabovi.push({ do: '/plan', ikona: '📋', txt: 'Plan radione' })
    tabovi.push(grupaPlan())
    tabovi.push(grupaVozila(true))
    tabovi.push(grupaSkladiste())
    tabovi.push({ do: '/zaduzenja', ikona: '🧾', txt: t('tab.zaduzenja') })
    tabovi.push({ do: '/slobodni-vozaci', ikona: '🧑‍✈️', txt: 'Slobodni vozači' })
    tabovi.push({ do: '/radnici', ikona: '👷', txt: t('tab.radnici') })
    tabovi.push({ do: '/pregledi', ikona: '🗓️', txt: t('tab.pregledi') })
    if (korisnik.ai_poslovodja) tabovi.push({ do: '/poslovodja', ikona: '🧠', txt: t('tab.poslovodja') })
    tabovi.push({ do: '/steta', ikona: '💥', txt: t('tab.steta') })
  }
  if (korisnik?.uloga === 'poslovodja') {
    if (planPristup) tabovi.push({ do: '/plan', ikona: '📋', txt: 'Plan radione' })
    tabovi.push(grupaPlan())
    tabovi.push(grupaVozila(false))
    tabovi.push(grupaSkladiste())
    tabovi.push({ do: '/zaduzenja', ikona: '🧾', txt: t('tab.zaduzenja') })
    tabovi.push({ do: '/slobodni-vozaci', ikona: '🧑‍✈️', txt: 'Slobodni vozači' })
    tabovi.push({ do: '/pregledi', ikona: '🗓️', txt: t('tab.pregledi') })
    if (korisnik.ai_poslovodja) tabovi.push({ do: '/poslovodja', ikona: '🧠', txt: t('tab.poslovodja') })
  }
  if (korisnik?.uloga === 'skladistar') {
    tabovi.push(grupaSkladiste())
  }
  if (korisnik?.uloga === 'radnik') {
    // „Moja radiona" maknuta — mehaničar radi isključivo preko WhatsApp poveznice.
    tabovi.push({ do: '/moj-ucinak', ikona: '🏆', txt: t('tab.mojUcinak') })
    tabovi.push({ do: '/nalozi', ikona: '🔧', txt: t('tab.nalozi') })
  }
  // „Radno vrijeme" (evidencija) vidi samo Marina, Akshay i vlasnik (Toni) — ne cijela uloga.
  {
    const un = (korisnik?.korisnicko_ime || '').toLowerCase()
    const im = (korisnik?.ime || '').toLowerCase()
    if (korisnik?.ai_poslovodja || im.includes('akshay') || un === 'akshay' || (im.includes('marina') && im.includes('pejkov'))) {
      tabovi.push({ do: '/evidencija', ikona: '🕒', txt: t('tab.evidencija') })
    }
  }
  // Imenik telefona (samo čitanje, iz Flota OS-a): vlasnik ILI tko ima dodijeljen modul '/imenik'.
  if (korisnik?.imenik) tabovi.push({ do: '/imenik', ikona: '☎️', txt: 'Imenik' })
  // Voditelju Profil ide gore desno (u zaglavlje), ostalima u izbornik.
  if (korisnik?.uloga !== 'voditelj') {
    tabovi.push({ do: '/profil', ikona: '👤', txt: t('tab.profil') })
  }

  // Moduli po korisniku (allow-lista, samo za kartice iz kataloga MODULI).
  // Ako je postavljena: korisnik vidi TOČNO te kartice iz kataloga (može i dobiti
  // i izgubiti). Posebne stavke (grupe, Profil, evidencija, AI…) ostaju po ulozi.
  let vidljiviTabovi = tabovi
  // „Samo Plan radione": korisniku je dodijeljen isključivo modul '/plan' →
  // u izborniku vidi SAMO karticu Plan radione (bez grupa i ostalih kartica).
  const planSamo = Array.isArray(korisnik?.moduli)
    && korisnik.moduli.length === 1 && korisnik.moduli[0] === '/plan'
  if (planSamo) {
    vidljiviTabovi = tabovi.filter((x) => x.do === '/plan')
  } else if (Array.isArray(korisnik?.moduli)) {
    const kataloskiKljucevi = new Set(MODULI.map((m) => m.key))
    const dopusteni = new Set(korisnik.moduli)
    // '/plan' je izuzet iz filtra — njegovu vidljivost odlučuje gornji push (planPristup).
    // '/imenik' isto — odlučuje korisnik.imenik (vlasnik ILI modul).
    // '/slobodni-vozaci' voditelj/poslovođa vide uvijek (nova kartica — ne skriva se starim popisima modula).
    const uvijekSlobodni = korisnik?.uloga === 'voditelj' || korisnik?.uloga === 'poslovodja'
    vidljiviTabovi = tabovi.filter((x) => x.do === '/plan' || x.do === '/imenik' || (uvijekSlobodni && x.do === '/slobodni-vozaci') || !(x.do && kataloskiKljucevi.has(x.do) && !dopusteni.has(x.do)))
    // Prisutni = i top-level i djeca grupa (da se modul ne doda duplo kao zasebna kartica).
    const prisutni = new Set()
    vidljiviTabovi.forEach((x) => { if (x.do) prisutni.add(x.do); if (x.djeca) x.djeca.forEach((d) => prisutni.add(d.do)) })
    for (const m of MODULI) {
      // '/plan' i '/imenik' se dodaju gore (planPristup / korisnik.imenik), ne ovdje.
      if (m.key === '/plan' || m.key === '/imenik' || m.key === '/valjci') continue   // valjci = zasebna app
      if (dopusteni.has(m.key) && !prisutni.has(m.key)) {
        vidljiviTabovi.push({ do: m.key, ikona: m.ikona, txt: m.literal ? m.txt : t(m.txt) })
      }
    }
  }

  // Jedinstven redoslijed kartica za SVE korisnike (bez obzira na ulogu/dodjelu).
  const red = (x) => {
    const i = NAV_RED.indexOf(x.do || ('grupa:' + x.grupa))
    return i === -1 ? 999 : i
  }
  vidljiviTabovi = [...vidljiviTabovi].sort((a, b) => red(a) - red(b))

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
        {navOtvoren && (
          <button type="button" className={'nav-zakljucaj' + (zakljucan ? ' akt' : '')}
            onClick={() => postaviZakljucan(!zakljucan)}
            title={zakljucan ? 'Izbornik ostaje otvoren — klikni za otključavanje' : 'Zaključaj izbornik da ostane otvoren'}>
            <span className="ikona">{zakljucan ? '🔒' : '🔓'}</span>
            <span className="txt">{zakljucan ? 'Izbornik zaključan' : 'Zaključaj izbornik'}</span>
          </button>
        )}
        {vidljiviTabovi.map((item) => {
          if (!item.djeca) {
            const n = paznjaZa(item.do)
            return (
              <NavLink key={item.do} to={item.do} onClick={zatvoriNav}
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
                  <NavLink key={d.do} to={d.do} end={!!d.end} onClick={zatvoriNav}
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
