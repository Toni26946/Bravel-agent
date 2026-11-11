import { useEffect, useRef, useState } from 'react'
import Layout from '../Layout'
import { api, medijUrl } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

const praznaStavka = () => ({ artikl: '', kolicina: 1, jedinica: 'kom', cijena: '' })

// --- Narudžbe (dijelovi upisani iz naloga) — skladištar vidi i obrađuje ---
const NAR_ST = {
  trazeno: { t: '🟠 za naručiti', c: '#b45309', b: '#fff2db' },
  naruceno: { t: '🔵 naručeno', c: '#1d4ed8', b: '#e5edff' },
  stiglo: { t: '🟢 stiglo', c: '#047857', b: '#dcfce7' },
}
function NarBadge({ s }) {
  const o = NAR_ST[s] || NAR_ST.trazeno
  return <span style={{ fontSize: 11, fontWeight: 700, color: o.c, background: o.b, borderRadius: 999, padding: '2px 8px', whiteSpace: 'nowrap' }}>{o.t}</span>
}
function NarudzbeSkladiste() {
  const [data, setData] = useState(null)
  const [sveStatuse, setSveStatuse] = useState(false)   // prikaži i stigle
  const [greska, setGreska] = useState('')
  const ucitaj = () => api.narudzbe().then(setData).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])
  const postavi = async (id, status) => { try { await api.narudzbaStatus(id, status); ucitaj() } catch (e) { setGreska(e.message) } }

  const svi = data || []
  const vidljive = sveStatuse ? svi : svi.filter((n) => n.status !== 'stiglo')
  const otvorene = svi.filter((n) => n.status === 'trazeno').length
  const grupe = {}
  vidljive.forEach((n) => { const g = n.vozilo_gb || '—'; (grupe[g] = grupe[g] || []).push(n) })
  const gbs = Object.keys(grupe).sort()

  return (
    <div className="karta" style={{ marginBottom: 14, borderLeft: '4px solid #1d4ed8' }}>
      <div className="naslov-red" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>📦 Narudžbe{otvorene ? ` (${otvorene} za naručiti)` : ''}</h3>
        <label className="meta" style={{ cursor: 'pointer' }}><input type="checkbox" checked={sveStatuse} onChange={(e) => setSveStatuse(e.target.checked)} /> i stigle</label>
      </div>
      <p className="meta" style={{ marginTop: 2 }}>Dijelovi koje su mehaničari/voditelji upisali u naloge. Pritisni „Naručeno" kad pošalješ narudžbu, „Stiglo" kad dio dođe.</p>
      {greska && <div className="greska">{greska}</div>}
      {data === null ? <Spinner /> : vidljive.length === 0 ? <p className="meta">Nema otvorenih narudžbi.</p> : (
        gbs.map((gb) => (
          <div key={gb} className="karta" style={{ padding: 10, marginTop: 8 }}>
            <div><strong>🚚 GB {gb}</strong>{grupe[gb][0].broj_naloga ? <span className="meta"> · nalog {grupe[gb][0].broj_naloga}</span> : ''}</div>
            {grupe[gb].map((n) => (
              <div key={n.id} style={{ borderTop: '1px solid var(--line,#eee)', paddingTop: 6, marginTop: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
                  <div>
                    <div><strong>{n.kolicina} {n.jmj}</strong> · {n.naziv}{n.kataloski ? <span className="meta"> · {n.kataloski}</span> : ''}</div>
                    {n.napomena ? <div className="meta">{n.napomena}</div> : null}
                    <div className="meta">tražio {n.trazio || '—'}{n.trazeno ? ` · ${new Date(n.trazeno).toLocaleDateString('hr-HR')}` : ''}</div>
                    {(n.fotografije || []).length > 0 && (
                      <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                        {n.fotografije.map((f, j) => (<a key={j} href={medijUrl(f)} target="_blank" rel="noreferrer"><img src={medijUrl(f)} alt="" style={{ width: 44, height: 44, objectFit: 'cover', borderRadius: 4, border: '1px solid var(--line,#ddd)' }} /></a>))}
                      </div>
                    )}
                  </div>
                  <NarBadge s={n.status} />
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                  {n.status === 'trazeno' && <button className="btn mali" onClick={() => postavi(n.id, 'naruceno')}>🔵 Naručeno</button>}
                  {n.status !== 'stiglo' && <button className="btn mali" onClick={() => postavi(n.id, 'stiglo')}>🟢 Stiglo</button>}
                  {n.status !== 'trazeno' && <button className="btn sekund mali" onClick={() => postavi(n.id, 'trazeno')}>↩︎ Vrati</button>}
                </div>
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  )
}

// --- Zalihe iz APROSS-a (uživo) — proširiva kartica na vrhu Skladišta ---
function ZaliheAPROSS() {
  const [otvoreno, setOtvoreno] = useState(false)
  const [data, setData] = useState(null)
  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)
  const [q, setQ] = useState('')
  const [nule, setNule] = useState(false)          // prikaži i artikle sa stanjem 0
  const [otvSkl, setOtvSkl] = useState({})         // koja su skladišta proširena

  const ucitaj = (opt = {}) => {
    setGreska(''); setRadi(true)
    api.arossZalihe({ nule: nule ? 1 : 0, osvjezi: opt.osvjezi ? 1 : 0 })
      .then((d) => setData(d)).catch((e) => setGreska(e.message)).finally(() => setRadi(false))
  }
  const prebaci = () => { const n = !otvoreno; setOtvoreno(n); if (n && data === null) ucitaj() }
  const prebaciNule = () => { const n = !nule; setNule(n); setRadi(true); setGreska(''); api.arossZalihe({ nule: n ? 1 : 0 }).then(setData).catch((e) => setGreska(e.message)).finally(() => setRadi(false)) }
  const prebaciSkl = (id) => setOtvSkl((p) => ({ ...p, [id]: !p[id] }))

  const s = q.trim().toLowerCase()
  const filtrirano = (arts) => {
    if (!s) return arts
    return arts.filter((a) => (a.naziv || '').toLowerCase().includes(s) || String(a.sifra).includes(s) || (a.kataloskiBroj || '').toLowerCase().includes(s))
  }

  return (
    <div className="karta" style={{ marginBottom: 14 }}>
      <div className="naslov-red" style={{ cursor: 'pointer' }} onClick={prebaci}>
        <h3 style={{ margin: 0 }}>📦 Zalihe (APROSS) {otvoreno ? '▾' : '▸'}</h3>
        {otvoreno && <button className="btn mali" onClick={(e) => { e.stopPropagation(); ucitaj({ osvjezi: true }) }} disabled={radi}>↻ Osvježi</button>}
      </div>

      {otvoreno && (
        <div style={{ marginTop: 8 }}>
          {greska && <div className="greska">{greska}</div>}
          {radi && data === null && <Spinner />}
          {data && data.povezano === false && <p className="meta">APROSS nije povezan. Postavi ključ u Šifrarnik → Integracije.</p>}
          {data && data.povezano && data.skladista.length === 0 && <p className="meta">Nema zaliha za prikaz.</p>}
          {data && data.povezano && data.skladista.length > 0 && (
            <>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Traži artikl, šifru, kataloški broj…" style={{ marginBottom: 6 }} />
              <label className="meta" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10, cursor: 'pointer' }}>
                <input type="checkbox" checked={nule} onChange={prebaciNule} /> prikaži i artikle sa stanjem 0
              </label>
              {data.skladista.map((sk) => {
                const arts = filtrirano(sk.artikli)
                if (s && arts.length === 0) return null       // pri pretrazi skrij prazna skladišta
                const open = !!otvSkl[sk.sifra] || !!s          // pretraga automatski proširi
                return (
                  <div key={sk.sifra} style={{ marginBottom: 6, border: '1px solid var(--line, #eee)', borderRadius: 8 }}>
                    <div onClick={() => prebaciSkl(sk.sifra)} style={{ cursor: 'pointer', padding: '8px 10px', fontWeight: 700, display: 'flex', justifyContent: 'space-between' }}>
                      <span>{open ? '▾' : '▸'} {sk.naziv}</span>
                      <span className="meta">{(sk.kolicina ?? sk.ukupno)} na stanju · {(sk.artikala ?? sk.ukupno)} artikala{s ? ` · ${arts.length} nađeno` : ''}</span>
                    </div>
                    {open && (
                      arts.length === 0 ? <p className="meta" style={{ padding: '0 10px 8px' }}>—</p> : (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                          <tbody>
                            {arts.map((a) => (
                              <tr key={a.sifra} style={{ borderTop: '1px solid var(--line, #eee)' }}>
                                <td style={{ padding: '4px 10px' }}>
                                  {a.naziv}
                                  {a.kataloskiBroj ? <span className="meta"> · {a.kataloskiBroj}</span> : ''}
                                </td>
                                <td style={{ padding: '4px 10px', textAlign: 'right', fontWeight: 700, whiteSpace: 'nowrap', color: a.stanje < 0 ? 'var(--crveno)' : 'inherit' }}>
                                  {a.stanje}{a.jmj ? ` ${a.jmj}` : ''}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}
                  </div>
                )
              })}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// Iznos retka = količina × cijena (null ako nema cijene).
// --- Trošak dijelova po vozilu (iz razduženja) — proširiva kartica ---
function TrosakPoVozilu() {
  const [otvoreno, setOtvoreno] = useState(false)
  const [data, setData] = useState(null)
  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)
  const [otv, setOtv] = useState({})

  const ucitaj = () => { setGreska(''); setRadi(true); api.trosakPoVozilu().then(setData).catch((e) => setGreska(e.message)).finally(() => setRadi(false)) }
  const prebaci = () => { const n = !otvoreno; setOtvoreno(n); if (n && data === null) ucitaj() }
  const eur = (n) => (n == null ? '—' : Number(n).toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €')

  return (
    <div className="karta" style={{ marginBottom: 14 }}>
      <div className="naslov-red" style={{ cursor: 'pointer' }} onClick={prebaci}>
        <h3 style={{ margin: 0 }}>💶 Trošak dijelova po vozilu {otvoreno ? '▾' : '▸'}</h3>
        {otvoreno && <button className="btn mali" onClick={(e) => { e.stopPropagation(); ucitaj() }} disabled={radi}>↻ Osvježi</button>}
      </div>
      {otvoreno && (
        <div style={{ marginTop: 8 }}>
          {greska && <div className="greska">{greska}</div>}
          {radi && data === null && <Spinner />}
          {data && (data.redovi || []).length === 0 && <p className="meta">Još nema razduženih dijelova na vozila.</p>}
          {data && (data.redovi || []).length > 0 && (
            <>
              <p className="meta" style={{ marginTop: 0 }}>Ukupno razduženo: <b>{eur(data.ukupno_eur)}</b> · izvor koji Flota čita za trošak po kamionu.</p>
              {data.redovi.map((r) => (
                <div key={r.gb} style={{ border: '1px solid var(--line, #eee)', borderRadius: 8, marginBottom: 6 }}>
                  <div onClick={() => setOtv((p) => ({ ...p, [r.gb]: !p[r.gb] }))} style={{ cursor: 'pointer', padding: '8px 10px', display: 'flex', justifyContent: 'space-between', fontWeight: 700 }}>
                    <span>{otv[r.gb] ? '▾' : '▸'} 🚚 GB {r.gb}</span>
                    <span>{eur(r.iznos)} <span className="meta" style={{ fontWeight: 400 }}>· {r.stavki} stavki</span></span>
                  </div>
                  {otv[r.gb] && (
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <tbody>
                        {r.stavke.map((s, i) => (
                          <tr key={i} style={{ borderTop: '1px solid var(--line, #eee)' }}>
                            <td style={{ padding: '4px 10px' }}>{s.artikl}<span className="meta"> · {s.datum || ''}{s.dobavljac ? ' · ' + s.dobavljac : ''}</span></td>
                            <td style={{ padding: '4px 10px', textAlign: 'right', whiteSpace: 'nowrap' }}>{s.kolicina} × {eur(s.cijena)} = <b>{eur(s.iznos)}</b></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// Generička tražilica s padajućim rezultatima (artikl / dobavljač iz Aprossa).
// onKreiraj(q) — opcionalno: ponudi kreiranje novog zapisa (vrati kreirani objekt).
function Trazilica({ placeholder, trazi, opis, onPick, pocetni = '', onKreiraj }) {
  const [q, setQ] = useState(pocetni)
  const [rez, setRez] = useState([])
  const [open, setOpen] = useState(false)
  const [radi, setRadi] = useState(false)
  const [kreiram, setKreiram] = useState(false)
  const tref = useRef(null)
  const run = (v) => {
    setQ(v); setOpen(true); setRadi(true)
    clearTimeout(tref.current)
    tref.current = setTimeout(async () => {
      try { setRez(await trazi(v)) } catch { setRez([]) } finally { setRadi(false) }
    }, 300)
  }
  const kreiraj = async () => {
    if (!onKreiraj || !q.trim() || kreiram) return
    setKreiram(true)
    try { const it = await onKreiraj(q.trim()); if (it) { setQ(opis(it)); setOpen(false) } }
    finally { setKreiram(false) }
  }
  return (
    <div style={{ position: 'relative' }}>
      <input value={q} placeholder={placeholder}
        onChange={(e) => run(e.target.value)} onFocus={() => { setOpen(true); if (!rez.length) run(q) }}
        style={{ width: '100%', boxSizing: 'border-box' }} />
      {open && (
        <div style={{ position: 'absolute', zIndex: 20, background: 'var(--karta, #fff)', border: '1px solid var(--line, #ccc)', borderRadius: 8, width: '100%', maxHeight: 220, overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,.12)' }}>
          {radi && <div className="meta" style={{ padding: 8 }}>Tražim…</div>}
          {!radi && rez.length === 0 && <div className="meta" style={{ padding: 8 }}>Nema rezultata.</div>}
          {rez.map((it, i) => (
            <div key={i} onClick={() => { onPick(it); setQ(opis(it)); setOpen(false) }}
              style={{ padding: '6px 8px', cursor: 'pointer', borderTop: i ? '1px solid var(--line, #eee)' : 'none', fontSize: 13 }}>
              {opis(it)}
            </div>
          ))}
          {onKreiraj && q.trim() && (
            <div onClick={kreiraj}
              style={{ padding: '7px 8px', cursor: 'pointer', borderTop: '1px solid var(--line, #eee)', fontSize: 13, color: 'var(--plava, #2563eb)', fontWeight: 600 }}>
              {kreiram ? 'Kreiram…' : `➕ Kreiraj novi artikl: „${q.trim()}"`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Slanje spremljene primke u Apross (mapiranje na prave šifre + primka/kreiraj).
function PosaljiUApross({ primka, onPoslano }) {
  const danas = new Date().toISOString().slice(0, 10)
  const [skl, setSkl] = useState([])
  const [sklId, setSklId] = useState('')
  const [dob, setDob] = useState(null)
  const [broj, setBroj] = useState(primka.broj_otpremnice || ('w' + primka.id))
  const [datum, setDatum] = useState(primka.datum || danas)
  const [mape, setMape] = useState(() => (primka.stavke || []).map((s) => ({ artikl: null, kolicina: s.kolicina || 1, cijena: s.cijena ?? '' })))
  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)
  const [otv, setOtv] = useState(false)

  useEffect(() => { if (otv && skl.length === 0) api.arossSkladistaPopis().then((d) => setSkl(d || [])).catch(() => {}) }, [otv])

  if (primka.apross_broj) {
    return <div className="karta" style={{ marginTop: 10, borderLeft: '4px solid var(--zelena, green)' }}>
      ✓ Poslano u Apross — primka <b>#{primka.apross_broj}</b>
    </div>
  }

  const postaviMapu = (i, patch) => setMape((m) => m.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  const posalji = async () => {
    setGreska('')
    const stavke = mape.filter((m) => m.artikl && Number(m.kolicina) > 0)
      .map((m) => ({ sifraArtikla: m.artikl.sifra, kolicina: Number(m.kolicina), cijena: Number(m.cijena) || 0 }))
    if (!sklId) return setGreska('Odaberi skladište.')
    if (!dob) return setGreska('Odaberi dobavljača.')
    if (!stavke.length) return setGreska('Poveži barem jednu stavku s artiklom iz Aprossa.')
    setRadi(true)
    try {
      const r = await api.arossPosaljiPrimku({ broj_primke: broj, sifra_dobavljaca: dob.sifra, datum, sifra_skladista: Number(sklId), stavke, napomena: primka.napomena || null, primka_id: primka.id })
      onPoslano && onPoslano(r.erp_broj_primke)
    } catch (e) { setGreska(e.message) } finally { setRadi(false) }
  }

  return (
    <div className="karta" style={{ marginTop: 10 }}>
      <div className="naslov-red" style={{ cursor: 'pointer' }} onClick={() => setOtv(!otv)}>
        <h3 style={{ margin: 0 }}>📤 Pošalji u Apross {otv ? '▾' : '▸'}</h3>
      </div>
      {otv && (
        <div style={{ marginTop: 8 }}>
          {greska && <div className="greska">{greska}</div>}
          <label className="meta">Skladište</label>
          <select value={sklId} onChange={(e) => setSklId(e.target.value)} style={{ width: '100%', marginBottom: 8 }}>
            <option value="">— odaberi skladište —</option>
            {skl.map((s) => <option key={s.sifra} value={s.sifra}>{s.naziv}</option>)}
          </select>

          <label className="meta">Dobavljač</label>
          <div style={{ marginBottom: 8 }}>
            <Trazilica placeholder="traži dobavljača…" pocetni={primka.dobavljac || ''}
              trazi={(q) => api.arossPartneri(q)} opis={(p) => `${p.naziv}${p.mjesto ? ' · ' + p.mjesto : ''}`}
              onPick={setDob} />
          </div>

          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <div style={{ flex: 1 }}>
              <label className="meta">Broj primke</label>
              <input value={broj} onChange={(e) => setBroj(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
            <div style={{ flex: 1 }}>
              <label className="meta">Datum</label>
              <input type="date" value={datum} onChange={(e) => setDatum(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
          </div>

          <label className="meta">Stavke — poveži svaku s artiklom iz Aprossa</label>
          {(primka.stavke || []).map((s, i) => (
            <div key={i} style={{ border: '1px solid var(--line, #eee)', borderRadius: 8, padding: 8, marginBottom: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{s.artikl} <span className="meta">({s.kolicina} {s.jedinica || 'kom'})</span></div>
              <Trazilica placeholder="traži Apross artikl (naziv / kat. broj)…" pocetni={s.artikl || ''}
                trazi={(q) => api.arossArtikliTrazi(q)}
                opis={(a) => `${a.naziv}${a.kataloskiBroj ? ' · ' + a.kataloskiBroj : ''}`}
                onPick={(a) => postaviMapu(i, { artikl: a })}
                onKreiraj={async (naziv) => {
                  const r = await api.arossKreirajArtikl({ naziv, jmj: s.jedinica || 'kom' })
                  if (r && r.artikl) { postaviMapu(i, { artikl: r.artikl }); return r.artikl }
                  return null
                }} />
              <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                <div style={{ flex: 1 }}>
                  <label className="meta">Količina</label>
                  <input type="number" step="any" value={mape[i].kolicina} onChange={(e) => postaviMapu(i, { kolicina: e.target.value })} style={{ width: '100%', boxSizing: 'border-box' }} />
                </div>
                <div style={{ flex: 1 }}>
                  <label className="meta">Cijena (EUR)</label>
                  <input type="number" step="any" value={mape[i].cijena} onChange={(e) => postaviMapu(i, { cijena: e.target.value })} style={{ width: '100%', boxSizing: 'border-box' }} />
                </div>
              </div>
              {mape[i].artikl && <div className="meta" style={{ marginTop: 4, color: 'var(--zelena, green)' }}>✓ {mape[i].artikl.naziv} (šifra {mape[i].artikl.sifra})</div>}
            </div>
          ))}

          <button className="btn" disabled={radi} onClick={posalji}>📤 Pošalji u Apross</button>
          <p className="meta" style={{ marginBottom: 0 }}>Apross dodjeljuje broj primke i vraća ga; stavke bez povezanog artikla se preskaču.</p>
        </div>
      )}
    </div>
  )
}

function redIznos(s) {
  const c = parseFloat(s.cijena); const k = parseFloat(s.kolicina)
  if (isNaN(c)) return null
  return c * (isNaN(k) ? 1 : k)
}
// Zbroj svih redaka (null ako nijedan nema cijenu).
function zbrojStavki(stavke) {
  let s = 0; let ima = false
  for (const st of (stavke || [])) {
    const r = redIznos(st)
    if (r != null) { s += r; ima = true }
  }
  return ima ? s : null
}
const eur = (n) => (n == null ? '' : n.toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €')
// Broj s hrvatskim decimalnim zarezom (bez prisilnih decimala): 2 → "2", 1.5 → "1,5"
const broj = (n) => (n == null || n === '' || isNaN(Number(n)) ? (n ?? '') : Number(n).toLocaleString('hr-HR'))
const datumHR = (d) => (d ? d.split('-').reverse().join('.') + '.' : '')
// mala slova bez dijakritika — za pretragu neosjetljivu na kvačice
const norm = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')

function praznaPrimka() {
  return { dobavljac: '', broj_otpremnice: '', datum: '', napomena: '', narucio_id: '', fotografije: [], stavke: [] }
}

export default function Skladiste() {
  const { t } = useT()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [poruka, setPoruka] = useState('')
  const [nova, setNova] = useState(null)       // objekt forme ili null (zatvoreno)
  const [detalj, setDetalj] = useState(null)   // otvorena primka (pregled) ili null
  const [q, setQ] = useState('')               // pretraga po artiklu (i dobavljaču/broju)
  const [narucitelji, setNarucitelji] = useState([])
  const [dijelovi, setDijelovi] = useState([])     // operacije koje čekaju dijelove (mehaničar stisnuo "Nemam dijelova")
  const [dodajem, setDodajem] = useState(false)   // učitavanje stranice
  const [citam, setCitam] = useState(false)       // AI čita
  const [spremam, setSpremam] = useState(false)
  const fileRef = useRef(null)

  const ucitaj = () => api.primke().then(setLista).catch((e) => setGreska(e.message))
  const ucitajDijelove = () => api.cekaDijelove().then((d) => setDijelovi(Array.isArray(d) ? d : [])).catch(() => {})
  useEffect(() => { ucitaj(); ucitajDijelove(); api.narucitelji().then(setNarucitelji).catch(() => {}) }, [])

  const dioStigao = async (zid) => {
    setGreska('')
    try { await api.dioStigao(zid); setDijelovi((p) => p.filter((o) => o.zadatak_id !== zid)) }
    catch (e) { setGreska(e.message) }
  }

  const zapocni = () => { setGreska(''); setPoruka(''); setDetalj(null); setNova(praznaPrimka()) }
  const odustani = () => { setNova(null); setCitam(false); setDodajem(false) }

  const dodajStranicu = async (e) => {
    const file = e.target.files && e.target.files[0]
    if (fileRef.current) fileRef.current.value = ''
    if (!file) return
    setGreska(''); setDodajem(true)
    try {
      const fd = new FormData()
      fd.append('slika', file)
      const r = await api.uploadStranicaOtpremnice(fd)
      setNova((p) => ({ ...p, fotografije: [...p.fotografije, r.foto] }))
    } catch (err) {
      setGreska(err.message)
    } finally {
      setDodajem(false)
    }
  }
  const makniStranicu = (i) => setNova((p) => ({ ...p, fotografije: p.fotografije.filter((_, j) => j !== i) }))

  const procitaj = async () => {
    if (!nova.fotografije.length) { setGreska(t('skl.bezStranica')); return }
    setGreska(''); setPoruka(''); setCitam(true)
    try {
      const r = await api.procitajOtpremnicu(nova.fotografije)
      if (!r.ai) { setPoruka(t('skl.aiNedostupan')); return }
      setNova((p) => ({
        ...p,
        dobavljac: r.dobavljac || p.dobavljac || '',
        broj_otpremnice: r.broj_otpremnice || p.broj_otpremnice || '',
        datum: r.datum || p.datum || '',
        stavke: (r.stavke && r.stavke.length ? r.stavke : p.stavke).map((s) => ({
          artikl: s.artikl || '', kolicina: s.kolicina ?? 1,
          jedinica: s.jedinica || 'kom', cijena: s.cijena ?? '',
        })),
      }))
    } catch (err) {
      setGreska(err.message)
    } finally {
      setCitam(false)
    }
  }

  const postaviPolje = (polje, vrijednost) => setNova((p) => ({ ...p, [polje]: vrijednost }))
  const postaviStavku = (i, polje, vrijednost) => setNova((p) => {
    const stavke = p.stavke.map((s, j) => (j === i ? { ...s, [polje]: vrijednost } : s))
    return { ...p, stavke }
  })
  const dodajStavku = () => setNova((p) => ({ ...p, stavke: [...p.stavke, praznaStavka()] }))
  const makniStavku = (i) => setNova((p) => ({ ...p, stavke: p.stavke.filter((_, j) => j !== i) }))

  const spremi = async () => {
    setGreska('')
    const narId = nova.narucio_id ? parseInt(nova.narucio_id, 10) : null
    const stavke = nova.stavke
      .filter((s) => (s.artikl || '').trim())
      .map((s) => ({
        artikl: s.artikl.trim(),
        kolicina: parseFloat(s.kolicina) || 1,
        jedinica: (s.jedinica || 'kom').trim() || 'kom',
        cijena: s.cijena === '' || s.cijena == null ? null : parseFloat(s.cijena),
        narucio_id: narId,
      }))
    const telo = {
      dobavljac: nova.dobavljac.trim() || null,
      broj_otpremnice: nova.broj_otpremnice.trim() || null,
      datum: nova.datum || null,
      napomena: nova.napomena.trim() || null,
      fotografije: nova.fotografije,
      stavke,
    }
    if (!telo.dobavljac && !telo.broj_otpremnice && !stavke.length && !nova.fotografije.length) {
      setGreska(t('skl.prazno')); return
    }
    setSpremam(true)
    try {
      await api.kreirajPrimku(telo)
      setNova(null); setPoruka(t('skl.spremljeno')); ucitaj()
    } catch (err) {
      setGreska(err.message)
    } finally {
      setSpremam(false)
    }
  }

  const obrisi = async (p) => {
    if (!window.confirm(t('skl.potvrdiBrisanje'))) return
    setGreska('')
    try { await api.obrisiPrimku(p.id); setDetalj(null); ucitaj() } catch (err) { setGreska(err.message) }
  }

  const spremiBlob = (blob, naziv) => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = naziv
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const izvozJedne = async (p) => {
    setGreska('')
    try {
      const blob = await api.preuzmiPrimkuExcel(p.id)
      spremiBlob(blob, `primka-${(p.broj_otpremnice || p.id)}.xlsx`)
    } catch (err) { setGreska(err.message) }
  }

  // Tablica stavki (s iznosom po retku) — koristi se u pregledu primke.
  const tablicaStavki = (stavke) => (
    <table className="skl-tablica">
      <thead>
        <tr>
          <th>{t('skl.artiklKratko')}</th>
          <th className="num">{t('skl.kolicina')}</th>
          <th>{t('skl.jedinica')}</th>
          <th className="num">{t('skl.cijena')}</th>
          <th className="num">{t('skl.iznos')}</th>
        </tr>
      </thead>
      <tbody>
        {stavke.map((s, i) => (
          <tr key={i}>
            <td>{s.artikl}</td>
            <td className="num">{broj(s.kolicina)}</td>
            <td>{s.jedinica}</td>
            <td className="num">{s.cijena != null ? eur(s.cijena) : ''}</td>
            <td className="num">{redIznos(s) != null ? eur(redIznos(s)) : ''}</td>
          </tr>
        ))}
      </tbody>
      {zbrojStavki(stavke) != null && (
        <tfoot>
          <tr>
            <td colSpan={4} style={{ fontWeight: 700 }}>{t('skl.ukupno')}</td>
            <td className="num" style={{ fontWeight: 700 }}>{eur(zbrojStavki(stavke))}</td>
          </tr>
        </tfoot>
      )}
    </table>
  )

  if (lista === null) return <Layout naslov={t('skl.naslov')}><Spinner /></Layout>

  // --- Pregled jedne primke ---
  if (detalj) {
    const str = (detalj.fotografije && detalj.fotografije.length ? detalj.fotografije : (detalj.foto_putanja ? [detalj.foto_putanja] : []))
    return (
      <Layout naslov={t('skl.naslov')} nazad={() => setDetalj(null)}>
        {greska && <div className="greska">{greska}</div>}
        <div className="btn-red">
          <button className="btn sekund" onClick={() => setDetalj(null)}>‹ {t('skl.natrag')}</button>
          <button className="btn sekund" onClick={() => izvozJedne(detalj)}>{t('skl.izvoz')}</button>
        </div>
        <div className="karta" style={{ marginTop: 10 }}>
          <div className="naslov-red">
            <h3>{detalj.dobavljac || t('skl.bezDobavljaca')}</h3>
            {detalj.datum && <span className="meta">{datumHR(detalj.datum)}</span>}
          </div>
          <p className="meta">
            {detalj.broj_otpremnice ? `${t('skl.broj')}: ${detalj.broj_otpremnice}` : ''}
            {detalj.kreirao ? `${detalj.broj_otpremnice ? ' · ' : ''}${detalj.kreirao.ime}` : ''}
          </p>
          {detalj.napomena && <p className="meta">{detalj.napomena}</p>}
          {(detalj.stavke || []).length > 0 && tablicaStavki(detalj.stavke)}
          {str.length > 0 && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8 }}>
              {str.map((f, i) => (
                <a key={i} href={medijUrl(f)} target="_blank" rel="noreferrer" className="meta">
                  📷 {t('skl.stranica')} {i + 1}
                </a>
              ))}
            </div>
          )}
          <div className="btn-red" style={{ marginTop: 10 }}>
            <button className="btn sekund mali" onClick={() => obrisi(detalj)}>{t('skl.obrisi')}</button>
          </div>
        </div>
        <PosaljiUApross primka={detalj}
          onPoslano={(erp) => { setDetalj({ ...detalj, apross_broj: erp }); setPoruka(`Poslano u Apross — primka #${erp}`); ucitaj() }} />
      </Layout>
    )
  }

  // --- Forma (nova primka) ---
  if (nova) {
    return (
      <Layout naslov={t('skl.naslov')} nazad={odustani}>
        {greska && <div className="greska">{greska}</div>}
        <div className="karta">
          {/* Stranice otpremnice */}
          <input
            ref={fileRef} type="file" accept="image/*" capture="environment"
            onChange={dodajStranicu} style={{ display: 'none' }}
          />
          <label style={{ marginTop: 0 }}>{t('skl.stranice')} ({nova.fotografije.length})</label>
          <p className="meta" style={{ marginTop: 0 }}>{t('skl.straniceHint')}</p>
          {nova.fotografije.length > 0 && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '6px 0' }}>
              {nova.fotografije.map((f, i) => (
                <div key={i} style={{ position: 'relative' }}>
                  <a href={medijUrl(f)} target="_blank" rel="noreferrer">
                    <img src={medijUrl(f)} alt={`${t('skl.stranica')} ${i + 1}`}
                      style={{ width: 84, height: 112, objectFit: 'cover', borderRadius: 6, border: '1px solid var(--rub, #ccc)' }} />
                  </a>
                  <span style={{ position: 'absolute', bottom: 2, left: 4, fontSize: 11, background: 'rgba(0,0,0,.6)', color: '#fff', padding: '0 5px', borderRadius: 4 }}>{i + 1}</span>
                  <button className="btn sekund mali" onClick={() => makniStranicu(i)} title={t('skl.makniStranicu')}
                    style={{ position: 'absolute', top: -8, right: -8, width: 24, height: 24, padding: 0, borderRadius: '50%' }}>✕</button>
                </div>
              ))}
            </div>
          )}
          <div className="btn-red">
            <button className="btn sekund" onClick={() => fileRef.current && fileRef.current.click()} disabled={dodajem || citam}>
              {dodajem ? t('skl.dodajem') : t('skl.dodajStranicu')}
            </button>
            <button className="btn" onClick={procitaj} disabled={citam || dodajem || !nova.fotografije.length}>
              {citam ? t('skl.citamVise', { n: nova.fotografije.length }) : t('skl.procitaj')}
            </button>
          </div>

          <label>{t('skl.dobavljac')}</label>
          <input value={nova.dobavljac} onChange={(e) => postaviPolje('dobavljac', e.target.value)} />

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 140px' }}>
              <label>{t('skl.broj')}</label>
              <input value={nova.broj_otpremnice} onChange={(e) => postaviPolje('broj_otpremnice', e.target.value)} />
            </div>
            <div style={{ flex: '1 1 140px' }}>
              <label>{t('skl.datum')}</label>
              <input type="date" value={nova.datum || ''} onChange={(e) => postaviPolje('datum', e.target.value)} />
            </div>
          </div>

          <label>{t('skl.narucioZadano')}</label>
          <select value={nova.narucio_id || ''} onChange={(e) => postaviPolje('narucio_id', e.target.value)}>
            <option value="">—</option>
            {narucitelji.map((n) => <option key={n.id} value={n.id}>{n.ime}</option>)}
          </select>

          <label>{t('skl.stavke')} ({nova.stavke.length})</label>
          {nova.stavke.map((s, i) => (
            <div key={i} className="karta" style={{ padding: 8, marginTop: 6 }}>
              <input placeholder={t('skl.artikl')} value={s.artikl}
                onChange={(e) => postaviStavku(i, 'artikl', e.target.value)} />
              <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'flex-end' }}>
                <div style={{ flex: '1 1 70px' }}>
                  <label style={{ marginTop: 0 }}>{t('skl.kolicina')}</label>
                  <input type="number" step="any" value={s.kolicina}
                    onChange={(e) => postaviStavku(i, 'kolicina', e.target.value)} />
                </div>
                <div style={{ flex: '1 1 60px' }}>
                  <label style={{ marginTop: 0 }}>{t('skl.jedinica')}</label>
                  <input value={s.jedinica} onChange={(e) => postaviStavku(i, 'jedinica', e.target.value)} />
                </div>
                <div style={{ flex: '1 1 80px' }}>
                  <label style={{ marginTop: 0 }}>{t('skl.cijena')}</label>
                  <input type="number" step="any" value={s.cijena}
                    onChange={(e) => postaviStavku(i, 'cijena', e.target.value)} />
                </div>
                <button className="btn sekund mali" onClick={() => makniStavku(i)} title={t('skl.makni')}>✕</button>
              </div>
              {redIznos(s) != null && (
                <p className="meta" style={{ textAlign: 'right', margin: '4px 2px 0' }}>{t('skl.iznos')}: {eur(redIznos(s))}</p>
              )}
            </div>
          ))}
          <button className="btn sekund mali" style={{ marginTop: 6 }} onClick={dodajStavku}>{t('skl.dodajStavku')}</button>
          {zbrojStavki(nova.stavke) != null && (
            <p style={{ textAlign: 'right', marginTop: 8, fontWeight: 700 }}>
              {t('skl.ukupno')}: {eur(zbrojStavki(nova.stavke))}
            </p>
          )}

          <label style={{ marginTop: 10 }}>{t('skl.napomena')}</label>
          <textarea value={nova.napomena} onChange={(e) => postaviPolje('napomena', e.target.value)} />

          <div className="btn-red" style={{ marginTop: 10 }}>
            <button className="btn" onClick={spremi} disabled={spremam || citam || dodajem}>
              {spremam ? t('skl.spremam') : t('skl.spremi')}
            </button>
            <button className="btn sekund" onClick={odustani} disabled={spremam}>{t('skl.odustani')}</button>
          </div>
        </div>
      </Layout>
    )
  }

  // --- Popis primki (kompaktno) ---
  const qn = norm(q.trim())
  const matchArtikli = (p) => (qn ? (p.stavke || []).filter((s) => norm(s.artikl).includes(qn)) : [])
  const odgovara = (p) => !qn
    || norm(p.dobavljac).includes(qn)
    || norm(p.broj_otpremnice).includes(qn)
    || matchArtikli(p).length > 0
  const prikaz = lista.filter(odgovara)

  return (
    <Layout naslov={t('skl.naslov')}>
      {greska && <div className="greska">{greska}</div>}
      {poruka && <div className="uspjeh">{poruka}</div>}

      <NarudzbeSkladiste />
      <ZaliheAPROSS />
      <TrosakPoVozilu />

      {dijelovi.length > 0 && (
        <div className="karta" style={{ marginBottom: 14, borderLeft: '4px solid var(--narancasta, #b26a00)' }}>
          <div className="naslov-red">
            <h3 style={{ margin: 0 }}>⚠️ Nedostaju dijelovi ({dijelovi.length})</h3>
          </div>
          <p className="meta" style={{ marginTop: 2 }}>Mehaničar je prijavio da za ove operacije fali dio. Kad dio stigne, pritisni „Dio stigao" — zadatak se vraća mehaničaru.</p>
          {dijelovi.map((o) => (
            <div key={o.zadatak_id} className="karta" style={{ padding: 10, marginTop: 8 }}>
              <div><strong>🚚 {o.gb || '—'}</strong>{o.vozilo ? ` · ${o.vozilo}` : ''}</div>
              <div style={{ marginTop: 2 }}>{o.kategorija ? <strong>{o.kategorija} — </strong> : ''}{o.opis}</div>
              <div className="meta" style={{ marginTop: 2 }}>
                {o.mehanicar ? `🧑‍🔧 ${o.mehanicar}` : 'bez mehaničara'}
                {o.dio ? ` · 🔧 naručeno: ${o.dio}` : ''}
              </div>
              <div className="btn-red" style={{ marginTop: 8 }}>
                <button className="btn mali" onClick={() => dioStigao(o.zadatak_id)}>✓ Dio stigao → vrati mehaničaru</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <button className="btn" onClick={zapocni}>{t('skl.nova')}</button>

      {lista.length > 0 && (
        <input style={{ marginTop: 10 }} value={q}
          onChange={(e) => setQ(e.target.value)} placeholder={t('skl.trazi')} />
      )}

      <div style={{ marginTop: 14 }}>
        {lista.length === 0 ? (
          <p className="meta">{t('skl.nema')}</p>
        ) : prikaz.length === 0 ? (
          <p className="meta">{t('skl.nemaRezultata', { q: q.trim() })}</p>
        ) : prikaz.map((p) => {
          const str = (p.fotografije && p.fotografije.length ? p.fotografije : (p.foto_putanja ? [p.foto_putanja] : []))
          const uk = zbrojStavki(p.stavke)
          const mArt = matchArtikli(p)
          return (
            <div key={p.id} className="karta skl-red" onClick={() => { setPoruka(''); setDetalj(p) }} style={{ cursor: 'pointer' }}>
              <div className="naslov-red">
                <h3>{p.dobavljac || t('skl.bezDobavljaca')}</h3>
                <span className="meta">{datumHR(p.datum)} ›</span>
              </div>
              <p className="meta" style={{ marginBottom: 0 }}>
                {p.broj_otpremnice ? `${t('skl.broj')}: ${p.broj_otpremnice} · ` : ''}
                {t('skl.stavkiBr', { n: (p.stavke || []).length })}
                {str.length ? ` · ${t('skl.brStranica', { n: str.length })}` : ''}
                {uk != null ? ` · ${eur(uk)}` : ''}
              </p>
              {mArt.length > 0 && (
                <p className="meta" style={{ marginTop: 4, color: 'var(--plava, #2563eb)' }}>
                  🔎 {mArt.slice(0, 3).map((s) => s.artikl).join(' · ')}{mArt.length > 3 ? ` +${mArt.length - 3}` : ''}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </Layout>
  )
}
