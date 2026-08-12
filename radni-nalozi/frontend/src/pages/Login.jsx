import { useState } from 'react'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import { omoguciPush } from '../push'

export default function Login() {
  const { t } = useT()
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
      <div className="login-logo">
        <span className="b">B</span>
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
