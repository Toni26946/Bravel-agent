import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useT } from '../i18n'
import { useAuth } from '../auth'

// Ploča spremnih šlepa: što imamo i gdje. Gore „Za upisati" (tjeramo na upis),
// dolje spremne grupirane po parkingu.
export default function SpremneSlepe() {
  const { t } = useT()
  const nav = useNavigate()
  const { korisnik } = useAuth()
  const [d, setD] = useState(null)
  const [parkinzi, setParkinzi] = useState([])
  const [greska, setGreska] = useState('')

  const ucitaj = () => api.spremneSlepe().then(setD).catch((e) => setGreska(e.message))
  const ucitajParkinge = () => api.parkinzi().then(setParkinzi).catch(() => {})
  useEffect(() => { ucitaj(); ucitajParkinge() }, [])
  useAutoOsvjezi(() => api.spremneSlepe().then(setD).catch(() => {}), 60000)

  if (greska) return <Layout naslov={t('tab.spremne')}><div className="greska">{greska}</div></Layout>
  if (!d) return <Layout naslov={t('tab.spremne')}><Spinner /></Layout>

  const zaUpisati = d.za_upisati || []
  const grupe = d.grupe || []
  const kamioni = d.kamioni || []
  const jeVoditelj = korisnik?.uloga === 'voditelj'

  return (
    <Layout naslov={t('tab.spremne')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('spremne.opis')}</p>

      {jeVoditelj && <Parkinzi parkinzi={parkinzi} onPromjena={ucitajParkinge} />}

      {/* Za upisati — crveno, tjeramo radionicu na upis spremnosti + lokacije */}
      {zaUpisati.length > 0 && (
        <div className="karta sp-upis">
          <div className="sekcija-naslov" style={{ marginTop: 0, color: '#c0392b' }}>
            ⚠ {t('spremne.zaUpisati')} ({zaUpisati.length})
          </div>
          <p className="meta" style={{ marginTop: 0 }}>{t('spremne.zaUpisatiOpis')}</p>
          {zaUpisati.map((s) => (
            <UpisRed key={s.gb} s={s} parkinzi={parkinzi} nav={nav} onGotovo={ucitaj} />
          ))}
        </div>
      )}

      {/* Gotovi kamioni — u krugu radione (GPS); nestaju kad odu */}
      <div className="sekcija-naslov">
        🚚 {t('spremne.kamioni')} ({kamioni.length})
      </div>
      {kamioni.length === 0
        ? <p className="meta">{t('spremne.nemaKamiona')}</p>
        : (
          <div className="karta">
            {kamioni.map((k) => (
              <div className="sp-red" key={k.gb}>
                <div className="sp-info" onClick={() => k.nalog_id && nav(`/nalozi/${k.nalog_id}`)}>
                  <div className="sp-gb">🚚 {k.gb}</div>
                  <div className="meta">
                    {[k.reg, k.tip].filter(Boolean).join(' · ') || '—'}{k.broj ? ` · ${k.broj}` : ''}
                  </div>
                </div>
                {k.lat != null && k.lon != null ? (
                  <a
                    className="sp-gps sp-gps-link"
                    href={`https://www.google.com/maps?q=${k.lat},${k.lon}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={t('spremne.prikaziNaKarti')}
                    onClick={(e) => e.stopPropagation()}
                  >
                    📍 {k.udaljenost_m != null ? `${(k.udaljenost_m / 1000).toFixed(1)} km` : t('spremne.karta')}
                  </a>
                ) : (
                  <span className="sp-gps">
                    {k.udaljenost_m != null
                      ? `📍 ${(k.udaljenost_m / 1000).toFixed(1)} km`
                      : (k.ima_gps ? '📍 radiona' : t('spremne.nemaGps'))}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      <p className="meta" style={{ marginTop: 4 }}>{t('spremne.kamioniOpis', { km: d.kamion_radius_km })}</p>

      <div className="sekcija-naslov">
        🟢 {t('spremne.spremne')} ({d.broj_spremnih})
      </div>
      {grupe.length === 0 && <p className="meta">{t('spremne.nema')}</p>}
      {grupe.map((g) => (
        <div className="karta" key={g.lokacija}>
          <div className="sp-parking">📍 {g.lokacija} <span className="meta">· {g.slepe.length}</span></div>
          {g.slepe.map((s) => (
            <div className="sp-red" key={s.gb}>
              <div className="sp-info" onClick={() => s.nalog_id && nav(`/nalozi/${s.nalog_id}`)}>
                <div className="sp-gb">🛻 {s.gb}</div>
                <div className="meta">
                  {[s.reg, s.tip].filter(Boolean).join(' · ') || '—'}
                  {s.spreman_od ? ` · ${t('spremne.od')} ${s.spreman_od}` : ''}
                </div>
                {s.napomena && <div className="meta sp-nap">📝 {s.napomena}</div>}
              </div>
              <Uzeta gb={s.gb} onGotovo={ucitaj} />
            </div>
          ))}
        </div>
      ))}
    </Layout>
  )
}

// Voditelj upravlja fiksnim popisom parkinga (da se lokacija bira, ne tipka).
function Parkinzi({ parkinzi, onPromjena }) {
  const { t } = useT()
  const [otvoren, setOtvoren] = useState(false)
  const [novi, setNovi] = useState('')
  const [radi, setRadi] = useState(false)

  const dodaj = async () => {
    if (!novi.trim()) return
    setRadi(true)
    try { await api.dodajParking(novi.trim()); setNovi(''); onPromjena() }
    catch (_) { /* tiho */ } finally { setRadi(false) }
  }
  const makni = async (id) => { try { await api.obrisiParking(id); onPromjena() } catch (_) { /* tiho */ } }

  return (
    <div className="karta">
      <div className="fs-glava" onClick={() => setOtvoren((o) => !o)}>
        <strong>🅿️ {t('spremne.parkinzi')} ({parkinzi.length})</strong>
        <span className="meta">{otvoren ? '▲' : '▼'}</span>
      </div>
      {otvoren && (
        <div style={{ marginTop: 8 }}>
          <div className="vz-filteri">
            {parkinzi.map((p) => (
              <span key={p.id} className="fil">
                {p.naziv} <span className="x" style={{ marginLeft: 4 }} onClick={() => makni(p.id)}>×</span>
              </span>
            ))}
            {parkinzi.length === 0 && <span className="meta">{t('spremne.nemaParkinga')}</span>}
          </div>
          <div className="btn-red" style={{ marginTop: 6 }}>
            <input className="pretraga-input" style={{ maxWidth: 220 }} placeholder={t('spremne.noviParking')}
              value={novi} onChange={(e) => setNovi(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') dodaj() }} />
            <button className="btn mali" disabled={radi || !novi.trim()} onClick={dodaj}>➕ {t('spremne.dodajParking')}</button>
          </div>
        </div>
      )}
    </div>
  )
}

// Odabir parkinga iz fiksnog popisa (ili poruka da voditelj prvo doda parking).
function ParkingSelect({ parkinzi, value, onChange }) {
  const { t } = useT()
  if (parkinzi.length === 0) {
    return <div className="meta">{t('spremne.trebaParking')}</div>
  }
  return (
    <select className="pretraga-input" value={value} onChange={(e) => onChange(e.target.value)} autoFocus>
      <option value="">{t('spremne.odaberiParking')}</option>
      {parkinzi.map((p) => <option key={p.id} value={p.naziv}>{p.naziv}</option>)}
    </select>
  )
}

// Redak „za upisati": brzi upis Spremno (+ parking) ili Pokvareno.
function UpisRed({ s, parkinzi, nav, onGotovo }) {
  const { t } = useT()
  const [forma, setForma] = useState(false)
  const [lok, setLok] = useState('')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')

  const spremno = async () => {
    if (!lok.trim()) { setGreska(t('spremne.lokObavezna')); return }
    setRadi(true); setGreska('')
    try { await api.postaviStatusVozila(s.gb, { status: 'spremno', lokacija: lok.trim() }); onGotovo() }
    catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }
  const pokvareno = async () => {
    setRadi(true); setGreska('')
    try { await api.postaviStatusVozila(s.gb, { status: 'pokvareno' }); onGotovo() }
    catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }

  return (
    <div className="sp-upis-red">
      <div className="sp-info" onClick={() => s.nalog_id && nav(`/nalozi/${s.nalog_id}`)}>
        <div className="sp-gb">🛻 {s.gb}</div>
        <div className="meta">{[s.reg, s.tip].filter(Boolean).join(' · ') || '—'}{s.broj ? ` · ${s.broj}` : ''}</div>
      </div>
      {!forma ? (
        <div className="btn-red">
          <button className="btn mali" disabled={radi} onClick={() => setForma(true)}>🟢 {t('spremne.spremnoBtn')}</button>
          <button className="btn sekund mali" disabled={radi} onClick={pokvareno}>🛑 {t('sv.pokvareno')}</button>
        </div>
      ) : (
        <div className="sp-forma">
          <ParkingSelect parkinzi={parkinzi} value={lok} onChange={setLok} />
          {greska && <div className="greska" style={{ margin: '2px 0' }}>{greska}</div>}
          <div className="btn-red" style={{ marginTop: 4 }}>
            <button className="btn mali" disabled={radi} onClick={spremno}>{radi ? '…' : t('common.spremi')}</button>
            <button className="btn sekund mali" disabled={radi} onClick={() => setForma(false)}>{t('common.odustani')}</button>
          </div>
        </div>
      )}
    </div>
  )
}

// „Uzeta" — kamion je odvezao šlepu → vraća se u pogon (Aktivno), skida s ploče.
function Uzeta({ gb, onGotovo }) {
  const { t } = useT()
  const [radi, setRadi] = useState(false)
  const uzmi = async () => {
    setRadi(true)
    try { await api.postaviStatusVozila(gb, { status: 'aktivno' }); onGotovo() }
    catch (_) { /* tiho */ } finally { setRadi(false) }
  }
  return <button className="btn sekund mali" disabled={radi} onClick={uzmi}>{radi ? '…' : t('spremne.uzeta')}</button>
}
