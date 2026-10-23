import { useEffect, useMemo, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'
import { PROVJERE, danaDo, hrDatum, klasa, istekZa } from '../pregledi'

export default function PregledVozila() {
  const { t } = useT()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [trazi, setTrazi] = useState('')
  const [samoIstek, setSamoIstek] = useState(false)
  const [sort, setSort] = useState({ col: null, dir: 1 })   // col: null=hitnost | 'broj' | k provjere
  const [aktivna, setAktivna] = useState(null)              // "<gb>|<k>" ćelija koja se trenutno uređuje

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
    if (q) r = r.filter((v) => (`${v.vozilo || ''} ${v.gb} ${v.registracija || ''} ${v.vozac || ''}`).toLowerCase().includes(q))
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
                  {v.vozac && <div className="pv-vozac">🧑 {v.vozac}</div>}
                </td>
                {PROVJERE.map((p) => (
                  <Celija
                    key={p.k} v={v} p={p}
                    otvoren={aktivna === v.gb + '|' + p.k}
                    onOtvori={() => setAktivna(v.gb + '|' + p.k)}
                    onZatvori={() => setAktivna(null)}
                    onSpremi={spremiLokalno} onGreska={setGreska}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Layout>
  )
}

function Celija({ v, p, otvoren, onOtvori, onZatvori, onSpremi, onGreska }) {
  const { t } = useT()
  const [datum, setDatum] = useState(v[p.dp] || '')
  const [inter, setInter] = useState(v[p.ip] != null ? v[p.ip] : (p.zad || ''))
  const [radi, setRadi] = useState(false)

  // Kad se ćelija zatvori (npr. klikom na drugu), vrati polja na spremljene vrijednosti.
  useEffect(() => {
    if (!otvoren) {
      setDatum(v[p.dp] || '')
      setInter(v[p.ip] != null ? v[p.ip] : (p.zad || ''))
    }
  }, [otvoren, v, p])

  const istek = istekZa(v, p)
  const dana = danaDo(istek)

  const spremi = async () => {
    setRadi(true)
    try {
      const body = { [p.dp]: datum || null }
      if (p.ip) body[p.ip] = inter ? Number(inter) : null
      await api.urediPregled(v.gb, body)
      onSpremi(v.gb, body)
      onZatvori()
    } catch (e) { onGreska(e.message) } finally { setRadi(false) }
  }

  if (otvoren) {
    return (
      <td className="pv-cel pv-edit">
        <div className="pv-ed-row">
          <input type="date" className="pv-ed-datum" value={datum || ''} onChange={(e) => setDatum(e.target.value)} />
          {p.ip && <input type="number" className="pv-ed-int" min="1" value={inter} title={t('pv.interval')} onChange={(e) => setInter(e.target.value)} />}
        </div>
        <div className="pv-btns">
          <button className="btn mali" onClick={spremi} disabled={radi}>{t('pv.spremi')}</button>
          <button className="btn sekund mali" onClick={onZatvori}>✕</button>
        </div>
      </td>
    )
  }

  return (
    <td className={'pv-cel ' + klasa(dana)} onClick={onOtvori} title={t('pv.uredi')}>
      {istek ? (
        <>
          <div className="pv-istek">{hrDatum(istek)}</div>
          <div className="pv-dana">{dana < 0 ? t('pv.isteklo') : `${dana} ${t('pv.dana')}`}</div>
        </>
      ) : <div className="pv-dana">—</div>}
    </td>
  )
}
