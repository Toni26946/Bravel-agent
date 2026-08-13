import { useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { JEZICI, useT } from '../i18n'
import { omoguciPush } from '../push'

export default function Profil() {
  const { korisnik, odjava } = useAuth()
  const { t, jezik, postaviJezik } = useT()
  const [poruka, setPoruka] = useState('')

  const ukljuciObavijesti = async () => {
    await omoguciPush()
    if (Notification.permission === 'granted') setPoruka(t('profil.pushOn'))
    else setPoruka(t('profil.pushNo'))
  }

  return (
    <Layout naslov={t('profil.title')}>
      <div className="karta">
        <h3>{korisnik.ime}</h3>
        <p className="meta">{t('profil.korime')}: <strong>{korisnik.korisnicko_ime}</strong></p>
        <p className="meta">{t('profil.uloga')}: <strong>{t('uloga.' + korisnik.uloga)}</strong></p>
        {korisnik.telefon && <p className="meta">{t('profil.telefon')}: <strong>{korisnik.telefon}</strong></p>}
      </div>

      <div className="karta">
        <label style={{ marginTop: 0 }}>🌐 {t('profil.jezik')}</label>
        <select value={jezik} onChange={(e) => postaviJezik(e.target.value)}>
          {JEZICI.map((j) => <option key={j.code} value={j.code}>{j.naziv}</option>)}
        </select>
      </div>

      {poruka && <div className="uspjeh">{poruka}</div>}

      <PromjenaLozinke />

      <button className="btn sekund" onClick={ukljuciObavijesti} style={{ marginTop: 12 }}>{t('profil.push')}</button>
      <button className="btn opasno" onClick={odjava} style={{ marginTop: 12 }}>{t('profil.odjava')}</button>

      <p className="meta" style={{ textAlign: 'center', marginTop: 24 }}>{t('profil.savjetInstall')}</p>
    </Layout>
  )
}

function PromjenaLozinke() {
  const { t } = useT()
  const [otvori, setOtvori] = useState(false)
  const [stara, setStara] = useState('')
  const [nova, setNova] = useState('')
  const [potvrda, setPotvrda] = useState('')
  const [greska, setGreska] = useState('')
  const [uspjeh, setUspjeh] = useState('')
  const [radi, setRadi] = useState(false)

  if (!otvori) {
    return (
      <button className="btn sekund" onClick={() => setOtvori(true)} style={{ marginTop: 12 }}>
        {t('profil.promijeniLozinku')}
      </button>
    )
  }

  const spremi = async (e) => {
    e.preventDefault()
    setGreska(''); setUspjeh('')
    if (nova.length < 8) { setGreska(t('profil.lozKratka')); return }
    if (nova !== potvrda) { setGreska(t('profil.lozNePodudara')); return }
    setRadi(true)
    try {
      await api.promijeniLozinku(stara, nova)
      setUspjeh(t('profil.lozPromijenjena'))
      setStara(''); setNova(''); setPotvrda('')
      setOtvori(false)
    } catch (err) {
      setGreska(err.message)
    } finally {
      setRadi(false)
    }
  }

  return (
    <form className="karta" onSubmit={spremi} style={{ marginTop: 12 }}>
      <h3 style={{ marginTop: 0 }}>{t('profil.promjenaLozinke')}</h3>
      {greska && <div className="greska">{greska}</div>}
      {uspjeh && <div className="uspjeh">{uspjeh}</div>}
      <label>{t('profil.trenutnaLoz')}</label>
      <input type="password" value={stara} onChange={(e) => setStara(e.target.value)} autoComplete="current-password" required />
      <label>{t('profil.novaLoz')}</label>
      <input type="password" value={nova} onChange={(e) => setNova(e.target.value)} autoComplete="new-password" required />
      <label>{t('profil.ponoviLoz')}</label>
      <input type="password" value={potvrda} onChange={(e) => setPotvrda(e.target.value)} autoComplete="new-password" required />
      <div className="btn-red">
        <button className="btn mali" disabled={radi}>{radi ? t('common.spremam') : t('common.spremi')}</button>
        <button type="button" className="btn sekund mali" onClick={() => { setOtvori(false); setGreska('') }}>{t('common.odustani')}</button>
      </div>
    </form>
  )
}
