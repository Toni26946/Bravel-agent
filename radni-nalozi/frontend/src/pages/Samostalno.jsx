import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { MikrofonGumb, Spinner, useAutoOsvjezi } from '../ui'

// Samostalni rad (npr. vulkanizer): sam sebi otvori posao (GB + što radi), mjerač odmah
// kreće; Pauza / Nastavi / Gotovo bez WhatsApp poveznice. Vidi SAMO svoje zadatke.
const BRZI = ['Zamjena gume', 'Krpanje gume', 'Demontaža i montaža guma', 'Balansiranje', 'Kontrola tlaka', 'Rotacija guma']

function trajanje(s) {
  s = Math.max(0, Math.floor(s || 0))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0')
}

export default function Samostalno() {
  const [d, setD] = useState(null)
  const [gb, setGb] = useState('')
  const [opis, setOpis] = useState('')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const [tik, setTik] = useState(0)        // sekunde od zadnjeg dohvata (živi mjerač)

  // Vlasnik: /samostalno?kao=<id> → pregled radnikova zaslona (samo gledanje).
  const kao = new URLSearchParams(window.location.search).get('kao')
  const ucitaj = () => api.samostalno(kao).then((r) => { setD(r); setTik(0) }).catch((e) => setGreska(e.message || 'Greška'))
  useEffect(() => { ucitaj() }, [])
  useAutoOsvjezi(ucitaj, 30000)
  useEffect(() => { const id = setInterval(() => setTik((x) => x + 1), 1000); return () => clearInterval(id) }, [])

  const akcija = (zid, a) => {
    setGreska('')
    api.samostalnoAkcija(zid, a).then(ucitaj).catch((e) => setGreska(e.message || 'Greška'))
  }
  const kreni = (e) => {
    e.preventDefault()
    if (!gb.trim() || !opis.trim()) { setGreska('Upiši garažni broj i što radiš.'); return }
    setRadi(true); setGreska('')
    api.samostalnoPosao(gb.trim(), opis.trim())
      .then(() => { setGb(''); setOpis(''); return ucitaj() })
      .catch((e2) => setGreska(e2.message || 'Greška'))
      .finally(() => setRadi(false))
  }

  if (d === null) return <Layout naslov="Moj rad">{greska ? <div className="greska">{greska}</div> : <Spinner />}</Layout>
  const uTijeku = d.otvoreni.filter((z) => z.radi)
  const ostali = d.otvoreni.filter((z) => !z.radi)
  const pr = !!d.pregled   // pregled vlasnika — gumbi zaključani

  return (
    <Layout naslov="Moj rad">
      {pr && <div className="karta" style={{ background: '#fff4d6', borderColor: '#f0c44c' }}>👁 Pregled kao <b>{d.ime}</b> — ovako mu izgleda zaslon (samo za gledanje).</div>}
      {greska && <div className="greska">{greska}</div>}
      <fieldset disabled={pr} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>

      {uTijeku.map((z) => (
        <div key={z.id} className="karta" style={{ borderColor: '#1f7a39', borderWidth: 2 }}>
          <div className="naslov-red">
            <h3>▶ GB {z.gb}</h3>
            <strong style={{ color: '#1f7a39', fontSize: 22 }}>⏱ {trajanje(z.sek + tik)}</strong>
          </div>
          <div className="meta">{[z.vozilo, z.reg, z.kategorija].filter(Boolean).join(' · ')}</div>
          <div style={{ fontSize: 17, margin: '8px 0 12px' }}>{z.opis}</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" style={{ background: '#1f7a39' }} onClick={() => akcija(z.id, 'gotovo')}>✅ Gotovo</button>
            <button className="btn sekund" onClick={() => akcija(z.id, 'pauza')}>⏸ Pauza</button>
          </div>
        </div>
      ))}

      <form className="karta" onSubmit={kreni}>
        <h3>➕ Novi posao</h3>
        <input className="pretraga-input" inputMode="numeric" placeholder="Garažni broj (npr. 1003)"
          value={gb} onChange={(e) => setGb(e.target.value)} />
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
          {BRZI.map((b) => (
            <button type="button" key={b} className="btn sekund mali" onClick={() => setOpis(b)}>{b}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
          <textarea className="pretraga-input" rows={2} placeholder="Što radiš? (odaberi gore ili upiši / izdiktiraj)"
            value={opis} onChange={(e) => setOpis(e.target.value)} />
          <MikrofonGumb onTekst={(t) => setOpis((o) => (o ? o + ' ' : '') + t)} />
        </div>
        <button className="btn" type="submit" disabled={radi}>{radi ? 'Spremam…' : '▶ Počni posao'}</button>
        <p className="meta" style={{ marginTop: 8 }}>Mjerač kreće odmah. Ako nešto već radiš, to ide u pauzu.</p>
      </form>

      {ostali.length > 0 && <h3 className="mu-naslov">Moji poslovi (čekaju)</h3>}
      {ostali.map((z) => (
        <div key={z.id} className="karta">
          <div className="naslov-red">
            <h3>GB {z.gb}</h3>
            {z.sek > 0 && <span className="meta">dosad ⏱ {trajanje(z.sek)}</span>}
          </div>
          <div className="meta">{[z.vozilo, z.kategorija].filter(Boolean).join(' · ')}</div>
          <div style={{ margin: '6px 0 10px' }}>{z.opis}</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn mali" onClick={() => akcija(z.id, 'pocni')}>▶ {z.sek > 0 ? 'Nastavi' : 'Počni'}</button>
            <button className="btn sekund mali" onClick={() => akcija(z.id, 'gotovo')}>✅ Gotovo</button>
          </div>
        </div>
      ))}

      <h3 className="mu-naslov">Danas završeno ({d.danas.length})</h3>
      {d.danas.length === 0 ? <p className="meta">Još ništa danas.</p> : d.danas.map((z) => (
        <div key={z.id} className="karta kk">
          <strong>GB {z.gb}</strong> · {z.opis} <span className="meta">· ⏱ {trajanje(z.sek)}</span>
        </div>
      ))}
      </fieldset>
    </Layout>
  )
}
