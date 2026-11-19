import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { CrtezOsovina } from './TestoviKocnica'

// Samostalna stranica jednog testa kočnica — otvara se iz obavijesti, BEZ prijave i bez izbornika.
// Gore crtež osovina, dolje upis GB-a vozila koje je bilo na valjcima.

const vrijeme = (iso) => { try { return new Date(iso).toLocaleTimeString('hr-HR', { hour: '2-digit', minute: '2-digit' }) } catch { return '' } }
const dan = (iso) => { try { return new Date(iso).toLocaleDateString('hr-HR') } catch { return '' } }

export default function KocniceJavno() {
  const { oznaka } = useParams()
  const [t, setT] = useState(null)
  const [greska, setGreska] = useState('')
  const [gb, setGb] = useState('')
  const [izbor, setIzbor] = useState(null)
  const [radi, setRadi] = useState(false)
  const [mijenjam, setMijenjam] = useState(false)

  useEffect(() => {
    api.kocniceJavno(oznaka).then(setT).catch((e) => setGreska(e.message || 'Poveznica ne vrijedi'))
  }, [oznaka])

  const spremi = async (nalogId) => {
    if (!gb.trim()) return
    setRadi(true); setGreska('')
    try {
      const r = await api.kocniceJavnoGb(oznaka, gb.trim(), nalogId)
      if (r.izbor) { setIzbor(r.izbor) } else { setT(r.test); setIzbor(null); setMijenjam(false); setGb('') }
    } catch (e) { setGreska(e.message) } finally { setRadi(false) }
  }

  const okvir = { maxWidth: 560, margin: '0 auto', padding: 16 }
  if (!t) return <div style={okvir}>{greska ? <div className="card" style={{ color: 'var(--crveno, #c62828)' }}>{greska}</div> : 'Učitavam…'}</div>

  const vezan = t.status === 'vezan' && t.gb
  return (
    <div style={okvir}>
      <div className="card">
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>Test kočnica s valjaka</div>
        <div style={{ fontSize: 22, fontWeight: 800 }}>{vrijeme(t.pocetak)} · {dan(t.pocetak)}</div>
        <CrtezOsovina mjerenja={t.mjerenja} />
      </div>

      <div className="card">
        {vezan && !mijenjam ? (
          <>
            <div style={{ fontSize: 13, color: 'var(--muted)' }}>Vozilo</div>
            <div style={{ fontSize: 30, fontWeight: 800 }}>GB {t.gb}</div>
            <div style={{ fontSize: 14, color: 'var(--muted)' }}>
              {t.nalog ? `Nalog ${t.nalog.broj}` : 'Bez otvorenog naloga'}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
              <button className="btn ghost" style={{ width: 'auto', margin: 0 }} onClick={() => setMijenjam(true)}>Promijeni GB</button>
              <button className="btn ghost" disabled={radi} style={{ width: 'auto', margin: 0 }} onClick={async () => {
                setRadi(true); setGreska('')
                try { setT((await api.kocniceJavnoPonisti(oznaka)).test) } catch (e) { setGreska(e.message) } finally { setRadi(false) }
              }}>Obriši GB</button>
            </div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 18, fontWeight: 800 }}>Koje vozilo je bilo na valjcima?</div>
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <input value={gb} inputMode="numeric" autoFocus placeholder="GB"
                onChange={(e) => { setGb(e.target.value.replace(/\D/g, '')); setIzbor(null); setGreska('') }}
                onKeyDown={(e) => { if (e.key === 'Enter') spremi() }}
                style={{ flex: 1, margin: 0, padding: '14px 16px', fontSize: 28, fontWeight: 800, textAlign: 'center' }} />
              <button className="btn" disabled={radi || !gb} style={{ width: 'auto', margin: 0, padding: '0 22px', fontSize: 18 }} onClick={() => spremi()}>Spremi</button>
            </div>
            {izbor && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 14, color: 'var(--muted)' }}>GB {gb} ima više otvorenih naloga — odaberi:</div>
                {izbor.map((n) => (
                  <button key={n.id} className="btn ghost" disabled={radi} style={{ marginTop: 6, textAlign: 'left' }} onClick={() => spremi(n.id)}>
                    {n.broj}{n.naslov ? ` · ${n.naslov}` : ''}
                  </button>
                ))}
              </div>
            )}
            {mijenjam && <button className="btn ghost" style={{ width: 'auto', marginTop: 10 }} onClick={() => { setMijenjam(false); setIzbor(null); setGreska('') }}>Odustani</button>}
          </>
        )}
        {greska && <div style={{ color: 'var(--crveno, #c62828)', marginTop: 8 }}>{greska}</div>}
      </div>
    </div>
  )
}
