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
const r2 = (n) => Math.round((n || 0) * 100) / 100

// "8" → "08:00", "830" → "08:30", "8:5" → "08:05", "" → ""
function normVrijeme(s) {
  const t = String(s || '').trim()
  if (!t) return ''
  let h, m
  if (t.includes(':')) {
    const [a, b] = t.split(':'); h = parseInt(a, 10); m = parseInt(b || '0', 10)
  } else {
    const c = t.replace(/\D/g, '')
    if (c.length <= 2) { h = parseInt(c, 10); m = 0 }
    else if (c.length === 3) { h = parseInt(c.slice(0, 1), 10); m = parseInt(c.slice(1), 10) }
    else { h = parseInt(c.slice(0, 2), 10); m = parseInt(c.slice(2, 4), 10) }
  }
  if (isNaN(h)) return ''
  if (isNaN(m)) m = 0
  h = Math.min(23, Math.max(0, h)); m = Math.min(59, Math.max(0, m))
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
function minute(hhmm) {
  if (!hhmm) return null
  const [h, m] = hhmm.split(':'); return parseInt(h, 10) * 60 + parseInt(m, 10)
}
// Lokalni izračun (isti kao na serveru) za trenutni prikaz.
function izracun(od, doo, kod) {
  if (kod) return { redovni: 0, prekovremeni: 0 }
  const a = minute(od), b0 = minute(doo)
  if (a == null || b0 == null) return { redovni: 0, prekovremeni: 0 }
  let b = b0; if (b < a) b += 24 * 60
  const uk = Math.max(0, b - a) / 60
  return { redovni: r2(Math.min(uk, 8)), prekovremeni: r2(Math.max(0, uk - 8)) }
}

function zbroji(r) {
  let redovno = 0, prekovremeni = 0, teren = 0, radni_dani = 0, go = 0, bo = 0, pd = 0
  for (const k in r.dani) {
    const d = r.dani[k]
    redovno += d.redovni || 0; prekovremeni += d.prekovremeni || 0; teren += d.teren || 0
    if ((d.redovni || 0) > 0 || (d.prekovremeni || 0) > 0) radni_dani += 1
    if (d.kod === 'GO') go += 1; else if (d.kod === 'BO') bo += 1; else if (d.kod === 'PD') pd += 1
  }
  return { ...r, redovno: r2(redovno), prekovremeni: r2(prekovremeni), teren: r2(teren), radni_dani, go, bo, pd, ukupno_redovnih: r2(redovno) }
}

export default function EvidencijaRV() {
  const { t } = useT()
  const danas = new Date()
  const [godina, setGodina] = useState(danas.getFullYear())
  const [mjesec, setMjesec] = useState(danas.getMonth() + 1)   // 1–12
  const [podaci, setPodaci] = useState(null)
  const [greska, setGreska] = useState('')

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

  // Ćelija je spremila → ažuriraj lokalno stanje (bez ponovnog dohvata).
  const naSpremljeno = (korisnik_id, datum, dan) => {
    setPodaci((p) => {
      if (!p) return p
      const radnici = p.radnici.map((r) => {
        if (r.korisnik_id !== korisnik_id) return r
        const dani2 = { ...r.dani }
        const prazan = !dan || (!dan.od && !dan.do && !dan.kod && !(dan.teren > 0))
        if (prazan) delete dani2[datum]; else dani2[datum] = dan
        return zbroji({ ...r, dani: dani2 })
      })
      return { ...p, radnici }
    })
  }

  const akcija = (
    <button className="btn mali" onClick={izvoz} disabled={!podaci?.radnici?.length}>{t('ev.izvoz')}</button>
  )

  return (
    <Layout naslov={t('ev.naslov')} akcija={akcija}>
      {greska && <div className="greska" onClick={() => setGreska('')}>{greska}</div>}

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
                    {dani.map((x) => (
                      <Celija key={x.d} korisnikId={r.korisnik_id} datum={x.datum}
                        dan={r.dani[x.datum]} vikend={x.vikend}
                        onSpremljeno={naSpremljeno} onGreska={setGreska} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </Layout>
  )
}

function Celija({ korisnikId, datum, dan, vikend, onSpremljeno, onGreska }) {
  const [od, setOd] = useState(dan?.od || '')
  const [doo, setDoo] = useState(dan?.do || '')
  const [kod, setKod] = useState(dan?.kod || '')
  const [teren, setTeren] = useState(dan?.teren ? String(dan.teren) : '')
  const [radi, setRadi] = useState(false)

  const spremi = async (polja) => {
    const stanje = { od, do: doo, kod, teren, ...polja }
    const t = stanje.teren ? parseFloat(String(stanje.teren).replace(',', '.')) : 0
    setRadi(true)
    try {
      const dn = await api.spremiEvidenciju({
        korisnik_id: korisnikId, datum,
        od: stanje.kod ? '' : stanje.od, do: stanje.kod ? '' : stanje.do,
        teren: t || 0, kod: stanje.kod || '',
      })
      onSpremljeno(korisnikId, datum, dn)
    } catch (e) { onGreska(e.message) } finally { setRadi(false) }
  }

  const blurVrijeme = (koje, vrij) => {
    const n = normVrijeme(vrij)
    if (koje === 'od') { if (n === (dan?.od || '')) { setOd(n); return } setOd(n); spremi({ od: n }) }
    else { if (n === (dan?.do || '')) { setDoo(n); return } setDoo(n); spremi({ do: n }) }
  }
  const promijeniKod = (v) => { setKod(v); spremi({ kod: v }) }
  const blurTeren = () => {
    const cur = teren ? String(teren) : ''
    const old = dan?.teren ? String(dan.teren) : ''
    if (cur === old) return
    spremi({ teren })
  }

  const c = izracun(od, doo, kod)
  const cls = 'ev-cel' + (vikend ? ' ev-vikend' : '') + (kod ? ' ev-kod ev-kod-' + kod : '') + (radi ? ' ev-radi' : '')

  return (
    <td className={cls}>
      <div className="ev-red1">
        <input className="ev-in" value={kod ? '' : od} disabled={!!kod} placeholder={kod ? kod : 'od'}
          onChange={(e) => setOd(e.target.value)} onBlur={(e) => blurVrijeme('od', e.target.value)} />
        <input className="ev-in" value={kod ? '' : doo} disabled={!!kod} placeholder={kod ? '' : 'do'}
          onChange={(e) => setDoo(e.target.value)} onBlur={(e) => blurVrijeme('do', e.target.value)} />
      </div>
      <div className="ev-red2">
        <select className="ev-in ev-kodsel" value={kod} onChange={(e) => promijeniKod(e.target.value)}>
          <option value="">–</option>
          <option value="GO">GO</option>
          <option value="BO">BO</option>
          <option value="PD">PD</option>
          <option value="OD">OD</option>
        </select>
        <input className="ev-in ev-teren" value={teren} inputMode="decimal" placeholder="ter"
          onChange={(e) => setTeren(e.target.value)} onBlur={blurTeren} />
      </div>
      {!kod && (c.redovni > 0 || c.prekovremeni > 0) && (
        <div className="ev-calc">{fmt(c.redovni)}{c.prekovremeni > 0 && <span className="ev-pre">+{fmt(c.prekovremeni)}</span>}</div>
      )}
    </td>
  )
}
