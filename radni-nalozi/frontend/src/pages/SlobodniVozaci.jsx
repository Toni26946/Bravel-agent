import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, Prazno } from '../ui'

// SLOBODNI VOZAČI — disponenti prijavljuju koji su vozači slobodni, odnosno čiji je kamion na
// popravku, da se na jednom mjestu vidi tko je raspoloživ (WhatsApp prijava Veljka, 19.11.2026.;
// ista funkcija kao u Flota OS-u). Vozilo se veže po GB-u: uz GB se vidi vozilo iz registra i
// otvoreni radni nalog (kamion u radioni). Kad vozač opet vozi, zapis se zatvori („Opet vozi") —
// ništa se ne briše, zatvoreni ostaju u povijesti.

const RAZLOZI = {
  POPRAVAK: { oznaka: 'Kamion na popravku', ikona: '🛠️', boja: '#b7791f', poz: '#fdf3dc' },
  SLOBODAN: { oznaka: 'Slobodan', ikona: '✅', boja: '#1f8a5b', poz: '#e3f6ec' },
  OSTALO: { oznaka: 'Ostalo', ikona: '•', boja: '#475569', poz: '#eef2f7' },
}

const danas = () => {
  const x = new Date()
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
}
const PRAZNO = () => ({ id: null, vozac: '', gb: '', razlog: 'POPRAVAK', od: danas(), do: '', napomena: '' })

