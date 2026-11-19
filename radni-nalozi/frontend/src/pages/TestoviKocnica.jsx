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

const LOSA_RAZLIKA = 25   // % razlike lijevo/desno iznad koje je osovina crvena

// Kotač: tamni pravokutnik; slabija strana kod prevelike razlike je crvena.
function Kotac({ los, prazan }) {
  return (
    <div style={{
      width: 24, height: 58, borderRadius: 7, flex: '0 0 auto',
      background: prazan ? 'transparent' : (los ? 'var(--crveno, #c62828)' : '#1f2937'),
      border: prazan ? '2px dashed #9ca3af' : 'none',
    }} />
  )
}

function Sila({ m, p, strana }) {
  const kljuc = strana === 'L' ? 'sila_lijevo' : 'sila_desno'
  const drugi = strana === 'L' ? 'sila_desno' : 'sila_lijevo'
  const slabijaRucna = !!p && p.razlika_pct > LOSA_RAZLIKA && p[kljuc] < p[drugi]
  return (
    <div style={{ textAlign: strana === 'L' ? 'right' : 'left', minWidth: 0 }}>
      <div style={{ fontSize: 24, fontWeight: 800, lineHeight: 1.1 }}>
        {m ? kN(m[kljuc]) : '—'}<span style={{ fontSize: 13, fontWeight: 400, color: 'var(--muted)' }}> kN</span>
      </div>
      {p && (
        <div style={{ fontSize: 13, color: slabijaRucna ? 'var(--crveno, #c62828)' : 'var(--muted)', fontWeight: slabijaRucna ? 700 : 400 }}>
          ručna {kN(p[kljuc])} kN
        </div>
      )}
    </div>
  )
}

// Jedna osovina gledana odozgo: sila lijevo — kotač — osovina s razlikom — kotač — sila desno.
function RedOsovine({ br, m, p }) {
  const losa = !!m && m.razlika_pct > LOSA_RAZLIKA
  const slabijaL = losa && m.sila_lijevo < m.sila_desno
  const slabijaD = losa && m.sila_desno < m.sila_lijevo
  const losaRucna = !!p && p.razlika_pct > LOSA_RAZLIKA
  return (
    <>
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto minmax(96px,1.1fr) auto minmax(0,1fr)', alignItems: 'center', gap: 8, padding: '8px 0 2px' }}>
      <Sila m={m} p={p} strana="L" />
      <Kotac los={slabijaL} prazan={!m} />
      <div style={{ position: 'relative', height: 58, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ position: 'absolute', left: 0, right: 0, top: '50%', height: 8, marginTop: -4, borderRadius: 4, background: m ? '#9ca3af' : 'transparent', borderTop: m ? 'none' : '2px dashed #9ca3af' }} />
        <div style={{
          position: 'relative', padding: '4px 10px', borderRadius: 999, textAlign: 'center', lineHeight: 1.2, whiteSpace: 'nowrap',
          background: losa ? 'var(--crveno, #c62828)' : (m ? '#e8f5e9' : '#f3f4f6'),
          color: losa ? '#fff' : (m ? '#1b5e20' : '#6b7280'), border: '2px solid #fff',
        }}>
          <div style={{ fontSize: 12 }}>{br}. osovina</div>
          <div style={{ fontSize: 15, fontWeight: 800 }}>
            {m ? `razlika ${m.razlika_pct.toLocaleString('hr-HR')} %` : 'nije izmjerena'}
          </div>
        </div>
      </div>
      <Kotac los={slabijaD} prazan={!m} />
      <Sila m={m} p={p} strana="D" />
    </div>
    {/* Ručna kočnica ima svoju razliku lijevo/desno (isti prag kao radna). */}
    <div style={{ textAlign: 'center', minHeight: 6, paddingBottom: 6 }}>
      {p && (
        <span style={{
          display: 'inline-block', padding: '2px 10px', borderRadius: 999, fontSize: 13, fontWeight: 700,
          background: losaRucna ? 'var(--crveno, #c62828)' : '#f3f4f6', color: losaRucna ? '#fff' : '#374151',
        }}>
          ručna: razlika {p.razlika_pct.toLocaleString('hr-HR')} %
        </span>
      )}
    </div>
    </>
  )
}

// Crtež vozila odozgo: po jedan red za svaku osovinu (i one koje nisu izmjerene, da se vidi da fale).
export function CrtezOsovina({ mjerenja }) {
  const vazeca = mjerenja.filter((m) => m.vazece)
  if (!vazeca.length) return null
  const radna = {}; const parkirna = {}
  vazeca.forEach((m) => { (m.vrsta === 'parkirna' ? parkirna : radna)[m.osovina] = m })
  const zadnja = Math.max(...vazeca.map((m) => m.osovina))
  const brojevi = Array.from({ length: zadnja }, (_, i) => i + 1)
  return (
    <div style={{ marginTop: 10, maxWidth: 520 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
        <span>Lijevo</span><span>▲ prednji kraj</span><span>Desno</span>
      </div>
      {brojevi.map((br) => <RedOsovine key={br} br={br} m={radna[br]} p={parkirna[br]} />)}
      <div style={{ fontSize: 12, color: 'var(--muted)' }}>
        Najveća sila kočenja po kotaču. Razlika veća od {LOSA_RAZLIKA} % je crvena (slabiji kotač označen) — vrijedi i za ručnu.
      </div>
    </div>
  )
}

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
          <div style={{ marginTop: 6 }}><OdabirNaloga disabled={radi} onOdaberi={vezi} /></div>
          {t.kandidati.length > 0 && <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 8 }}>ili odaberi nalog koji je u radu:</div>}
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
          </div>
          {greska && <div style={{ color: 'var(--crveno)', fontSize: 13 }}>{greska}</div>}
        </div>
      )}
      <CrtezOsovina mjerenja={t.mjerenja} />
      {povijest && <TablicaMjerenja mjerenja={t.mjerenja} sveVerzije />}
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
      const r = (await api.cartecNaloziZaGb(gb.trim())) || []
      if (r.length === 1) { onOdaberi(r[0].id); return }       // jedan otvoren nalog → odmah veži
      setNalozi(r)
    } catch { setNalozi([]) }
  }
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <input value={gb} inputMode="numeric" placeholder="Upiši GB" onChange={(e) => { setGb(e.target.value.replace(/\D/g, '')); setNalozi(null) }}
        onKeyDown={(e) => { if (e.key === 'Enter') trazi() }}
        style={{ width: 130, margin: 0, padding: '10px 12px', fontSize: 20, fontWeight: 700 }} />
      <button className="btn" disabled={disabled || !gb} style={{ width: 'auto', margin: 0 }} onClick={trazi}>Potvrdi</button>
      {nalozi && !nalozi.length && <small style={{ color: 'var(--crveno, #c62828)' }}>GB {gb} nema otvoren nalog</small>}
      {nalozi && nalozi.length > 1 && <small style={{ color: 'var(--muted)' }}>GB {gb} ima više naloga — odaberi:</small>}
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
    <Layout naslov="Testovi kočnica" nazad={true}>
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
