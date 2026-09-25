import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, useAutoOsvjezi } from '../ui'
import { useT } from '../i18n'

// Evidencija prikapčanja — vlastita stranica.
//  1) „Trenutno" — tko vozi koju prikolicu (zadnji događaj = prikačeno)
//  2) Dnevnik svih događaja (prikačeno/otkačeno) s filterima i ispisom
export default function EvidencijaPrikapcanja() {
  const { t } = useT()
  const [trenutno, setTrenutno] = useState(null)
  const [rows, setRows] = useState(null)
  const [vrsta, setVrsta] = useState('')
  const [q, setQ] = useState('')

  const ucitajTrenutno = () => api.prikapcanjeTrenutno().then(setTrenutno).catch(() => setTrenutno([]))
  const ucitajDnevnik = (v = vrsta) => api.dnevnikPrikapcanja({ vrsta: v, dana: 180 }).then(setRows).catch(() => setRows([]))
  useEffect(() => { ucitajTrenutno(); ucitajDnevnik('') }, [])
  useAutoOsvjezi(() => { ucitajTrenutno(); ucitajDnevnik(vrsta) }, 60000)

  const oznaka = (x) => (x.vrsta === 'prikaceno' ? `🔗 ${t('spremne.prikaceno')}` : `⛓️‍💥 ${t('spremne.otkaceno')}`)
  const kada = (iso) => { try { return new Date(iso).toLocaleString('hr-HR') } catch (_) { return iso } }
  const datumKratko = (iso) => { try { return new Date(iso).toLocaleDateString('hr-HR') } catch (_) { return iso } }

  return (
    <Layout naslov={t('tab.prikapcanje')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('prikapcanje.opis')}</p>

      <NovaPromjena onGotovo={() => { ucitajTrenutno(); ucitajDnevnik(vrsta) }} />

      {/* Trenutno — tko vozi koju prikolicu */}
      {(() => {
        const upit = q.trim().toLowerCase()
        const filtrirano = (trenutno || []).filter((x) => {
          if (!upit) return true
          return [x.kamion_gb, x.kamion_reg, x.prikolica_gb, x.reg, x.vozac]
            .some((v) => (v || '').toString().toLowerCase().includes(upit))
        })
        return (
          <>
            <div className="sekcija-naslov" style={{ marginTop: 0 }}>
              🚚 {t('prikapcanje.trenutno')} {trenutno ? `(${filtrirano.length}${upit ? '/' + trenutno.length : ''})` : ''}
            </div>
            <input
              className="pretraga-input"
              style={{ marginBottom: 8 }}
              placeholder={t('prikapcanje.trazi')}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <div className="karta">
              {trenutno === null ? <Spinner /> : trenutno.length === 0 ? (
                <p className="meta" style={{ margin: 0 }}>{t('prikapcanje.nemaTrenutno')}</p>
              ) : filtrirano.length === 0 ? (
                <p className="meta" style={{ margin: 0 }}>{t('prikapcanje.nemaRezultata')}</p>
              ) : (
                <table className="di-tab">
                  <thead>
                    <tr><th>{t('spremne.kamion')}</th><th>{t('spremne.prikolica')}</th>
                      <th>{t('spremne.vozac')}</th><th>{t('spremne.od')}</th></tr>
                  </thead>
                  <tbody>
                    {filtrirano.map((x) => (
                      <tr key={x.prikolica_gb}>
                        <td><strong>🚚 {x.kamion_gb || '—'}</strong>{x.kamion_reg ? <span className="meta"> · {x.kamion_reg}</span> : ''}</td>
                        <td>🛻 {x.prikolica_gb}{x.reg ? <span className="meta"> · {x.reg}</span> : ''}</td>
                        <td>{x.vozac || '—'}</td>
                        <td>{x.vrijeme ? datumKratko(x.vrijeme) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )
      })()}

      {/* Dnevnik svih događaja */}
      <div className="sekcija-naslov">📋 {t('prikapcanje.dnevnik')}</div>
      <div className="karta">
        <div className="vz-filteri no-print">
          {['', 'prikaceno', 'otkaceno'].map((v) => (
            <button key={v || 'sve'} className={'vz-fil' + (vrsta === v ? ' akt' : '')}
              onClick={() => { setVrsta(v); ucitajDnevnik(v) }}>
              {v === '' ? t('vozila.sve') : v === 'prikaceno' ? t('spremne.prikaceno') : t('spremne.otkaceno')}
            </button>
          ))}
          <button className="btn sekund mali" onClick={() => window.print()}>🖨️ {t('spremne.ispisi')}</button>
        </div>
        {rows === null ? <Spinner /> : rows.length === 0 ? (
          <p className="meta">{t('spremne.nemaEvidencije')}</p>
        ) : (() => {
          const upit = q.trim().toLowerCase()
          const dnevnikFiltriran = rows.filter((x) => {
            if (!upit) return true
            return [x.kamion_gb, x.prikolica_gb, x.vozac, x.lokacija]
              .some((v) => (v || '').toString().toLowerCase().includes(upit))
          })
          if (dnevnikFiltriran.length === 0) {
            return <p className="meta">{t('prikapcanje.nemaRezultata')}</p>
          }
          return (
            <div className="dnevnik-ispis">
              <h3 className="di-naslov">{t('spremne.evidencija')}</h3>
              <table className="di-tab">
                <thead>
                  <tr><th>{t('spremne.kada')}</th><th>{t('spremne.dogadaj')}</th><th>{t('spremne.kamion')}</th>
                    <th>{t('spremne.prikolica')}</th><th>{t('spremne.vozac')}</th><th>{t('spremne.lokacijaKol')}</th></tr>
                </thead>
                <tbody>
                  {dnevnikFiltriran.map((x) => (
                    <tr key={x.id}>
                      <td>{kada(x.vrijeme)}</td>
                      <td>{oznaka(x)}</td>
                      <td>{x.kamion_gb || '—'}</td>
                      <td>{x.prikolica_gb}</td>
                      <td>{x.vozac || '—'}</td>
                      <td>{x.lokacija || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        })()}
      </div>
    </Layout>
  )
}

// Ručni unos promjene prikapčanja: odaberi prikolicu + (novi) kamion → Prikači/Otkači.
// Vozila se biraju iz padajućih popisa (matični popis), da se ne tipka GB.
function NovaPromjena({ onGotovo }) {
  const { t } = useT()
  const [otvoren, setOtvoren] = useState(false)
  const [vozila, setVozila] = useState(null)
  const [prikolicaGb, setPrikolicaGb] = useState('')
  const [kamionGb, setKamionGb] = useState('')
  const [vozac, setVozac] = useState('')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')

  useEffect(() => {
    if (otvoren && vozila === null) api.vozilaRegistar().then(setVozila).catch(() => setVozila([]))
  }, [otvoren, vozila])

  const jePrikolica = (v) => /prikolic/i.test(v.kategorija || '') || /prikolic|šlep|slep/i.test(v.tip || '')
  const jeKamion = (v) => /kamion/i.test(v.kategorija || '')
  const sortGb = (a, b) => {
    const na = parseInt(a.gb, 10), nb = parseInt(b.gb, 10)
    if (!isNaN(na) && !isNaN(nb)) return na - nb
    return (a.gb || '').localeCompare(b.gb || '')
  }
  const prikolice = (vozila || []).filter(jePrikolica).sort(sortGb)
  const kamioni = (vozila || []).filter(jeKamion).sort(sortGb)

  const posalji = async (vrsta) => {
    if (!prikolicaGb) { setGreska(t('prikapcanje.trebaPrikolica')); return }
    if (vrsta === 'prikaceno' && !kamionGb) { setGreska(t('prikapcanje.trebaKamion')); return }
    setRadi(true); setGreska('')
    try {
      await api.zabiljeziPrikapcanje({
        prikolica_gb: prikolicaGb,
        vrsta,
        kamion_gb: vrsta === 'prikaceno' ? kamionGb : null,
        vozac: vozac.trim() || null,
      })
      setPrikolicaGb(''); setKamionGb(''); setVozac(''); setOtvoren(false)
      onGotovo()
    } catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }

  return (
    <div className="karta" style={{ marginBottom: 12 }}>
      <div className="fs-glava" onClick={() => setOtvoren((o) => !o)}>
        <strong>➕ {t('prikapcanje.novaPromjena')}</strong>
        <span className="meta">{otvoren ? '▲' : '▼'}</span>
      </div>
      {otvoren && (
        <div style={{ marginTop: 10 }}>
          {vozila === null ? <Spinner /> : (
            <>
              <label style={{ marginTop: 0 }}>{t('spremne.prikolica')}</label>
              <select className="pretraga-input" value={prikolicaGb} onChange={(e) => setPrikolicaGb(e.target.value)}>
                <option value="">{t('prikapcanje.odaberiPrikolicu')}</option>
                {prikolice.map((v) => (
                  <option key={v.gb} value={v.gb}>{v.gb}{v.registracija ? ` · ${v.registracija}` : ''}</option>
                ))}
              </select>
              <label style={{ marginTop: 8 }}>{t('spremne.kamion')}</label>
              <select className="pretraga-input" value={kamionGb} onChange={(e) => setKamionGb(e.target.value)}>
                <option value="">{t('prikapcanje.odaberiKamion')}</option>
                {kamioni.map((v) => (
                  <option key={v.gb} value={v.gb}>{v.gb}{v.registracija ? ` · ${v.registracija}` : ''}</option>
                ))}
              </select>
              <label style={{ marginTop: 8 }}>{t('spremne.vozac')}</label>
              <input className="pretraga-input" placeholder={t('spremne.vozacOpc')}
                value={vozac} onChange={(e) => setVozac(e.target.value)} />
              {greska && <div className="greska" style={{ marginTop: 6 }}>{greska}</div>}
              <div className="btn-red" style={{ marginTop: 10 }}>
                <button className="btn" disabled={radi} onClick={() => posalji('prikaceno')}>🔗 {t('spremne.prikaceno')}</button>
                <button className="btn sekund" disabled={radi} onClick={() => posalji('otkaceno')}>⛓️‍💥 {t('spremne.otkaceno')}</button>
              </div>
              <p className="meta" style={{ marginTop: 6 }}>{t('prikapcanje.napomenaUnos')}</p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