// „2026-11-19" → „19.11.2026."
const hrDatum = (s) => {
  const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${m[3]}.${m[2]}.${m[1]}.` : '—'
}
const danaOd = (s) => {
  const t = Date.parse(s)
  return Number.isFinite(t) ? Math.max(0, Math.floor((Date.now() - t) / 86400000)) : null
}
const bezKvacica = (s) => String(s || '').toLowerCase().replace(/đ/g, 'd').normalize('NFD').replace(/[̀-ͯ]/g, '')

const NALOG_STATUS = { otvoren: 'otvoren', u_radu: 'u radu', ceka_dijelove: 'čeka dijelove' }

export default function SlobodniVozaci() {
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')
  const [povijest, setPovijest] = useState(false)
  const [filtar, setFiltar] = useState('SVI')
  const [trazi, setTrazi] = useState('')
  const [uredi, setUredi] = useState(null)   // zapis u obrascu (null = obrazac zatvoren)
  const [poruka, setPoruka] = useState('')
  const [sprema, setSprema] = useState(false)

  const ucitaj = () => api.slobodniVozaci(true)
    .then((x) => { setD(x); setGreska('') })
    .catch((e) => setGreska(e.message || 'Greška'))
  useEffect(() => { ucitaj() }, [])

  const zapisi = d?.zapisi || []
  const aktivni = zapisi.filter((z) => z.aktivan)
  const vidljivi = useMemo(() => {
    const q = bezKvacica(trazi).trim()
    return zapisi.filter((z) => (povijest ? !z.aktivan : z.aktivan)
      && (filtar === 'SVI' || z.razlog === filtar)
      && (!q || bezKvacica(`${z.vozac} ${z.gb || ''} ${z.napomena || ''}`).includes(q)))
  }, [zapisi, povijest, filtar, trazi])
  const brojPo = (r) => aktivni.filter((z) => r === 'SVI' || z.razlog === r).length

  const spremi = async () => {
    setSprema(true); setPoruka('')
    const tijelo = { vozac: uredi.vozac, gb: uredi.gb || null, razlog: uredi.razlog,
      od: uredi.od || null, do: uredi.do || null, napomena: uredi.napomena || null }
    try {
      if (uredi.id) await api.urediSlobodnogVozaca(uredi.id, tijelo)
      else await api.dodajSlobodnogVozaca(tijelo)
      setUredi(null); setPoruka('✓ Spremljeno.')
      await ucitaj()
    } catch (e) { setPoruka('⚠ ' + (e.message || 'Greška')) }
    setSprema(false)
  }

  const zatvori = async (z) => {
    if (!window.confirm(`${z.vozac} opet vozi? Zapis prelazi u povijest.`)) return
    try {
      await api.zatvoriSlobodnogVozaca(z.id)
      setPoruka(`✓ ${z.vozac} — opet vozi.`)
    } catch (e) { setPoruka('⚠ ' + (e.message || 'Greška')) }
    setUredi(null)
    await ucitaj()
  }

  const akcija = (
    <button className="btn mali" onClick={() => { setUredi(PRAZNO()); setPoruka('') }}>+ Prijavi vozača</button>
  )

  return (
    <Layout naslov="Slobodni vozači" akcija={akcija}>
      <p className="meta" style={{ marginTop: 0 }}>
        Vozači koji trenutno ne voze svoj kamion — kamion je na popravku ili su slobodni za drugi posao.
        Kad vozač opet vozi, stisne se <strong>Opet vozi</strong> i zapis prelazi u povijest.
      </p>

      {uredi && (
        <div className="karta" style={{ marginBottom: 12 }}>
          <h3>{uredi.id ? 'Uredi prijavu' : 'Prijavi slobodnog vozača'}</h3>
          <label style={{ marginTop: 6 }}>Vozač</label>
          <input className="pretraga-input" list="slobodni-vozaci-imena" value={uredi.vozac}
            onChange={(e) => setUredi({ ...uredi, vozac: e.target.value })} placeholder="Počni pisati ime…" />
          <datalist id="slobodni-vozaci-imena">
            {(d?.vozaci || []).map((ime) => <option key={ime} value={ime} />)}
          </datalist>
          <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 120px' }}>
              <label>GB kamiona</label>
              <input className="pretraga-input" list="slobodni-vozaci-gb" inputMode="numeric" value={uredi.gb || ''}
                onChange={(e) => setUredi({ ...uredi, gb: e.target.value })} placeholder="npr. 433" />
              <datalist id="slobodni-vozaci-gb">
                {(d?.gbovi || []).map((g) => <option key={g} value={g} />)}
              </datalist>
            </div>
            <div style={{ flex: '2 1 200px' }}>
              <label>Razlog</label>
              <select className="pretraga-input" value={uredi.razlog} onChange={(e) => setUredi({ ...uredi, razlog: e.target.value })}>
                {Object.entries(RAZLOZI).map(([k, r]) => <option key={k} value={k}>{r.ikona} {r.oznaka}</option>)}
              </select>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 140px' }}>
              <label>Slobodan od</label>
              <input className="pretraga-input" type="date" value={uredi.od || ''} onChange={(e) => setUredi({ ...uredi, od: e.target.value })} />
            </div>
            <div style={{ flex: '1 1 140px' }}>
              <label>Predviđeno do (ako se zna)</label>
              <input className="pretraga-input" type="date" value={uredi.do || ''} onChange={(e) => setUredi({ ...uredi, do: e.target.value })} />
            </div>
          </div>
          <label style={{ marginTop: 8 }}>Napomena</label>
          <input className="pretraga-input" value={uredi.napomena || ''} onChange={(e) => setUredi({ ...uredi, napomena: e.target.value })}
            placeholder="npr. kvar mjenjača, servis u radioni" />
          <div className="btn-red" style={{ marginTop: 10 }}>
            <button className="btn mali" disabled={sprema} onClick={spremi}>{sprema ? 'Spremam…' : '💾 Spremi'}</button>
            <button className="btn mali sekund" onClick={() => setUredi(null)}>Odustani</button>
            {uredi.id && aktivni.some((z) => z.id === uredi.id) && (
              <button className="btn mali sekund" onClick={() => zatvori(uredi)}>✓ Opet vozi</button>
            )}
          </div>
        </div>
      )}

      {poruka && <div className={poruka.startsWith('⚠') ? 'greska' : 'meta'} style={{ marginBottom: 8, color: poruka.startsWith('⚠') ? undefined : '#1f8a5b' }}>{poruka}</div>}

      <div className="vz-filteri">
        {['SVI', ...Object.keys(RAZLOZI)].map((r) => (
          <button key={r} className={'vz-fil' + (filtar === r ? ' akt' : '')} onClick={() => setFiltar(r)}>
            {r === 'SVI' ? 'Svi' : `${RAZLOZI[r].ikona} ${RAZLOZI[r].oznaka}`} ({brojPo(r)})
          </button>
        ))}
        <button className={'vz-fil' + (povijest ? ' akt' : '')} onClick={() => setPovijest((p) => !p)}>🕘 Povijest (opet voze)</button>
      </div>
      <input className="pretraga-input" style={{ marginBottom: 10 }} placeholder="Traži vozača, GB ili napomenu…"
        value={trazi} onChange={(e) => setTrazi(e.target.value)} />

      {greska ? <div className="greska">{greska}</div>
        : d === null ? <Spinner />
        : vidljivi.length === 0 ? (
          <Prazno emo="🧑‍✈️" tekst={povijest ? 'Nema zatvorenih prijava.' : 'Trenutno nema prijavljenih slobodnih vozača.'} />
        ) : (
          vidljivi.map((z) => <Kartica key={z.id} z={z} onUredi={() => {
            setUredi({ ...z, gb: z.gb || '', do: z.do || '', napomena: z.napomena || '' }); setPoruka('')
            window.scrollTo({ top: 0, behavior: 'smooth' })
          }} onZatvori={() => zatvori(z)} />)
        )}
      {d && !greska && (
        <p className="meta">{povijest ? `Povijest: ${vidljivi.length} zapisa.` : `Slobodnih vozača: ${aktivni.length}.`}</p>
      )}
    </Layout>
  )
}

function Kartica({ z, onUredi, onZatvori }) {
  const r = RAZLOZI[z.razlog] || RAZLOZI.OSTALO
  const n = danaOd(z.od)
  const v = z.vozilo
  return (
    <div className="karta" style={{ opacity: z.aktivan ? 1 : 0.6 }}>
      <div className="naslov-red">
        <div>
          <h3>{z.vozac}</h3>
          <span style={{ display: 'inline-block', fontSize: 12, fontWeight: 700, color: r.boja, background: r.poz,
            borderRadius: 999, padding: '2px 10px' }}>{r.ikona} {r.oznaka}</span>
        </div>
        {z.aktivan && (
          <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
            <button className="ikonbtn" onClick={onUredi} title="Uredi">✏️</button>
            <button className="btn mali sekund" onClick={onZatvori}>✓ Opet vozi</button>
          </div>
        )}
      </div>
      <p className="meta" style={{ marginTop: 6 }}>
        🚛 <strong>{z.gb ? `GB ${z.gb}` : 'bez kamiona'}</strong>
        {v?.vozilo ? ` · ${v.vozilo}` : ''}
        {v?.nalog && <> · 🔧 <Link to={`/nalozi/${v.nalog.id}`}>{v.nalog.broj}</Link> ({NALOG_STATUS[v.nalog.status] || v.nalog.status})</>}
      </p>
      <p className="meta">
        📅 od <strong>{hrDatum(z.od)}</strong>
        {z.aktivan && n !== null && <span style={{ color: n >= 7 ? 'var(--crvena)' : undefined }}> ({n === 0 ? 'od danas' : `${n} d`})</span>}
        {z.do ? <> · predviđeno do <strong>{hrDatum(z.do)}</strong></> : ''}
      </p>
      {z.napomena && <p className="meta">📝 {z.napomena}</p>}
      <p className="meta" style={{ fontSize: 12 }}>
        Prijavio: {z.autor || '?'} · {hrDatum(z.prijavljeno)}
        {!z.aktivan && <> · opet vozi od {hrDatum(z.zatvoreno)}{z.zatvorio ? ` (${z.zatvorio})` : ''}</>}
      </p>
    </div>
  )
}
