import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, datumVrijeme } from '../ui'
import { useT } from '../i18n'

// Evidencija parkiranja nezaduženih šlepa: poslano / otvoreno / riješeno + lokacija, s ispisom.
export default function Parkiranje() {
  const { t } = useT()
  const nav = useNavigate()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')

  const ucitaj = () => api.parkiranje().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => {
    // Otvaranjem stranice bilježimo da je voditelj primio/otvorio obavijest.
    api.parkiranje().then(async (l) => {
      const neotvoreni = l.filter((n) => n.parking_obavijest_poslano && !n.parking_otvoreno)
      if (neotvoreni.length) {
        await Promise.all(neotvoreni.map((n) => api.parkingOtvoreno(n.id).catch(() => {})))
        return ucitaj()
      }
      setLista(l)
    }).catch((e) => setGreska(e.message))
  }, [])

  if (greska) return <Layout naslov={t('tab.parkiranje')}><div className="greska">{greska}</div></Layout>
  if (!lista) return <Layout naslov={t('tab.parkiranje')}><Spinner /></Layout>

  const zaRijesiti = lista.filter((n) => !n.parking_rijeseno)
  const rijeseni = lista.filter((n) => n.parking_rijeseno)

  return (
    <Layout naslov={t('tab.parkiranje')}>
      <div className="btn-red no-print" style={{ marginTop: 0 }}>
        <button className="btn sekund mali" onClick={() => window.print()}>🖨️ {t('parking.ispisi')}</button>
      </div>

      <div className="sekcija-naslov no-print">{t('parking.zaRijesiti')} ({zaRijesiti.length})</div>
      {zaRijesiti.length === 0 ? (
        <div className="karta no-print"><p className="meta" style={{ margin: 0 }}>{t('parking.nemaZa')}</p></div>
      ) : (
        zaRijesiti.map((n) => <RedZaRijesiti key={n.id} n={n} onGotovo={ucitaj} nav={nav} t={t} />)
      )}

      <div className="sekcija-naslov no-print">{t('parking.evidencija')} ({rijeseni.length})</div>
      {rijeseni.map((n) => (
        <div className="karta no-print" key={n.id} onClick={() => nav(`/nalozi/${n.id}`)}>
          <div className="naslov-red">
            <h3 style={{ margin: 0 }}>🛻 {n.vozilo?.gb} <span className="pk-lok">📍 {n.parking_lokacija}</span></h3>
            <span className="meta">{n.broj}</span>
          </div>
          <div className="pk-vremena">
            <span>{t('parking.poslano')}: {datumVrijeme(n.parking_obavijest_poslano)}</span>
            <span>{t('parking.otvoreno')}: {n.parking_otvoreno ? datumVrijeme(n.parking_otvoreno) : '—'}</span>
            <span>{t('parking.rijeseno')}: {datumVrijeme(n.parking_rijeseno)}</span>
          </div>
        </div>
      ))}

      {/* Ispis: čista tablica cijele evidencije */}
      <ParkingIspis lista={lista} t={t} />
    </Layout>
  )
}

function RedZaRijesiti({ n, onGotovo, nav, t }) {
  const [lok, setLok] = useState('')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')

  const spremi = async () => {
    if (!lok.trim()) { setGreska(t('parking.upisiLok')); return }
    setRadi(true); setGreska('')
    try { await api.parkingLokacija(n.id, lok.trim()); onGotovo() }
    catch (e) { setGreska(e.message); setRadi(false) }
  }

  return (
    <div className="karta no-print">
      <div className="naslov-red">
        <h3 style={{ margin: 0, cursor: 'pointer' }} onClick={() => nav(`/nalozi/${n.id}`)}>🛻 {n.vozilo?.gb}</h3>
        <span className="meta">{n.broj}</span>
      </div>
      <div className="pk-vremena">
        <span>{t('parking.poslano')}: {datumVrijeme(n.parking_obavijest_poslano)}</span>
        <span>{t('parking.otvoreno')}: {n.parking_otvoreno ? datumVrijeme(n.parking_otvoreno) : '—'}</span>
      </div>
      {greska && <div className="greska">{greska}</div>}
      <label style={{ marginTop: 8 }}>{t('parking.gdjeParkirano')}</label>
      <div className="polje-mik">
        <input value={lok} onChange={(e) => setLok(e.target.value)} placeholder={t('parking.phLok')} />
      </div>
      <div className="btn-red">
        <button className="btn mali" disabled={radi} onClick={spremi}>{radi ? '…' : t('parking.spremiLok')}</button>
      </div>
    </div>
  )
}

function ParkingIspis({ lista, t }) {
  return (
    <div className="parking-ispis">
      <div className="np-head">
        <div className="np-tvrtka">
          <img className="np-logo-img" src="/bravel-logo.png" alt="Bravel d.o.o." />
          <div className="np-adresa">Bravel d.o.o. · Zagrebačka 146, 10340 Vrbovec</div>
        </div>
      </div>
      <h2 className="np-naslov">{t('parking.ispisNaslov')}</h2>
      <table className="np-tablica">
        <thead>
          <tr>
            <th>GB</th><th>Nalog</th><th>{t('parking.poslano')}</th>
            <th>{t('parking.otvoreno')}</th><th>{t('parking.rijeseno')}</th><th>{t('parking.lokacija')}</th>
          </tr>
        </thead>
        <tbody>
          {lista.length === 0 && <tr><td colSpan={6} className="np-prazno">—</td></tr>}
          {lista.map((n) => (
            <tr key={n.id}>
              <td>{n.vozilo?.gb}</td>
              <td>{n.broj}</td>
              <td>{datumVrijeme(n.parking_obavijest_poslano)}</td>
              <td>{n.parking_otvoreno ? datumVrijeme(n.parking_otvoreno) : '—'}</td>
              <td>{n.parking_rijeseno ? datumVrijeme(n.parking_rijeseno) : '—'}</td>
              <td>{n.parking_lokacija || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
