import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Prazno, Spinner, useAutoOsvjezi } from '../ui'

// Testovi kočnica s Cartec valjaka (računalo u radioni šalje svako mjerenje).
// Gore: testovi kojima ne znamo vozilo → pitanje „Test kočnica u HH:MM — koje vozilo?" s gumbima.

const vrijeme = (iso) => { try { return new Date(iso).toLocaleTimeString('hr-HR', { hour: '2-digit', minute: '2-digit' }) } catch { return '' } }
const dan = (iso) => { try { return new Date(iso).toLocaleDateString('hr-HR') } catch { return '' } }
const kN = (n) => (n / 1000).toLocaleString('hr-HR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

export function TablicaMjerenja({ mjerenja, sveVerzije = false }) {
  const red = sveVerzije ? mjerenja : mjerenja.filter((m) => m.vazece)
  if (!red.length) return null
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, marginTop: 6 }}>
      <thead>
        <tr style={{ textAlign: 'left', color: 'var(--muted)', fontSize: 12 }}>
          <th>Osovina</th><th>Lijevo kN</th><th>Desno kN</th><th>Razlika</th><th>Vrijeme</th>
        </tr>
      </thead>
      <tbody>
        {red.map((m) => (
          <tr key={m.id} style={{ borderTop: '1px solid var(--rub, #e5e7eb)', opacity: m.vazece ? 1 : 0.5 }}>
            <td>{m.vrsta === 'parkirna' ? '🅿️ ' : ''}{m.osovina}.{!m.vazece && <small> (ponovljeno)</small>}</td>
            <td>{kN(m.sila_lijevo)}</td>
            <td>{kN(m.sila_desno)}</td>
            <td style={{ color: m.razlika_pct > 25 ? 'var(--crveno, #c62828)' : undefined, fontWeight: m.razlika_pct > 25 ? 700 : 400 }}>
              {m.razlika_pct.toLocaleString('hr-HR')} %
            </td>
            <td>{vrijeme(m.vrijeme)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function KarticaTesta({ t, onVezano }) {
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const [povijest, setPovijest] = useState(false)
  const vezi = async (nalogId) => {
    setRadi(true); setGreska('')
    try { await api.testKocnicaVezi(t.id, nalogId); onVezano() } catch (e) { setGreska(e.message) } finally { setRadi(false) }
  }
  const otvoren = t.status !== 'vezan'
  const imaPonovljenih = t.mjerenja.some((m) => !m.vazece)
  return (
    <div className="card" style={{ borderLeft: otvoren ? '4px solid var(--crveno, #c62828)' : undefined }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <b>Test kočnica u {vrijeme(t.pocetak)} · {dan(t.pocetak)}</b>
        <span style={{ color: 'var(--muted)', fontSize: 13 }}>{t.osovina} osov.</span>
      </div>
      {t.nalog && (
        <div style={{ fontSize: 14, marginTop: 2 }}>
          GB <b>{t.gb || '—'}</b> · <Link to={`/nalozi/${t.nalog.id}`}>{t.nalog.broj}</Link> {t.nalog.naslov}
        </div>
      )}
      {otvoren && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontWeight: 700 }}>{t.status === 'ceka_potvrdu' ? 'Potvrdi vozilo:' : 'Koje vozilo?'}</div>
          {t.napomena && <div style={{ fontSize: 13, color: 'var(--muted)' }}>{t.napomena}</div>}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
            {t.status === 'ceka_potvrdu' && t.nalog && (
              <button className="btn" disabled={radi} style={{ width: 'auto', margin: 0 }} onClick={() => vezi(t.nalog.id)}>
                ✓ Da, GB {t.nalog.gb}
              </button>
            )}
            {t.kandidati.filter((n) => n.id !== t.nalog?.id).map((n) => (
              <button key={n.id} className="btn ghost" disabled={radi} style={{ width: 'auto', margin: 0 }} onClick={() => vezi(n.id)}>
                GB {n.gb} · {n.broj}
              </button>
            ))}
            <OdabirNaloga disabled={radi} onOdaberi={vezi} />
          </div>
          {greska && <div style={{ color: 'var(--crveno)', fontSize: 13 }}>{greska}</div>}
        </div>
      )}
      <TablicaMjerenja mjerenja={t.mjerenja} sveVerzije={povijest} />
      {imaPonovljenih && (
        <button className="btn ghost" style={{ width: 'auto', margin: '6px 0 0', fontSize: 12, padding: '4px 10px' }} onClick={() => setPovijest(!povijest)}>
          {povijest ? 'Sakrij ponovljena mjerenja' : 'Prikaži ponovljena mjerenja'}
        </button>
      )}
    </div>
  )
}

// Ručni odabir bilo kojeg otvorenog naloga upisom GB-a (kad pravog vozila nema među gumbima).
function OdabirNaloga({ onOdaberi, disabled }) {
  const [gb, setGb] = useState('')
  const [nalozi, setNalozi] = useState(null)
  const trazi = async () => {
    if (!gb.trim()) return
    try {
      setNalozi((await api.cartecNaloziZaGb(gb.trim())) || [])
    } catch { setNalozi([]) }
  }
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
      <input value={gb} inputMode="numeric" placeholder="drugi GB" onChange={(e) => setGb(e.target.value.replace(/\D/g, ''))}
        onKeyDown={(e) => { if (e.key === 'Enter') trazi() }}
        style={{ width: 90, margin: 0, padding: '6px 8px' }} />
      <button className="btn ghost" disabled={disabled || !gb} style={{ width: 'auto', margin: 0 }} onClick={trazi}>Traži</button>
      {nalozi && !nalozi.length && <small style={{ color: 'var(--muted)' }}>nema otvorenog naloga za GB {gb}</small>}
      {nalozi && nalozi.map((n) => (
        <button key={n.id} className="btn" disabled={disabled} style={{ width: 'auto', margin: 0 }} onClick={() => onOdaberi(n.id)}>
          {n.broj}
        </button>
      ))}
    </span>
  )
}

export default function TestoviKocnica() {
  const [otvoreni, setOtvoreni] = useState(null)
  const [zadnji, setZadnji] = useState(null)
  const [greska, setGreska] = useState('')
  const ucitaj = () => Promise.all([api.testoviKocnica({ status: 'otvoreni' }), api.testoviKocnica({ status: 'vezan' })])
    .then(([o, v]) => { setOtvoreni(o); setZadnji(v); setGreska('') })
    .catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])
  useAutoOsvjezi(ucitaj, 15000)

  return (
    <Layout naslov="Testovi kočnica">
      {greska && <div className="card" style={{ color: 'var(--crveno)' }}>{greska}</div>}
      {!otvoreni || !zadnji ? <Spinner /> : (
        <>
          {otvoreni.length > 0 && <h3 style={{ margin: '8px 0' }}>❓ Treba odabrati vozilo ({otvoreni.length})</h3>}
          {otvoreni.map((t) => <KarticaTesta key={t.id} t={t} onVezano={ucitaj} />)}
          <h3 style={{ margin: '14px 0 8px' }}>Zadnji testovi</h3>
          {!zadnji.length ? <Prazno emo="🛞" tekst="Još nema testova s valjaka." /> : zadnji.map((t) => <KarticaTesta key={t.id} t={t} onVezano={ucitaj} />)}
        </>
      )}
    </Layout>
  )
}
