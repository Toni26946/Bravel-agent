import { useEffect, useMemo, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { Spinner, Prazno } from '../ui'
import { useT } from '../i18n'

// Šifrarnik vozača — naša evidencija tko je vozač (ime, sektor, telefon).
// Voditelj dodaje/uređuje/deaktivira; popis puni obrazac zaduženja.
export default function Vozaci() {
  const { t } = useT()
  const { korisnik } = useAuth()
  const uredi = korisnik?.uloga === 'voditelj' || korisnik?.uloga === 'poslovodja'
  const smijeBrisati = korisnik?.uloga === 'voditelj'
  const [redovi, setRedovi] = useState(null)
  const [q, setQ] = useState('')
  const [samoAktivni, setSamoAktivni] = useState(true)
  const [dodaj, setDodaj] = useState(false)

  const ucitaj = () => api.vozaci().then(setRedovi).catch(() => setRedovi([]))
  useEffect(() => { ucitaj() }, [])

  const filt = useMemo(() => {
    const upit = q.trim().toLowerCase()
    return (redovi || []).filter((v) => {
      if (samoAktivni && !v.aktivan) return false
      if (!upit) return true
      return [v.ime, v.sektor, v.telefon].some((x) => (x || '').toString().toLowerCase().includes(upit))
    })
  }, [redovi, q, samoAktivni])

  const brojAktivnih = (redovi || []).filter((v) => v.aktivan).length

  const akcija = uredi ? (
    <button className="btn mali" onClick={() => setDodaj((o) => !o)}>{dodaj ? '×' : '+ ' + t('voz.dodaj')}</button>
  ) : null

  return (
    <Layout naslov={t('tab.vozaci')} akcija={akcija}>
      <p className="meta" style={{ marginTop: 0 }}>{t('voz.opis')}</p>

      {dodaj && uredi && <DodajVozaca onGotovo={() => { setDodaj(false); ucitaj() }} t={t} />}

      <div className="vz-filteri" style={{ marginBottom: 8 }}>
        <button className={'vz-fil' + (samoAktivni ? ' akt' : '')} onClick={() => setSamoAktivni(true)}>{t('voz.aktivni')} ({brojAktivnih})</button>
        <button className={'vz-fil' + (!samoAktivni ? ' akt' : '')} onClick={() => setSamoAktivni(false)}>{t('voz.svi')} ({(redovi || []).length})</button>
      </div>
      <input className="pretraga-input" style={{ marginBottom: 10 }} placeholder={t('voz.trazi')} value={q} onChange={(e) => setQ(e.target.value)} />

      {redovi === null ? <Spinner /> : filt.length === 0 ? (
        <Prazno emo="🧑‍✈️" tekst={q ? t('voz.nemaRezultata') : t('voz.nema')} />
      ) : (
        <div className="karta">
          <table className="di-tab">
            <thead>
              <tr>
                <th>{t('voz.ime')}</th><th>{t('voz.sektor')}</th><th>{t('voz.telefon')}</th>
                {uredi && <th className="no-print"></th>}
              </tr>
            </thead>
            <tbody>
              {filt.map((v) => (
                <Red key={v.id} v={v} uredi={uredi} smijeBrisati={smijeBrisati} onPromjena={ucitaj} t={t} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Layout>
  )
}

function Red({ v, uredi, smijeBrisati, onPromjena, t }) {
  const [edit, setEdit] = useState(false)
  const [ime, setIme] = useState(v.ime)
  const [sektor, setSektor] = useState(v.sektor || '')
  const [telefon, setTelefon] = useState(v.telefon || '')
  const [radi, setRadi] = useState(false)

  const spremi = async () => {
    if (!ime.trim()) return
    setRadi(true)
    try { await api.azurirajVozaca(v.id, { ime, sektor, telefon }); setEdit(false); onPromjena() }
    finally { setRadi(false) }
  }
  const toggle = async () => { await api.azurirajVozaca(v.id, { aktivan: !v.aktivan }); onPromjena() }
  const obrisi = async () => { if (window.confirm(t('voz.potvrdiBrisanje', { ime: v.ime }))) { await api.obrisiVozaca(v.id); onPromjena() } }

  if (edit) {
    return (
      <tr>
        <td><input className="zad-nap-inp" value={ime} onChange={(e) => setIme(e.target.value)} /></td>
        <td><input className="zad-nap-inp" value={sektor} onChange={(e) => setSektor(e.target.value)} placeholder="TEGLJAČ / DIZALICA" /></td>
        <td><input className="zad-nap-inp" value={telefon} onChange={(e) => setTelefon(e.target.value)} /></td>
        <td className="no-print" style={{ whiteSpace: 'nowrap' }}>
          <button className="ikonbtn" disabled={radi} onClick={spremi} title={t('voz.spremi')}>✓</button>
          <button className="ikonbtn" onClick={() => setEdit(false)} title={t('voz.odustani')}>✕</button>
        </td>
      </tr>
    )
  }
  return (
    <tr className={v.aktivan ? '' : 'voz-neaktivan'}>
      <td>{v.ime}{!v.aktivan && <span className="meta"> · {t('voz.neaktivan')}</span>}</td>
      <td>{v.sektor || '—'}</td>
      <td>{v.telefon ? <a href={'tel:' + v.telefon}>{v.telefon}</a> : '—'}</td>
      {uredi && (
        <td className="no-print" style={{ whiteSpace: 'nowrap' }}>
          <button className="ikonbtn" onClick={() => setEdit(true)} title={t('voz.uredi')}>✏️</button>
          <button className="ikonbtn" onClick={toggle} title={v.aktivan ? t('voz.deaktiviraj') : t('voz.aktiviraj')}>{v.aktivan ? '🚫' : '↩️'}</button>
          {smijeBrisati && <button className="ikonbtn" onClick={obrisi} title={t('voz.obrisi')}>🗑️</button>}
        </td>
      )}
    </tr>
  )
}

function DodajVozaca({ onGotovo, t }) {
  const [ime, setIme] = useState('')
  const [sektor, setSektor] = useState('')
  const [telefon, setTelefon] = useState('')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')

  const spremi = async () => {
    if (!ime.trim()) { setGreska(t('voz.trebaIme')); return }
    setRadi(true); setGreska('')
    try { await api.dodajVozaca({ ime, sektor, telefon }); onGotovo() }
    catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }
  return (
    <div className="karta" style={{ marginBottom: 12 }}>
      <label style={{ marginTop: 0 }}>{t('voz.ime')}</label>
      <input className="pretraga-input" value={ime} onChange={(e) => setIme(e.target.value)} placeholder={t('voz.imePh')} />
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <div style={{ flex: 1 }}>
          <label>{t('voz.sektor')}</label>
          <input className="pretraga-input" value={sektor} onChange={(e) => setSektor(e.target.value)} placeholder="TEGLJAČ / DIZALICA" />
        </div>
        <div style={{ flex: 1 }}>
          <label>{t('voz.telefon')}</label>
          <input className="pretraga-input" value={telefon} onChange={(e) => setTelefon(e.target.value)} />
        </div>
      </div>
      {greska && <div className="greska" style={{ marginTop: 6 }}>{greska}</div>}
      <div className="btn-red" style={{ marginTop: 10 }}>
        <button className="btn" disabled={radi} onClick={spremi}>💾 {t('voz.spremi')}</button>
      </div>
    </div>
  )
}
