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
        <button className={'pos-tab' + (tab === 'ljestvica' ? ' akt' : '')} onClick={() => setTab('ljestvica')}>🏆 {t('pos.ljestvica')}</button>
        <button className={'pos-tab' + (tab === 'norme' ? ' akt' : '')} onClick={() => setTab('norme')}>💶 {t('pos.norme')}</button>
        <button className={'pos-tab' + (tab === 'postavke' ? ' akt' : '')} onClick={() => setTab('postavke')}>⚙️ {t('pos.postavke')}</button>
      </div>
      {tab === 'ucinak' && <Ucinak t={t} />}
      {tab === 'ljestvica' && <Ljestvica t={t} />}
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

function Ljestvica({ t }) {
  const [dana, setDana] = useState(7)
  const [d, setD] = useState(null)
  useEffect(() => { setD(null); api.ljestvica(dana).then(setD).catch(() => setD({ redovi: [] })) }, [dana])
  const eur = (x) => (x || 0).toLocaleString('hr-HR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
  const medalja = (i) => (i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : i + 1)
  return (
    <div>
      <div className="vz-filteri" style={{ marginBottom: 8 }}>
        {[7, 30, 90].map((n) => (
          <button key={n} className={'vz-fil' + (dana === n ? ' akt' : '')} onClick={() => setDana(n)}>{n} {t('pos.dana')}</button>
        ))}
      </div>
      {d === null ? <Spinner /> : d.redovi.length === 0 ? (
        <p className="meta">{t('pos.ljestvicaPrazno')}</p>
      ) : (
        <>
          {d.eur_po_normi === 0 && <div className="pos-upozorenje">⚠️ {t('pos.nemaEur')}</div>}
          <div className="karta">
            <table className="di-tab">
              <thead>
                <tr><th>#</th><th>{t('pos.radnik')}</th><th>{t('pos.poslova')}</th><th>{t('pos.zarada')}</th></tr>
              </thead>
              <tbody>
                {d.redovi.map((r, i) => (
                  <tr key={r.radnik_id} className={i < 3 ? 'lj-top' : ''}>
                    <td style={{ fontSize: i < 3 ? 18 : 14 }}>{medalja(i)}</td>
                    <td><strong>{r.ime}</strong></td>
                    <td>{r.broj_poslova}</td>
                    <td className="pos-cijena">{eur(r.zarada_eur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="meta" style={{ marginTop: 8 }}>{t('pos.ljestvicaNapo')}</p>
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
      <p className="meta" style={{ marginTop: -4 }}>{t('pos.cijenaOpis')}</p>
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
                <th>{t('pos.cijena')}</th>
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
    <tr className={n.broj_uzoraka < 15 ? 'pos-malo' : ''}>
      <td>{n.kategorija}{n.rucno && <span className="pos-znak">{t('pos.rucno')}</span>}</td>
      <td>{n.broj_uzoraka}{n.broj_uzoraka < 15 && <span className="pos-slab" title={t('pos.slabOpis')}>⚠</span>}</td>
      <td className="meta">{n.medijan_min ?? '—'}{n.p60_min ? ` / ${n.p60_min}` : ''}</td>
      <td>
        {voditelj ? (
          <input className="pos-min" type="number" min="0" value={v} onChange={(e) => setV(e.target.value)} />
        ) : (<strong>{n.norma_min}</strong>)} <span className="meta">min</span>
      </td>
      <td className="pos-cijena">{(n.cijena_eur || 0).toLocaleString('hr-HR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 })}</td>
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
  const [info, setInfo] = useState(null)
  const [rekRadi, setRekRadi] = useState(false)
  const [rekPoruka, setRekPoruka] = useState('')
  useEffect(() => { api.poslovodjaPostavke().then(setP).catch(() => setP({ eur_po_normi: 0, osnovica: 0, shadow: true })) }, [])
  useEffect(() => { api.obracunInfo().then(setInfo).catch(() => setInfo(null)) }, [])
  const spremi = async (izmjene) => {
    const az = await api.azurirajPoslovodjaPostavke(izmjene)
    setP(az); setPoruka(t('pos.spremljeno')); setTimeout(() => setPoruka(''), 2000)
  }
  const rekalibriraj = async () => {
    setRekRadi(true); setRekPoruka('')
    try {
      const r = await api.rekalibriraj()
      if (r.ok && r.valjana) {
        setRekPoruka(t('pos.rekOk', { stopa: r.stopa, n: r.poklopljeno }))
        const [np, ni] = await Promise.all([api.poslovodjaPostavke(), api.obracunInfo()])
        setP(np); setInfo(ni)
      } else {
        setRekPoruka(t('pos.rekLose'))
      }
    } catch { setRekPoruka(t('pos.rekLose')) }
    finally { setRekRadi(false); setTimeout(() => setRekPoruka(''), 6000) }
  }
  if (!p) return <Spinner />
  return (
    <div className="karta" style={{ maxWidth: 460 }}>
      <label style={{ marginTop: 0 }}>{t('pos.eurPoNormi')}</label>
      <input key={p.eur_po_normi} className="pretraga-input" type="number" min="0" step="0.5" defaultValue={p.eur_po_normi}
        disabled={!voditelj} onBlur={(e) => voditelj && spremi({ eur_po_normi: Number(e.target.value) })} />
      <p className="meta" style={{ marginTop: 4 }}>{t('pos.eurOpis')}</p>

      <div className="pos-rekalib">
        <div className="meta" style={{ marginBottom: 6 }}>
          {info && info.zadnji_sync
            ? t('pos.obracunZadnji', { datum: info.zadnji_sync, stopa: info.stopa, n: info.poklopljeno })
            : t('pos.obracunNema')}
        </div>
        {voditelj && (
          <button className="btn sekund mali" disabled={rekRadi} onClick={rekalibriraj}>
            🔄 {t('pos.rekalibriraj')}
          </button>
        )}
        {rekPoruka && <div className="meta" style={{ marginTop: 6 }}>{rekPoruka}</div>}
      </div>

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
