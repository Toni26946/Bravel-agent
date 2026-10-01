import { useEffect, useMemo, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { Spinner } from '../ui'
import { useT } from '../i18n'

// AI Poslovođa — Faza 1: Učinak (shadow), Norme (cijene posla), Postavke.
export default function Poslovodja() {
  const { t } = useT()
  const { korisnik } = useAuth()
  const voditelj = korisnik?.uloga === 'voditelj'
  const [tab, setTab] = useState('ucinak')

  return (
    <Layout naslov={t('tab.poslovodja')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('pos.opis')}</p>
      <div className="pos-tabovi no-print" style={{ marginBottom: 10 }}>
        <button className={'pos-tab' + (tab === 'ucinak' ? ' akt' : '')} onClick={() => setTab('ucinak')}>📊 {t('pos.ucinak')}</button>
        <button className={'pos-tab' + (tab === 'norme' ? ' akt' : '')} onClick={() => setTab('norme')}>💶 {t('pos.norme')}</button>
        <button className={'pos-tab' + (tab === 'postavke' ? ' akt' : '')} onClick={() => setTab('postavke')}>⚙️ {t('pos.postavke')}</button>
      </div>
      {tab === 'ucinak' && <Ucinak t={t} />}
      {tab === 'norme' && <Norme t={t} voditelj={voditelj} />}
      {tab === 'postavke' && <Postavke t={t} voditelj={voditelj} />}
    </Layout>
  )
}

function Ucinak({ t }) {
  const [dana, setDana] = useState(30)
  const [d, setD] = useState(null)
  const ucitaj = (n = dana) => { setD(null); api.ucinak(n).then(setD).catch(() => setD({ redovi: [] })) }
  useEffect(() => { ucitaj(dana) }, [dana])
  const eur = (x) => (x || 0).toLocaleString('hr-HR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })

  return (
    <div>
      <div className="vz-filteri" style={{ marginBottom: 8 }}>
        {[30, 90, 180].map((n) => (
          <button key={n} className={'vz-fil' + (dana === n ? ' akt' : '')} onClick={() => setDana(n)}>{n} {t('pos.dana')}</button>
        ))}
      </div>
      {d && d.shadow && <div className="pos-shadow">🧪 {t('pos.shadowObavijest')}</div>}
      {d === null ? <Spinner /> : d.redovi.length === 0 ? (
        <p className="meta">{t('pos.nemaUcinka')}</p>
      ) : (
        <>
          {d.eur_po_normi === 0 && <div className="pos-upozorenje">⚠️ {t('pos.nemaEur')}</div>}
          <div className="karta">
            <table className="di-tab">
              <thead>
                <tr>
                  <th>#</th><th>{t('pos.radnik')}</th><th>{t('pos.poslova')}</th>
                  <th>{t('pos.normaSati')}</th><th>{t('pos.zarada')}</th>
                </tr>
              </thead>
              <tbody>
                {d.redovi.map((r, i) => (
                  <tr key={r.radnik}>
                    <td>{i + 1}</td>
                    <td><strong>{r.radnik}</strong></td>
                    <td>{r.broj_poslova}</td>
                    <td>{r.norma_sati.toLocaleString('hr-HR')} h</td>
                    <td>{d.eur_po_normi > 0 ? eur(r.procijenjena_zarada) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.bez_norme > 0 && <p className="meta">{t('pos.bezNorme', { n: d.bez_norme })}</p>}
        </>
      )}
    </div>
  )
}

function Norme({ t, voditelj }) {
  const [redovi, setRedovi] = useState(null)
  const [q, setQ] = useState('')
  const [radi, setRadi] = useState(false)
  const ucitaj = () => api.norme().then(setRedovi).catch(() => setRedovi([]))
  useEffect(() => { ucitaj() }, [])

  const filt = useMemo(() => {
    const u = q.trim().toLowerCase()
    return (redovi || []).filter((n) => !u || n.kategorija.toLowerCase().includes(u))
  }, [redovi, q])

  const preracunaj = async () => {
    if (!window.confirm(t('pos.potvrdiPreracun'))) return
    setRadi(true)
    try { await api.preracunajNorme(); ucitaj() } finally { setRadi(false) }
  }

  return (
    <div>
      <p className="meta" style={{ marginTop: 0 }}>{t('pos.normeOpis')}</p>
      <div className="btn-red no-print" style={{ marginBottom: 8, gap: 8 }}>
        <input className="pretraga-input" placeholder={t('pos.traziNorma')} value={q} onChange={(e) => setQ(e.target.value)} />
        {voditelj && <button className="btn sekund mali" disabled={radi} onClick={preracunaj}>🔄 {t('pos.preracunaj')}</button>}
      </div>
      {redovi === null ? <Spinner /> : (
        <div className="karta">
          <table className="di-tab">
            <thead>
              <tr>
                <th>{t('pos.kategorija')}</th><th>{t('pos.uzoraka')}</th>
                <th>{t('pos.medijan')}</th><th>{t('pos.normaMin')}</th>
                {voditelj && <th className="no-print"></th>}
              </tr>
            </thead>
            <tbody>
              {filt.map((n) => (
                <NormaRed key={n.id} n={n} voditelj={voditelj} onPromjena={ucitaj} t={t} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function NormaRed({ n, voditelj, onPromjena, t }) {
  const [v, setV] = useState(n.norma_min)
  const [radi, setRadi] = useState(false)
  const promijenjeno = v !== n.norma_min
  const spremi = async () => {
    setRadi(true)
    try { await api.azurirajNormu(n.id, { norma_min: Number(v) }); onPromjena() } finally { setRadi(false) }
  }
  const vratiAuto = async () => { setRadi(true); try { await api.azurirajNormu(n.id, { rucno: false }); onPromjena() } finally { setRadi(false) } }
  return (
    <tr className={n.broj_uzoraka < 3 ? 'pos-malo' : ''}>
      <td>{n.kategorija}{n.rucno && <span className="pos-znak">{t('pos.rucno')}</span>}</td>
      <td>{n.broj_uzoraka}</td>
      <td className="meta">{n.medijan_min ?? '—'}{n.p60_min ? ` / ${n.p60_min}` : ''}</td>
      <td>
        {voditelj ? (
          <input className="pos-min" type="number" min="0" value={v} onChange={(e) => setV(e.target.value)} />
        ) : (<strong>{n.norma_min}</strong>)} <span className="meta">min</span>
      </td>
      {voditelj && (
        <td className="no-print" style={{ whiteSpace: 'nowrap' }}>
          {promijenjeno && <button className="ikonbtn" disabled={radi} onClick={spremi} title={t('pos.spremi')}>✓</button>}
          {n.rucno && <button className="ikonbtn" disabled={radi} onClick={vratiAuto} title={t('pos.vratiAuto')}>↩️</button>}
        </td>
      )}
    </tr>
  )
}

function Postavke({ t, voditelj }) {
  const [p, setP] = useState(null)
  const [poruka, setPoruka] = useState('')
  useEffect(() => { api.poslovodjaPostavke().then(setP).catch(() => setP({ eur_po_normi: 0, osnovica: 0, shadow: true })) }, [])
  const spremi = async (izmjene) => {
    const az = await api.azurirajPoslovodjaPostavke(izmjene)
    setP(az); setPoruka(t('pos.spremljeno')); setTimeout(() => setPoruka(''), 2000)
  }
  if (!p) return <Spinner />
  return (
    <div className="karta" style={{ maxWidth: 460 }}>
      <label style={{ marginTop: 0 }}>{t('pos.eurPoNormi')}</label>
      <input className="pretraga-input" type="number" min="0" step="0.5" defaultValue={p.eur_po_normi}
        disabled={!voditelj} onBlur={(e) => voditelj && spremi({ eur_po_normi: Number(e.target.value) })} />
      <p className="meta" style={{ marginTop: 4 }}>{t('pos.eurOpis')}</p>

      <label style={{ marginTop: 10 }}>{t('pos.osnovica')}</label>
      <input className="pretraga-input" type="number" min="0" step="10" defaultValue={p.osnovica}
        disabled={!voditelj} onBlur={(e) => voditelj && spremi({ osnovica: Number(e.target.value) })} />
      <p className="meta" style={{ marginTop: 4 }}>{t('pos.osnovicaOpis')}</p>

      <label className="pos-toggle" style={{ marginTop: 12 }}>
        <input type="checkbox" checked={p.shadow} disabled={!voditelj}
          onChange={(e) => voditelj && spremi({ shadow: e.target.checked })} />
        <span>{t('pos.shadowMode')}</span>
      </label>
      <p className="meta" style={{ marginTop: 4 }}>{t('pos.shadowOpis')}</p>
      {poruka && <div className="uspjeh" style={{ marginTop: 8 }}>{poruka}</div>}
    </div>
  )
}
