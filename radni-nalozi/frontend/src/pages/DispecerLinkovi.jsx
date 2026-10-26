import { useEffect, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner } from '../ui'

// Vlasnik-only: generiranje i gašenje login-less poveznica mehaničarima.
// Slanje WhatsAppom je zasebno i gateano — ovdje se poveznica samo napravi/kopira.
export default function DispecerLinkovi() {
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [linkovi, setLinkovi] = useState({})   // radnik_id -> { url, token }
  const [trazi, setTrazi] = useState('')

  const ucitaj = () => api.dispecerLinkovi().then(setLista).catch((e) => { setGreska(e.message); setLista([]) })
  useEffect(() => { ucitaj() }, [])

  const napravi = async (id) => {
    setGreska('')
    try {
      const r = await api.dispecerNapraviLink(id)
      setLinkovi((s) => ({ ...s, [id]: { url: r.url, token: r.token } }))
      ucitaj()
    } catch (e) { setGreska(e.message) }
  }
  const ugasi = async (id) => {
    if (!window.confirm('Ugasiti sve poveznice ovog mehaničara?')) return
    setGreska('')
    try { await api.dispecerUgasi(id); setLinkovi((s) => { const n = { ...s }; delete n[id]; return n }); ucitaj() }
    catch (e) { setGreska(e.message) }
  }
  const kopiraj = (url) => { try { navigator.clipboard.writeText(url) } catch (_) {} }

  if (lista === null) return <Layout naslov="Dispečer — poveznice" nazad><Spinner /></Layout>

  const q = trazi.trim().toLowerCase()
  const redci = q ? lista.filter((r) => r.ime.toLowerCase().includes(q)) : lista

  return (
    <Layout naslov="Dispečer — poveznice" nazad>
      {greska && <div className="greska" onClick={() => setGreska('')}>{greska}</div>}
      <p className="meta" style={{ margin: '4px 0 12px' }}>
        Napravi poveznicu, kopiraj je i pošalji mehaničaru. Veže se na prvi mobitel koji je otvori.
        Slanje WhatsAppom je zasebno (zasad isključeno).
      </p>
      <input className="pretraga-input" placeholder="Traži mehaničara…" value={trazi}
        onChange={(e) => setTrazi(e.target.value)} style={{ marginBottom: 12 }} />

      {redci.map((r) => {
        const novi = linkovi[r.id]
        return (
          <div key={r.id} className="karta" style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <strong>{r.ime}</strong>
              {r.ima_link
                ? <span className="meta">🔗 poveznica aktivna{r.vezan_uredjaj ? ' · vezan uređaj' : ' · čeka prvi uređaj'}</span>
                : <span className="meta">bez poveznice</span>}
            </div>
            <div className="btn-red" style={{ marginTop: 8 }}>
              <button className="btn mali" onClick={() => napravi(r.id)}>
                {r.ima_link ? 'Nova poveznica' : 'Napravi poveznicu'}
              </button>
              {r.ima_link && <button className="btn sekund mali" onClick={() => ugasi(r.id)}>Ugasi</button>}
            </div>
            {novi && (
              <div style={{ marginTop: 8 }}>
                <input readOnly value={novi.url} onFocus={(e) => e.target.select()} style={{ fontSize: 12 }} />
                <div className="btn-red" style={{ marginTop: 6 }}>
                  <button className="btn sekund mali" onClick={() => kopiraj(novi.url)}>📋 Kopiraj</button>
                  <a className="btn sekund mali" href={novi.url} target="_blank" rel="noreferrer">Otvori</a>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </Layout>
  )
}
