import { useState } from 'react'
import { useAuth } from '../auth'
import { useT, JEZICI } from '../i18n'
import { omoguciPush } from '../push'

export default function Login() {
  const { t, jezik, postaviJezik } = useT()
  const { prijava } = useAuth()
  const [ime, setIme] = useState('')
  const [lozinka, setLozinka] = useState('')
  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)

  const posalji = async (e) => {
    e.preventDefault()
    setGreska('')
    setRadi(true)
    try {
      await prijava(ime.trim(), lozinka)
      omoguciPush()
    } catch (err) {
      setGreska(err.message)
    } finally {
      setRadi(false)
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-lang">
        🌐 <select value={jezik} onChange={(e) => postaviJezik(e.target.value)} aria-label={t('profil.jezik')}>
          {JEZICI.map((j) => <option key={j.code} value={j.code}>{j.naziv}</option>)}
        </select>
      </div>
      <div className="login-logo">
        <img src="/bravel-logo.png" alt="Bravel" className="login-logo-img" />
        <h1>{t('app.title')}</h1>
        <p>{t('app.subtitle')}</p>
      </div>
      <form onSubmit={posalji}>
        {greska && <div className="greska">{greska}</div>}
        <label>{t('login.username')}</label>
        <input value={ime} onChange={(e) => setIme(e.target.value)} autoCapitalize="none" autoComplete="username" required />
        <label>{t('login.password')}</label>
        <input type="password" value={lozinka} onChange={(e) => setLozinka(e.target.value)} autoComplete="current-password" required />
        <button className="btn" disabled={radi}>{radi ? t('login.submitting') : t('login.submit')}</button>
      </form>
    </div>
  )
}
