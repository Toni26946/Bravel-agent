import { useEffect, useMemo, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

const DANI = ['ned', 'pon', 'uto', 'sri', 'čet', 'pet', 'sub']
const MJESECI = ['Siječanj', 'Veljača', 'Ožujak', 'Travanj', 'Svibanj', 'Lipanj',
  'Srpanj', 'Kolovoz', 'Rujan', 'Listopad', 'Studeni', 'Prosinac']

const fmt = (n) => {
  const v = Number(n || 0)
  if (!v) return ''
  return v.toLocaleString('hr-HR', { maximumFractionDigits: 2 })
}
const iso = (g, m, d) => `${g}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`

export default function EvidencijaRV() {
  const { t } = useT()
  const danas = new Date()
  const [godina, setGodina] = useState(danas.getFullYear())
  const [mjesec, setMjesec] = useState(danas.getMonth() + 1)   // 1–12
  const [podaci, setPodaci] = useState(null)
  const [greska, setGreska] = useState('')
  const [uredi, setUredi] = useState(null)     // { korisnik_id, ime, datum }
  const [spremam, setSpremam] = useState(false)

  const ucitaj = () => {
    setPodaci(null)
    api.evidencijaMjesec(godina, mjesec).then(setPodaci).catch((e) => { setGreska(e.message); setPodaci({ radnici: [], dana_u_mjesecu: 0 }) })
  }
  useEffect(ucitaj, [godina, mjesec])

  const dani = useMemo(() => {
    const n = podaci?.dana_u_mjesecu || 0
    return Array.from({ length: n }, (_, i) => {
      const d = i + 1
      const dow = new Date(godina, mjesec - 1, d).getDay()
      return { d, dow, vikend: dow === 0 || dow === 6, datum: iso(godina, mjesec, d) }
    })
  }, [podaci, godina, mjesec])

  const promijeniMjesec = (delta) => {
    let m = mjesec + delta, g = godina
    if (m < 1) { m = 12; g -= 1 }
    if (m > 12) { m = 1; g += 1 }
    setGodina(g); setMjesec(m)
  }

  const izvoz = async () => {
    try {
      const blob = await api.preuzmiEvidencijuExcel(godina, mjesec)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `evidencija-${godina}-${String(mjesec).padStart(2, '0')}.xlsx`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch (e) { setGreska(e.message) }
  }

  const spremi = async (vrijednosti) => {
    setSpremam(true); setGreska('')
    try {
      await api.spremiEvidenciju({ korisnik_id: uredi.korisnik_id, datum: uredi.datum, ...vrijednosti })
      setUredi(null)
      ucitaj()
    } catch (e) { setGreska(e.message) } finally { setSpremam(false) }
  }

  const akcija = (
    <button className="btn mali" onClick={izvoz} disabled={!podaci?.radnici?.length}>{t('ev.izvoz')}</button>
  )

  return (
    <Layout naslov={t('ev.naslov')} akcija={akcija}>
      {greska && <div className="greska">{greska}</div>}

      <div className="ev-alati">
        <button className="btn mali" onClick={() => promijeniMjesec(-1)} aria-label="Prethodni">‹</button>
        <span className="ev-mjesec">{MJESECI[mjesec - 1]} {godina}</span>
        <button className="btn mali" onClick={() => promijeniMjesec(1)} aria-label="Sljedeći">›</button>
        <span className="ev-legenda">{t('ev.legenda')}</span>
      </div>

      {podaci === null ? <Spinner /> : (
        podaci.radnici.length === 0 ? <p className="meta">{t('ev.nemaRadnika')}</p> : (
          <div className="ev-tablica-wrap">
            <table className="ev-tablica">
              <thead>
                <tr>
                  <th className="ev-sticky ev-ime">{t('ev.radnik')}</th>
                  <th title={t('ev.redovno')}>{t('ev.redovno')}</th>
                  <th title={t('ev.prekovremeni')}>{t('ev.prekShort')}</th>
                  <th title={t('ev.teren')}>{t('ev.terenShort')}</th>
                  <th title={t('ev.radniDani')}>d</th>
                  <th>GO</th><th>BO</th><th>PD</th>
                  {dani.map((x) => (
                    <th key={x.d} className={'ev-dan' + (x.vikend ? ' ev-vikend' : '')}>
                      <div className="ev-dan-br">{x.d}</div>
                      <div className="ev-dan-dow">{DANI[x.dow]}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {podaci.radnici.map((r) => (
                  <tr key={r.korisnik_id}>
                    <td className="ev-sticky ev-ime" title={r.ime}>{r.ime}</td>
                    <td className="ev-zbroj">{fmt(r.redovno)}</td>
                    <td className="ev-zbroj">{fmt(r.prekovremeni)}</td>
                    <td className="ev-zbroj">{fmt(r.teren)}</td>
                    <td className="ev-zbroj">{r.radni_dani || ''}</td>
                    <td className="ev-zbroj">{r.go || ''}</td>
                    <td className="ev-zbroj">{r.bo || ''}</td>
                    <td className="ev-zbroj">{r.pd || ''}</td>
                    {dani.map((x) => {
                      const dan = r.dani[x.datum]
                      let sadrzaj = null, cls = 'ev-cel'
                      if (x.vikend) cls += ' ev-vikend'
                      if (dan) {
                        if (dan.kod) { sadrzaj = dan.kod; cls += ' ev-kod ev-kod-' + dan.kod }
                        else {
                          const uk = (dan.redovni || 0) + (dan.prekovremeni || 0)
                          sadrzaj = (
                            <>
                              <span className="ev-sati">{fmt(uk)}</span>
                              {dan.prekovremeni > 0 && <span className="ev-pre">+{fmt(dan.prekovremeni)}</span>}
                              {dan.teren > 0 && <span className="ev-ter">T{fmt(dan.teren)}</span>}
                            </>
                          )
                          cls += ' ev-radio'
                        }
                      }
                      return (
                        <td key={x.d} className={cls}
                          title={dan ? `${dan.od || ''}–${dan.do || ''}` : ''}
                          onClick={() => setUredi({ korisnik_id: r.korisnik_id, ime: r.ime, datum: x.datum, dan })}>
                          {sadrzaj}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {uredi && (
        <UrediDan uredi={uredi} spremam={spremam} onZatvori={() => setUredi(null)} onSpremi={spremi} t={t} />
      )}
    </Layout>
  )
}

function UrediDan({ uredi, spremam, onZatvori, onSpremi, t }) {
  const d0 = uredi.dan || {}
  const [od, setOd] = useState(d0.od || '')
  const [doo, setDoo] = useState(d0.do || '')
  const [teren, setTeren] = useState(d0.teren ? String(d0.teren) : '')
  const [kod, setKod] = useState(d0.kod || '')
  const [napomena, setNapomena] = useState(d0.napomena || '')

  const spremi = () => onSpremi({
    od: kod ? '' : od, do: kod ? '' : doo,
    teren: teren ? parseFloat(String(teren).replace(',', '.')) : 0,
    kod, napomena,
  })
  const isprazni = () => onSpremi({ od: '', do: '', teren: 0, kod: '', napomena: '' })

  const naslov = t('ev.uredi', { ime: uredi.ime, datum: uredi.datum.split('-').reverse().join('.') + '.' })

  return (
    <div className="sheet-bg" onClick={onZatvori}>
      <div className="sheet ev-modal" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{naslov}</h3>

        <label>{t('ev.kod')}</label>
        <select value={kod} onChange={(e) => setKod(e.target.value)}>
          <option value="">{t('ev.kodNema')}</option>
          <option value="GO">{t('ev.koGO')}</option>
          <option value="BO">{t('ev.koBO')}</option>
          <option value="PD">{t('ev.koPD')}</option>
          <option value="OD">{t('ev.koOD')}</option>
        </select>

        {!kod && (
          <div className="ev-vrijeme">
            <div>
              <label>{t('ev.od')}</label>
              <input type="time" value={od} onChange={(e) => setOd(e.target.value)} />
            </div>
            <div>
              <label>{t('ev.do')}</label>
              <input type="time" value={doo} onChange={(e) => setDoo(e.target.value)} />
            </div>
          </div>
        )}

        <label>{t('ev.teren')} ({t('ev.h')})</label>
        <input type="number" step="any" inputMode="decimal" value={teren}
          onChange={(e) => setTeren(e.target.value)} placeholder="0" />

        <label>{t('ev.napomena')}</label>
        <input value={napomena} onChange={(e) => setNapomena(e.target.value)} />

        <div className="ev-modal-akcije">
          <button className="btn" onClick={spremi} disabled={spremam}>{spremam ? '⏳' : t('ev.spremi')}</button>
          <button className="btn sekund" onClick={isprazni} disabled={spremam}>{t('ev.obrisi')}</button>
          <button className="btn sekund" onClick={onZatvori} disabled={spremam}>{t('ev.odustani')}</button>
        </div>
      </div>
    </div>
  )
}
