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
  const [sort, setSort] = useState({ col: null, dir: 1 })   // col: null=hitnost | 'broj' | k provjere

  const ucitaj = () => api.pregledi().then(setLista).catch((e) => { setGreska(e.message); setLista([]) })
  useEffect(() => { ucitaj() }, [])

  const spremiLokalno = (gb, polja) => setLista((l) => l.map((v) => v.gb === gb ? { ...v, ...polja } : v))

  const sortiraj = (col) => setSort((s) => s.col === col ? { col, dir: -s.dir } : { col, dir: 1 })

  const hitnost = (v) => Math.min(...PROVJERE.map((p) => {
    const d = danaDo(istekZa(v, p)); return d == null ? 1e9 : d
  }))
  const kljuc = (v, col) => {
    if (col === 'broj') { const n = parseInt(v.gb, 10); return isNaN(n) ? [1, String(v.gb)] : [0, n] }
    const p = PROVJERE.find((x) => x.k === col)
    const d = danaDo(istekZa(v, p)); return d == null ? 1e9 : d
  }

  const redci = useMemo(() => {
    if (!lista) return []
    const q = trazi.trim().toLowerCase()
    let r = lista.slice()
    if (q) r = r.filter((v) => (`${v.vozilo || ''} ${v.gb} ${v.registracija || ''}`).toLowerCase().includes(q))
    if (samoIstek) r = r.filter((v) => hitnost(v) <= 30)
    if (sort.col == null) {
      r.sort((a, b) => hitnost(a) - hitnost(b))
    } else {
      r.sort((a, b) => {
        const ka = kljuc(a, sort.col), kb = kljuc(b, sort.col)
        const cmp = Array.isArray(ka) ? (ka[0] - kb[0] || (ka[1] > kb[1] ? 1 : ka[1] < kb[1] ? -1 : 0)) : (ka - kb)
        return cmp * sort.dir
      })
    }
    return r
  }, [lista, trazi, samoIstek, sort])

  const Sorter = ({ col, children }) => (
    <th className={col === 'broj' ? 'pv-vozilo pv-th' : 'pv-th'} onClick={() => sortiraj(col)}>
      {children}{sort.col === col ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}
    </th>
  )

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
              <Sorter col="broj">{t('pv.vozilo')}</Sorter>
              <Sorter col="periodicki">{t('pv.periodicki')}</Sorter>
              <Sorter col="taho">{t('pv.taho')}</Sorter>
              <Sorter col="pp">{t('pv.pp')}</Sorter>
              <Sorter col="reg">{t('pv.reg')}</Sorter>
            </tr>
          </thead>
          <tbody>
            {redci.map((v) => (
              <tr key={v.gb}>
                <td className="pv-vozilo">
                  <div className="pv-naziv">{v.gb}</div>
                  <div className="pv-meta">{[v.vozilo, v.registracija].filter(Boolean).join(' · ')}</div>
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
        <div className="pv-ed-row">
          <input type="date" className="pv-ed-datum" value={datum || ''} onChange={(e) => setDatum(e.target.value)} />
          {p.ip && <input type="number" className="pv-ed-int" min="1" value={inter} title={t('pv.interval')} onChange={(e) => setInter(e.target.value)} />}
        </div>
        <div className="pv-btns">
          <button className="btn mali" onClick={spremi} disabled={radi}>{t('pv.spremi')}</button>
          <button className="btn sekund mali" onClick={() => { setUredi(false); setDatum(v[p.dp] || ''); setInter(v[p.ip] != null ? v[p.ip] : (p.zad || '')) }}>✕</button>
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
