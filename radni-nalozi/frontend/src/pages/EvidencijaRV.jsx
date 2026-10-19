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

// "8" → "08:00", "830" → "08:30", "8:5" → "08:05", "24" → "24:00", "" → ""
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
  if (h >= 24) return '24:00'   // kraj dana (teren cijeli dan = 00:00–24:00)
  h = Math.max(0, h); m = Math.min(59, Math.max(0, m))
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
function minute(hhmm) {
  if (!hhmm) return null
  const [h, m] = hhmm.split(':'); return parseInt(h, 10) * 60 + parseInt(m, 10)
}
// Lokalni izračun (isti kao na serveru) za trenutni prikaz.
function izracun(od, doo, kod) {
  const a = minute(od), b0 = minute(doo)
  let uk = 0
  if (a != null && b0 != null) { let b = b0; if (b < a) b += 24 * 60; uk = Math.max(0, b - a) / 60 }
  if (kod === 'TER') return { redovni: 0, prekovremeni: 0, teren: r2(uk) }
  if (kod) return { redovni: 0, prekovremeni: 0, teren: 0 }
  if (a == null || b0 == null) return { redovni: 0, prekovremeni: 0, teren: 0 }
  return { redovni: r2(Math.min(uk, 8)), prekovremeni: r2(Math.max(0, uk - 8)), teren: 0 }
}

const PRAG_2H = 2   // dan se broji u "2h+" ako je prekovremenih ≥ ovoliko sati
const SUBOTA = 6    // dow: 6 = subota
const FAKTOR_SUBOTA = 1.5

// Obračunski sati za jedan dan u RADIONI (kod je prazan): samo REDOVNI sati,
// subota ×1,5, ostali ×1. Prekovremeni se NE uključuju (ostaju u svom stupcu),
// teren (TER) i izostanci (GO/BO/PD/OD) također ne ulaze.
function danObrSati(d, dow) {
  if (!d || d.kod) return 0
  const red = d.redovni || 0
  if (red <= 0) return 0
  return dow === SUBOTA ? red * FAKTOR_SUBOTA : red
}

function zbroji(r) {
  let redovno = 0, prekovremeni = 0, teren = 0, radni_dani = 0, go = 0, bo = 0, pd = 0, prekovremeni_2h = 0
  for (const k in r.dani) {
    const d = r.dani[k]
    redovno += d.redovni || 0; prekovremeni += d.prekovremeni || 0; teren += d.teren || 0
    if ((d.redovni || 0) > 0 || (d.prekovremeni || 0) > 0 || (d.teren || 0) > 0) radni_dani += 1
    if ((d.prekovremeni || 0) >= PRAG_2H) prekovremeni_2h += 1
    if (d.kod === 'GO') go += 1; else if (d.kod === 'BO') bo += 1; else if (d.kod === 'PD') pd += 1
  }
  return { ...r, redovno: r2(redovno), prekovremeni: r2(prekovremeni), teren: r2(teren), radni_dani, prekovremeni_2h, go, bo, pd, ukupno_redovnih: r2(redovno) }
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

  // Mjesečni obračunski sati radnika (radiona, subota ×1,5). Samo prikaz.
  const obrSati = (r) => r2(dani.reduce((s, x) => s + danObrSati(r.dani[x.datum], x.dow), 0))

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
                  <th title={t('ev.obrPomoc')}>{t('ev.redovno')}</th>
                  <th title={t('ev.prekovremeni')}>{t('ev.prekShort')}</th>
                  <th title={t('ev.prek2hPomoc')}>{t('ev.prek2h')}</th>
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
                    <td className="ev-zbroj" title={t('ev.obrPomoc')}>{fmt(obrSati(r))}</td>
                    <td className="ev-zbroj">{fmt(r.prekovremeni)}</td>
                    <td className="ev-zbroj">{r.prekovremeni_2h || ''}</td>
                    <td className="ev-zbroj">{fmt(r.teren)}</td>
                    <td className="ev-zbroj">{r.radni_dani || ''}</td>
                    <td className="ev-zbroj">{r.go || ''}</td>
                    <td className="ev-zbroj">{r.bo || ''}</td>
                    <td className="ev-zbroj">{r.pd || ''}</td>
                    {dani.map((x) => (
                      <Celija key={x.d} korisnikId={r.korisnik_id} datum={x.datum}
                        dan={r.dani[x.datum]} vikend={x.vikend} subota={x.dow === SUBOTA}
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

function Celija({ korisnikId, datum, dan, vikend, subota, onSpremljeno, onGreska }) {
  const { t } = useT()
  const [od, setOd] = useState(dan?.od || '')
  const [doo, setDoo] = useState(dan?.do || '')
  const [kod, setKod] = useState(dan?.kod || '')
  const [radi, setRadi] = useState(false)

  // Vrijeme (OD/DO) se upisuje za običan dan i za TEREN; za GO/BO/PD/OD se ne upisuje.
  const vrijemeAktivno = (k) => !k || k === 'TER'

  const spremi = async (polja) => {
    const stanje = { od, do: doo, kod, ...polja }
    const cuvaj = vrijemeAktivno(stanje.kod)
    setRadi(true)
    try {
      const dn = await api.spremiEvidenciju({
        korisnik_id: korisnikId, datum,
        od: cuvaj ? stanje.od : '', do: cuvaj ? stanje.do : '',
        teren: 0, kod: stanje.kod || '',
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

  const c = izracun(od, doo, kod)
  const aktivno = vrijemeAktivno(kod)
  const cls = 'ev-cel' + (vikend ? ' ev-vikend' : '') + (kod ? ' ev-kod ev-kod-' + kod : '') + (radi ? ' ev-radi' : '')

  return (
    <td className={cls}>
      <div className="ev-red1">
        <input className="ev-in" value={aktivno ? od : ''} disabled={!aktivno} placeholder={aktivno ? 'od' : kod}
          onChange={(e) => setOd(e.target.value)} onBlur={(e) => blurVrijeme('od', e.target.value)} />
        <input className="ev-in" value={aktivno ? doo : ''} disabled={!aktivno} placeholder={aktivno ? 'do' : ''}
          onChange={(e) => setDoo(e.target.value)} onBlur={(e) => blurVrijeme('do', e.target.value)} />
      </div>
      <div className="ev-red2">
        <select className="ev-in ev-kodsel-puni" value={kod} title={t('ev.kodPomoc')} onChange={(e) => promijeniKod(e.target.value)}>
          <option value="">–</option>
          <option value="TER">TER</option>
          <option value="GO">GO</option>
          <option value="BO">BO</option>
          <option value="PD">PD</option>
          <option value="OD">OD</option>
        </select>
      </div>
      {kod === 'TER' && c.teren > 0 && (
        <div className="ev-calc"><span className="ev-ter">{fmt(c.teren)} ter</span></div>
      )}
      {!kod && (c.redovni > 0 || c.prekovremeni > 0) && (
        <div className="ev-calc">{fmt(c.redovni)}{c.prekovremeni > 0 && <span className="ev-pre">+{fmt(c.prekovremeni)}</span>}
          {subota && c.redovni > 0 && <span className="ev-obr" title="Subota ×1,5 (samo redovni)"> → {fmt(c.redovni * FAKTOR_SUBOTA)}</span>}
        </div>
      )}
    </td>
  )
}
