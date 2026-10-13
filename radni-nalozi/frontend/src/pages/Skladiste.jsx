import { useEffect, useRef, useState } from 'react'
import Layout from '../Layout'
import { api, medijUrl } from '../api'
import { Spinner } from '../ui'
import { useT } from '../i18n'

const praznaStavka = () => ({ artikl: '', kolicina: 1, jedinica: 'kom', cijena: '' })

function praznaPrimka() {
  return { dobavljac: '', broj_otpremnice: '', datum: '', napomena: '', foto: '', stavke: [] }
}

export default function Skladiste() {
  const { t } = useT()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [poruka, setPoruka] = useState('')
  const [nova, setNova] = useState(null)       // objekt forme ili null (zatvoreno)
  const [citam, setCitam] = useState(false)    // AI čita sliku
  const [spremam, setSpremam] = useState(false)
  const fileRef = useRef(null)

  const ucitaj = () => api.primke().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])

  const zapocni = () => { setGreska(''); setPoruka(''); setNova(praznaPrimka()) }
  const odustani = () => { setNova(null); setCitam(false) }

  const slikaj = async (e) => {
    const file = e.target.files && e.target.files[0]
    if (fileRef.current) fileRef.current.value = ''   // dopusti ponovni odabir iste slike
    if (!file) return
    setGreska(''); setCitam(true)
    try {
      const fd = new FormData()
      fd.append('slika', file)
      const r = await api.procitajOtpremnicu(fd)
      setNova((prev) => {
        const baza = prev || praznaPrimka()
        return {
          dobavljac: r.dobavljac || baza.dobavljac || '',
          broj_otpremnice: r.broj_otpremnice || baza.broj_otpremnice || '',
          datum: r.datum || baza.datum || '',
          napomena: baza.napomena || '',
          foto: r.foto || baza.foto || '',
          stavke: (r.stavke && r.stavke.length ? r.stavke : baza.stavke).map((s) => ({
            artikl: s.artikl || '', kolicina: s.kolicina ?? 1,
            jedinica: s.jedinica || 'kom', cijena: s.cijena ?? '',
          })),
        }
      })
      if (!r.ai) setPoruka(t('skl.aiNedostupan'))
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
      foto: nova.foto || null,
      stavke,
    }
    if (!telo.dobavljac && !telo.broj_otpremnice && !stavke.length && !telo.foto) {
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
    try { await api.obrisiPrimku(p.id); ucitaj() } catch (err) { setGreska(err.message) }
  }

  if (lista === null) return <Layout naslov={t('skl.naslov')}><Spinner /></Layout>

  return (
    <Layout naslov={t('skl.naslov')}>
      {greska && <div className="greska">{greska}</div>}
      {poruka && <div className="uspjeh">{poruka}</div>}

      {!nova ? (
        <button className="btn" onClick={zapocni}>{t('skl.nova')}</button>
      ) : (
        <div className="karta">
          {/* Fotografija otpremnice → AI */}
          <input
            ref={fileRef} type="file" accept="image/*" capture="environment"
            onChange={slikaj} style={{ display: 'none' }}
          />
          <button className="btn sekund" onClick={() => fileRef.current && fileRef.current.click()} disabled={citam}>
            {citam ? t('skl.citam') : (nova.foto ? t('skl.ponovoSlikaj') : t('skl.slikaj'))}
          </button>
          {citam && <p className="meta">{t('skl.citamHint')}</p>}
          {nova.foto && (
            <img src={medijUrl(nova.foto)} alt={t('skl.foto')}
              style={{ maxWidth: '100%', borderRadius: 8, margin: '8px 0' }} />
          )}

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

          <label>{t('skl.stavke')}</label>
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
            </div>
          ))}
          <button className="btn sekund mali" style={{ marginTop: 6 }} onClick={dodajStavku}>{t('skl.dodajStavku')}</button>

          <label style={{ marginTop: 10 }}>{t('skl.napomena')}</label>
          <textarea value={nova.napomena} onChange={(e) => postaviPolje('napomena', e.target.value)} />

          <div className="btn-red" style={{ marginTop: 10 }}>
            <button className="btn" onClick={spremi} disabled={spremam || citam}>
              {spremam ? t('skl.spremam') : t('skl.spremi')}
            </button>
            <button className="btn sekund" onClick={odustani} disabled={spremam}>{t('skl.odustani')}</button>
          </div>
        </div>
      )}

      {/* Popis primki */}
      {!nova && (
        <div style={{ marginTop: 14 }}>
          {lista.length === 0 ? (
            <p className="meta">{t('skl.nema')}</p>
          ) : lista.map((p) => (
            <div key={p.id} className="karta">
              <div className="naslov-red">
                <h3>{p.dobavljac || t('skl.bezDobavljaca')}</h3>
                {p.datum && <span className="meta">{p.datum.split('-').reverse().join('.')}.</span>}
              </div>
              <p className="meta">
                {p.broj_otpremnice ? `${t('skl.broj')}: ${p.broj_otpremnice} · ` : ''}
                {t('skl.stavkiBr', { n: (p.stavke || []).length })}
                {p.kreirao ? ` · ${p.kreirao.ime}` : ''}
              </p>
              {(p.stavke || []).length > 0 && (
                <div className="dio-lista" style={{ marginTop: 6 }}>
                  {p.stavke.map((s, i) => (
                    <div key={i} className="steta-stavka">
                      <span>{s.artikl}</span>
                      <span className="c">
                        {s.kolicina} {s.jedinica}{s.cijena != null ? ` · ${s.cijena} €` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {p.foto_putanja && (
                <a href={medijUrl(p.foto_putanja)} target="_blank" rel="noreferrer" className="meta" style={{ display: 'inline-block', marginTop: 6 }}>
                  📷 {t('skl.foto')}
                </a>
              )}
              <div className="btn-red" style={{ marginTop: 8 }}>
                <button className="btn sekund mali" onClick={() => obrisi(p)}>{t('skl.obrisi')}</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Layout>
  )
}
