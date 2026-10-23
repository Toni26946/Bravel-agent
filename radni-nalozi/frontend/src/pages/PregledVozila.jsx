import { useEffect, useMemo, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

// datum + N mjeseci → ISO (YYYY-MM-DD)
function dodajMjesece(iso, mj) {
  if (!iso || !mj) return null
  const d = new Date(iso + 'T00:00:00')
  if (isNaN(d)) return null
  const dan = d.getDate()
  d.setMonth(d.getMonth() + Number(mj))
  if (d.getDate() < dan) d.setDate(0) // prelio mjesec → zadnji dan prethodnog
  return d.toISOString().slice(0, 10)
}
function danaDo(iso) {
  if (!iso) return null
  const d = new Date(iso + 'T00:00:00')
  if (isNaN(d)) return null
  const danas = new Date(); danas.setHours(0, 0, 0, 0)
  return Math.round((d - danas) / 86400000)
}
function hrDatum(iso) {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  if (isNaN(d)) return iso
  return d.toLocaleDateString('hr-HR')
}
function klasa(dana) {
  if (dana == null) return 'pv-siva'
  if (dana < 0) return 'pv-crvena'
  if (dana <= 30) return 'pv-naranca'
  return 'pv-zelena'
}

// Definicije provjera: datum-polje, interval-polje, zadani interval; registracija je samo datum isteka.
const PROVJERE = [
  { k: 'periodicki', dp: 'periodicki_datum', ip: 'periodicki_int', zad: 3 },
  { k: 'taho', dp: 'taho_datum', ip: 'taho_int', zad: 24 },
  { k: 'pp', dp: 'pp_datum', ip: 'pp_int', zad: 12 },
  { k: 'reg', dp: 'registracija_istek', ip: null, zad: null },
]

function istekZa(v, p) {
  if (p.k === 'reg') return v.registracija_istek || null
  return dodajMjesece(v[p.dp], v[p.ip] || p.zad)
}

export default function PregledVozila() {
  const { t } = useT()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [trazi, setTrazi] = useState('')
  const [samoIstek, setSamoIstek] = useState(false)

  const ucitaj = () => api.pregledi().then(setLista).catch((e) => { setGreska(e.message); setLista([]) })
  useEffect(() => { ucitaj() }, [])

  const spremiLokalno = (gb, polja) => setLista((l) => l.map((v) => v.gb === gb ? { ...v, ...polja } : v))

  const redci = useMemo(() => {
    if (!lista) return []
    const q = trazi.trim().toLowerCase()
    const hitnost = (v) => Math.min(...PROVJERE.map((p) => {
      const d = danaDo(istekZa(v, p)); return d == null ? 1e9 : d
    }))
    let r = lista.map((v) => ({ v, hit: hitnost(v) }))
    if (q) r = r.filter(({ v }) => (`${v.vozilo || ''} ${v.gb} ${v.registracija || ''}`).toLowerCase().includes(q))
    if (samoIstek) r = r.filter(({ hit }) => hit <= 30)
    r.sort((a, b) => a.hit - b.hit)
    return r.map((x) => x.v)
  }, [lista, trazi, samoIstek])

  if (lista === null) return <Layout naslov={t('pv.naslov')}><Spinner /></Layout>

  return (
    <Layout naslov={t('pv.naslov')}>
      {greska && <div className="greska" onClick={() => setGreska('')}>{greska}</div>}
      <div className="pv-alati">
        <input className="pv-trazi" placeholder={t('pv.trazi')} value={trazi} onChange={(e) => setTrazi(e.target.value)} />
        <label className="pv-samo">
          <input type="checkbox" checked={samoIstek} onChange={(e) => setSamoIstek(e.target.checked)} />
          {t('pv.samoIstek')}
        </label>
        <span className="pv-brojilo">{redci.length}</span>
      </div>

      <div className="pv-wrap">
        <table className="pv-tablica">
          <thead>
            <tr>
              <th className="pv-vozilo">{t('pv.vozilo')}</th>
              <th>{t('pv.periodicki')}</th>
              <th>{t('pv.taho')}</th>
              <th>{t('pv.pp')}</th>
              <th>{t('pv.reg')}</th>
            </tr>
          </thead>
          <tbody>
            {redci.map((v) => (
              <tr key={v.gb}>
                <td className="pv-vozilo">
                  <div className="pv-naziv">{v.vozilo || v.gb}</div>
                  <div className="pv-meta">GB {v.gb}{v.registracija ? ` · ${v.registracija}` : ''}</div>
                </td>
                {PROVJERE.map((p) => (
                  <Celija key={p.k} v={v} p={p} onSpremi={spremiLokalno} onGreska={setGreska} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Layout>
  )
}

function Celija({ v, p, onSpremi, onGreska }) {
  const { t } = useT()
  const [uredi, setUredi] = useState(false)
  const [datum, setDatum] = useState(v[p.dp] || '')
  const [inter, setInter] = useState(v[p.ip] != null ? v[p.ip] : (p.zad || ''))
  const [radi, setRadi] = useState(false)

  const istek = istekZa(v, p)
  const dana = danaDo(istek)

  const spremi = async () => {
    setRadi(true)
    try {
      const body = { [p.dp]: datum || null }
      if (p.ip) body[p.ip] = inter ? Number(inter) : null
      await api.urediPregled(v.gb, body)
      onSpremi(v.gb, body)
      setUredi(false)
    } catch (e) { onGreska(e.message) } finally { setRadi(false) }
  }

  if (uredi) {
    return (
      <td className="pv-cel pv-edit">
        <input type="date" value={datum || ''} onChange={(e) => setDatum(e.target.value)} />
        {p.ip && (
          <label className="pv-int">{t('pv.interval')}
            <input type="number" min="1" value={inter} onChange={(e) => setInter(e.target.value)} />
          </label>
        )}
        <div className="pv-btns">
          <button className="btn mali" onClick={spremi} disabled={radi}>{t('pv.spremi')}</button>
          <button className="btn sekund mali" onClick={() => { setUredi(false); setDatum(v[p.dp] || ''); setInter(v[p.ip] != null ? v[p.ip] : (p.zad || '')) }}>{t('pv.odustani')}</button>
        </div>
      </td>
    )
  }

  return (
    <td className={'pv-cel ' + klasa(dana)} onClick={() => setUredi(true)} title={t('pv.uredi')}>
      {istek ? (
        <>
          <div className="pv-istek">{hrDatum(istek)}</div>
          <div className="pv-dana">{dana < 0 ? t('pv.isteklo') : `${dana} ${t('pv.dana')}`}</div>
        </>
      ) : <div className="pv-dana">—</div>}
    </td>
  )
}
