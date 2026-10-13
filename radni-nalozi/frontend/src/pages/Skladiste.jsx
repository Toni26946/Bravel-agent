import { useEffect, useRef, useState } from 'react'
import Layout from '../Layout'
import { api, medijUrl } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

const praznaStavka = () => ({ artikl: '', kolicina: 1, jedinica: 'kom', cijena: '' })

// Iznos retka = količina × cijena (null ako nema cijene).
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

function praznaPrimka() {
  return { dobavljac: '', broj_otpremnice: '', datum: '', napomena: '', fotografije: [], stavke: [] }
}

export default function Skladiste() {
  const { t } = useT()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [poruka, setPoruka] = useState('')
  const [nova, setNova] = useState(null)       // objekt forme ili null (zatvoreno)
  const [detalj, setDetalj] = useState(null)   // otvorena primka (pregled) ili null
  const [dodajem, setDodajem] = useState(false)   // učitavanje stranice
  const [citam, setCitam] = useState(false)       // AI čita
  const [spremam, setSpremam] = useState(false)
  const fileRef = useRef(null)

  const ucitaj = () => api.primke().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])

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
    const stavke = nova.stavke
      .filter((s) => (s.artikl || '').trim())
      .map((s) => ({
        artikl: s.artikl.trim(),
        kolicina: parseFloat(s.kolicina) || 1,
        jedinica: (s.jedinica || 'kom').trim() || 'kom',
        cijena: s.cijena === '' || s.cijena == null ? null : parseFloat(s.cijena),
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

  const izvoz = async () => {
    setGreska('')
    try {
      const blob = await api.preuzmiPrimkeExcel()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'primke.xlsx'
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
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
        <button className="btn sekund" onClick={() => setDetalj(null)}>‹ {t('skl.natrag')}</button>
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
  return (
    <Layout naslov={t('skl.naslov')}>
      {greska && <div className="greska">{greska}</div>}
      {poruka && <div className="uspjeh">{poruka}</div>}
      <div className="btn-red">
        <button className="btn" onClick={zapocni}>{t('skl.nova')}</button>
        {lista.length > 0 && (
          <button className="btn sekund" onClick={izvoz}>{t('skl.izvoz')}</button>
        )}
      </div>

      <div style={{ marginTop: 14 }}>
        {lista.length === 0 ? (
          <p className="meta">{t('skl.nema')}</p>
        ) : lista.map((p) => {
          const str = (p.fotografije && p.fotografije.length ? p.fotografije : (p.foto_putanja ? [p.foto_putanja] : []))
          const uk = zbrojStavki(p.stavke)
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
            </div>
          )
        })}
      </div>
    </Layout>
  )
}
