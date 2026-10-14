import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

const eur = (n) => (n == null ? '' : n.toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €')
const broj = (n) => (n == null || n === '' || isNaN(Number(n)) ? (n ?? '') : Number(n).toLocaleString('hr-HR'))
const iso = (d) => d.toISOString().slice(0, 10)
const danasISO = () => iso(new Date())
const prijeDana = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return iso(d) }

// Preseti razdoblja → {od, do}. 'sve' = bez filtra, 'prilagodjeno' = ručni Od/Do.
function rasponZa(kljuc) {
  const d = new Date()
  const danas = iso(d)
  if (kljuc === 'sve') return { od: '', do: '' }
  if (kljuc === '7') return { od: prijeDana(7), do: danas }
  if (kljuc === '14') return { od: prijeDana(14), do: danas }
  if (kljuc === '30') return { od: prijeDana(30), do: danas }
  if (kljuc === 'mjesec') return { od: iso(new Date(d.getFullYear(), d.getMonth(), 1)), do: danas }
  if (kljuc === 'tjedan') {
    const p = new Date(d); p.setDate(p.getDate() - ((p.getDay() + 6) % 7)); return { od: iso(p), do: danas }
  }
  return null
}

export default function SkladisteDashboard() {
  const { t } = useT()
  const [primke, setPrimke] = useState(null)
  const [narucitelji, setNarucitelji] = useState([])
  const [greska, setGreska] = useState('')
  const [razdoblje, setRazdoblje] = useState('sve')   // zadano: prikaži sve (inače se stare primke sakriju)
  const [od, setOd] = useState('')
  const [doDat, setDoDat] = useState('')
  const [samoStari, setSamoStari] = useState(false)
  const [sort, setSort] = useState('dana')   // dana | naziv | iznos | preostalo | dobavljac
  const [unos, setUnos] = useState({})   // { "pid:idx": {gb, kol} }

  const odaberiRazdoblje = (kljuc) => {
    setRazdoblje(kljuc)
    const r = rasponZa(kljuc)
    if (r) { setOd(r.od); setDoDat(r.do) }
  }

  const ucitaj = () => api.primke().then(setPrimke).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj(); api.narucitelji().then(setNarucitelji).catch(() => {}) }, [])

  if (primke === null) return <Layout naslov={t('skl.dashNaslov')}><Spinner /></Layout>

  const danas = new Date()
  const dijelovi = []
  for (const p of primke) {
    const datum = p.datum || (p.kreiran ? p.kreiran.slice(0, 10) : null)
    if (od && datum && datum < od) continue
    if (doDat && datum && datum > doDat) continue
    ;(p.stavke || []).forEach((s, idx) => {
      const prim = parseFloat(s.kolicina) || 0
      const razd = s.razduzenja || []
      const poslano = razd.reduce((a, r) => a + (parseFloat(r.kolicina) || 0), 0)
      const preostalo = Math.round((prim - poslano) * 1000) / 1000
      const gotov = prim > 0 && preostalo <= 0
      const dana = datum ? Math.floor((danas - new Date(datum)) / 86400000) : 0
      const cij = s.cijena == null || s.cijena === '' ? null : parseFloat(s.cijena)
      dijelovi.push({ pid: p.id, idx, artikl: s.artikl, jedinica: s.jedinica || 'kom', cijena: cij,
        iznos: cij == null ? null : Math.round(cij * prim * 100) / 100,
        prim, razd, preostalo, gotov, dana, datum, dobavljac: p.dobavljac, brojOtp: p.broj_otpremnice, narucioId: s.narucio_id })
    })
  }
  let vidljivi = dijelovi
  if (samoStari) vidljivi = dijelovi.filter((x) => !x.gotov && x.dana > 6)
  const usporedba = {
    dana: (a, b) => b.dana - a.dana,
    naziv: (a, b) => (a.artikl || '').localeCompare(b.artikl || '', 'hr'),
    iznos: (a, b) => (b.iznos || 0) - (a.iznos || 0),
    preostalo: (a, b) => b.preostalo - a.preostalo,
    dobavljac: (a, b) => (a.dobavljac || '').localeCompare(b.dobavljac || '', 'hr'),
  }[sort] || ((a, b) => b.dana - a.dana)
  // gotovi (potrošeni) uvijek na dno; unutar grupe po odabranom sortiranju
  vidljivi.sort((a, b) => (a.gotov ? 1 : 0) - (b.gotov ? 1 : 0) || usporedba(a, b))

  const kljuc = (x) => `${x.pid}:${x.idx}`
  const setU = (x, polje, v) => setUnos((p) => ({ ...p, [kljuc(x)]: { ...(p[kljuc(x)] || {}), [polje]: v } }))

  const razduzi = async (x) => {
    const u = unos[kljuc(x)] || {}
    const gb = (u.gb || '').trim()
    const kol = parseFloat(String(u.kol || '').replace(',', '.'))
    if (!gb || !kol) { setGreska(t('skl.unesiGbKol')); return }
    setGreska('')
    try {
      await api.dodajRazduzenje(x.pid, x.idx, { gb, kolicina: kol })
      setUnos((p) => ({ ...p, [kljuc(x)]: { gb: '', kol: '' } }))
      ucitaj()
    } catch (e) { setGreska(e.message) }
  }
  const makniRazd = async (x, ri) => {
    setGreska('')
    try { await api.obrisiRazduzenje(x.pid, x.idx, ri); ucitaj() } catch (e) { setGreska(e.message) }
  }
  const postaviNarucio = async (x, idRaw) => {
    const id = idRaw ? parseInt(idRaw, 10) : null
    setGreska('')
    // Optimistički: odmah prikaži odabir i zadrži ga (bez ponovnog učitavanja
    // cijele liste — to je uzrokovalo treptaj/„vraćanje" na „Naručio…").
    setPrimke((prev) => (prev || []).map((p) => (
      p.id !== x.pid ? p : { ...p, stavke: (p.stavke || []).map((s, i) => (i === x.idx ? { ...s, narucio_id: id } : s)) }
    )))
    try {
      await api.urediStavku(x.pid, x.idx, { narucio_id: id })
    } catch (e) {
      setGreska(e.message)
      ucitaj()   // na grešci vrati stvarno stanje
    }
  }

  return (
    <Layout naslov={t('skl.dashNaslov')}>
      {greska && <div className="greska">{greska}</div>}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
        <div style={{ flex: '1 1 180px' }}>
          <label style={{ marginTop: 0 }}>{t('skl.razdoblje')}</label>
          <select style={{ width: '100%' }} value={razdoblje} onChange={(e) => odaberiRazdoblje(e.target.value)}>
            <option value="sve">{t('skl.rSve')}</option>
            <option value="7">{t('skl.r7')}</option>
            <option value="14">{t('skl.r14')}</option>
            <option value="30">{t('skl.r30')}</option>
            <option value="mjesec">{t('skl.rMjesec')}</option>
            <option value="tjedan">{t('skl.rTjedan')}</option>
            <option value="prilagodjeno">{t('skl.rPrilagodjeno')}</option>
          </select>
        </div>
        <div style={{ flex: '1 1 180px' }}>
          <label style={{ marginTop: 0 }}>{t('skl.sortiraj')}</label>
          <select style={{ width: '100%' }} value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="dana">{t('skl.sNajstariji')}</option>
            <option value="naziv">{t('skl.sNaziv')}</option>
            <option value="iznos">{t('skl.sIznos')}</option>
            <option value="preostalo">{t('skl.sPreostalo')}</option>
            <option value="dobavljac">{t('skl.sDobavljac')}</option>
          </select>
        </div>
        <label className="pos-toggle" style={{ flex: '1 1 220px', marginTop: 0, paddingBottom: 8 }}>
          <input type="checkbox" checked={samoStari} onChange={(e) => setSamoStari(e.target.checked)} />
          {t('skl.stari6')}
        </label>
      </div>

      {razdoblje === 'prilagodjeno' && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 8 }}>
          <div style={{ flex: '1 1 130px' }}>
            <label style={{ marginTop: 0 }}>{t('skl.od')}</label>
            <input type="date" value={od} onChange={(e) => setOd(e.target.value)} />
          </div>
          <div style={{ flex: '1 1 130px' }}>
            <label style={{ marginTop: 0 }}>{t('skl.do')}</label>
            <input type="date" value={doDat} onChange={(e) => setDoDat(e.target.value)} />
          </div>
        </div>
      )}

      <p className="meta" style={{ marginTop: 8 }}>{t('skl.dijelova', { n: vidljivi.length })}</p>

      {vidljivi.length === 0 ? (
        <p className="meta">{t('skl.nemaDijelova')}</p>
      ) : vidljivi.map((x) => {
        const cls = x.gotov ? ' gotov' : (x.dana > 6 ? ' kasni' : '')
        const u = unos[kljuc(x)] || {}
        const narIme = narucitelji.find((n) => n.id === x.narucioId)?.ime
        return (
          <div key={kljuc(x)} className={'skl-dio-red' + cls}>
            <div className="sdr-glava">
              <span className="sdr-naziv" title={x.artikl}>{x.artikl}</span>
              <span className="sdr-meta">
                {x.gotov ? '✓ ' + t('skl.ugradjeno') : `${t('skl.preostalo')}: ${broj(x.preostalo)} ${x.jedinica}`}
                {` · ${t('skl.primljeno')} ${broj(x.prim)}`}
                {x.cijena != null ? ` · ${eur(x.cijena)}/${x.jedinica}` : ''}
                {x.iznos != null ? ` · ${t('skl.iznos')} ${eur(x.iznos)}` : ''}
                {x.datum ? ` · ${t('skl.prijeDana', { n: x.dana })}` : ''}
                {x.brojOtp ? ` · ${x.brojOtp}` : ''}
              </span>
            </div>
            {!x.gotov && (
              <>
                <input className="sdr-gb" value={u.gb || ''} onChange={(e) => setU(x, 'gb', e.target.value)} placeholder={t('skl.gb')} />
                <input className="sdr-kol" type="text" inputMode="decimal" value={u.kol || ''}
                  onChange={(e) => setU(x, 'kol', e.target.value.replace(/[^0-9.,]/g, ''))} placeholder={String(x.preostalo)} />
              </>
            )}
            <div className="sdr-narwrap">
              <select className="sdr-nar" value={x.narucioId || ''} title={t('skl.narucio')}
                onChange={(e) => postaviNarucio(x, e.target.value)}>
                <option value="">{t('skl.narucio')}…</option>
                {narucitelji.map((n) => <option key={n.id} value={n.id}>{n.ime}</option>)}
              </select>
            </div>
            {!x.gotov && (
              <button className="btn mali sdr-btn" onClick={() => razduzi(x)}>{t('skl.razduzi')}</button>
            )}
            {(x.razd.length > 0 || narIme) && (
              <div className="sdr-razd">
                {x.razd.map((r, ri) => (
                  <span key={ri} className="sdr-chip">{t('skl.gb')} {r.gb}: {broj(r.kolicina)}
                    <button className="sdr-chip-x" onClick={() => makniRazd(x, ri)} title="✕">✕</button>
                  </span>
                ))}
                {narIme && <span className="sdr-chip sdr-narchip" title={t('skl.narucio')}>👤 {narIme}</span>}
              </div>
            )}
          </div>
        )
      })}
    </Layout>
  )
}
