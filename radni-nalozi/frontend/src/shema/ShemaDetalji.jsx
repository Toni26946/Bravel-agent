import { useMemo } from 'react'
import {
  BOJA_STATUSA_CSS, OZNAKA_STATUSA, ZONE, zonaZaKategoriju,
} from '../shemaMapiranje'

const REDOSLIJED_LEGENDE = ['treba', 'djelomicno', 'gotovo', 'neutral']

// Legenda + popis dijelova u nalogu + detalj odabranog + ostale operacije.
// Dijele ga i 2D nacrt i 3D prikaz.
export default function ShemaDetalji({ nalog, statusi, selektiran, onSelect }) {
  const { poZoni, ostalo } = useMemo(() => {
    const poZoni = {}
    const ostalo = []
    for (const o of nalog?.operacije || []) {
      const uk = (o.zadaci || []).length
      const go = (o.zadaci || []).filter((t) => t.gotovo).length
      const z = zonaZaKategoriju(o.kategorija)
      if (!z) { ostalo.push({ o, uk, go }); continue }
      const g = poZoni[z] || (poZoni[z] = { ops: [], uk: 0, go: 0 })
      g.ops.push({ o, uk, go }); g.uk += uk; g.go += go
    }
    return { poZoni, ostalo }
  }, [nalog])

  const labela = (k) => ZONE[k] || k
  const zoneKljucevi = Object.keys(poZoni).sort((a, b) => labela(a).localeCompare(labela(b), 'hr'))
  const opsZone = poZoni[selektiran]?.ops || []

  return (
    <>
      <div className="shema-legenda">
        {REDOSLIJED_LEGENDE.map((s) => (
          <span key={s} className="shema-leg">
            <i style={{ background: BOJA_STATUSA_CSS[s] }} /> {OZNAKA_STATUSA[s]}
          </span>
        ))}
      </div>

      {zoneKljucevi.length > 0 && (
        <div className="karta" style={{ marginTop: 12 }}>
          <div className="sekcija-naslov" style={{ margin: '0 0 6px' }}>Dijelovi u ovom nalogu</div>
          {zoneKljucevi.map((k) => {
            const g = poZoni[k]
            const st = statusi[k] || 'neutral'
            return (
              <div
                key={k}
                className={`shema-red ${selektiran === k ? 'akt' : ''}`}
                onClick={() => onSelect(selektiran === k ? null : k)}
              >
                <span className="shema-tocka" style={{ background: BOJA_STATUSA_CSS[st] }} />
                <span className="shema-red-ime">{labela(k)}</span>
                <span className="c">{g.uk ? `${g.go}/${g.uk}` : `${g.ops.length} op.`}</span>
              </div>
            )
          })}
        </div>
      )}

      {selektiran && (
        <div className="karta shema-info">
          <div className="naslov-red">
            <h3 style={{ margin: 0 }}>{labela(selektiran)}</h3>
            <span className="bedz" style={{ background: BOJA_STATUSA_CSS[statusi[selektiran] || 'neutral'], color: '#fff' }}>
              {OZNAKA_STATUSA[statusi[selektiran] || 'neutral']}
            </span>
          </div>
          {opsZone.length === 0 ? (
            <p className="meta" style={{ marginTop: 6 }}>Nema operacija za ovaj dio u ovom nalogu.</p>
          ) : (
            <div style={{ marginTop: 6 }}>
              {opsZone.map(({ o, uk, go }) => (
                <div key={o.id} className="steta-stavka">
                  <span>{o.kategorija}</span>
                  <span className="c">{uk ? `${go}/${uk}` : '—'}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {ostalo.length > 0 && (
        <div className="karta" style={{ marginTop: 12 }}>
          <div className="sekcija-naslov" style={{ margin: '0 0 6px' }}>Ostale operacije (nisu vezane uz dio)</div>
          {ostalo.map(({ o, uk, go }) => (
            <div key={o.id} className="steta-stavka">
              <span>{o.kategorija}</span>
              <span className="c">{uk ? `${go}/${uk}` : '—'}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
