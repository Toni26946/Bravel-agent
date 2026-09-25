import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { Spinner } from '../ui'
import { useT } from '../i18n'

// Novi ili postojeći obrazac zaduženja kamiona/prikolice.
// Zaglavlje (registracije, datum, potpisnici) + popis opreme s +/- oznakama.
export default function ZaduzenjeDetalj({ novo = false }) {
  const { t } = useT()
  const nav = useNavigate()
  const { id } = useParams()
  const { korisnik } = useAuth()
  const [z, setZ] = useState(null)
  const [stavke, setStavke] = useState([])
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const [poruka, setPoruka] = useState('')

  useEffect(() => {
    let ziv = true
    if (novo) {
      api.zaduzenjePredlozak().then((p) => {
        if (!ziv) return
        const sve = [...(p.kamion || []), ...(p.prikolica || [])]
        setStavke(sve)
        setZ({
          kamion_registracija: '', prikolica_registracija: '', vozac: '',
          datum: new Date().toISOString().slice(0, 10),
          odradio: '', predao: '', preuzeo: '', napomena: '', status: 'u_tijeku',
        })
      }).catch(() => setGreska(t('zad.greskaUcitavanje')))
    } else {
      api.zaduzenje(id).then((d) => {
        if (!ziv) return
        setZ(d)
        setStavke(d.stavke || [])
      }).catch(() => setGreska(t('zad.greskaUcitavanje')))
    }
    return () => { ziv = false }
  }, [id, novo])

  const postavi = (polje, vrijednost) => setZ((s) => ({ ...s, [polje]: vrijednost }))

  const postaviStavku = (idx, izmjene) => {
    setStavke((lista) => lista.map((s, i) => (i === idx ? { ...s, ...izmjene } : s)))
  }

  const oznaciSve = (grupa, stanje) => {
    setStavke((lista) => lista.map((s) => (s.grupa === grupa ? { ...s, stanje, kolicina: stanje === 'da' ? s.kom : s.kolicina } : s)))
  }

  const spremi = async (noviStatus) => {
    // Obavezno: kamion, prikolica i vozač.
    const fali = []
    if (!(z.kamion_registracija || '').trim()) fali.push(t('zad.kamion'))
    if (!(z.prikolica_registracija || '').trim()) fali.push(t('zad.prikolica'))
    if (!(z.vozac || '').trim()) fali.push(t('zad.vozac'))
    if (fali.length) { setGreska(t('zad.faliPolja', { polja: fali.join(', ') })); setPoruka(''); return }
    setRadi(true); setGreska(''); setPoruka('')
    const telo = {
      kamion_registracija: z.kamion_registracija,
      kamion_gb: z.kamion_gb,
      prikolica_registracija: z.prikolica_registracija,
      prikolica_gb: z.prikolica_gb,
      vozac: z.vozac,
      datum: z.datum,
      odradio: z.odradio,
      predao: z.predao,
      preuzeo: z.preuzeo,
      napomena: z.napomena,
      status: noviStatus || z.status,
      stavke,
    }
    try {
      if (novo) {
        const kreiran = await api.kreirajZaduzenje(telo)
        nav(`/zaduzenja/${kreiran.id}`, { replace: true })
      } else {
        const az = await api.azurirajZaduzenje(id, telo)
        setZ(az); setStavke(az.stavke || [])
        setPoruka(t('zad.spremljeno'))
        setTimeout(() => setPoruka(''), 2500)
      }
    } catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }

  const obrisi = async () => {
    if (!window.confirm(t('zad.potvrdiBrisanje'))) return
    setRadi(true)
    try { await api.obrisiZaduzenje(id); nav('/zaduzenja', { replace: true }) }
    catch (e) { setGreska(e.message || 'Greška'); setRadi(false) }
  }

  const kamionStavke = useMemo(() => stavke.filter((s) => s.grupa === 'kamion'), [stavke])
  const prikolicaStavke = useMemo(() => stavke.filter((s) => s.grupa === 'prikolica'), [stavke])
  const brojPredanih = stavke.filter((s) => s.stanje === 'da').length

  if (!z) return <Layout naslov={t('tab.zaduzenja')} nazad="/zaduzenja">{greska ? <p className="greska">{greska}</p> : <Spinner />}</Layout>

  const smijeBrisati = korisnik?.uloga === 'voditelj' && !novo
  const zavrseno = z.status === 'zavrseno'

  return (
    <Layout naslov={novo ? t('zad.novo') : t('zad.naslov')} nazad="/zaduzenja">
      <div className="zad-obrazac">
        {/* Zaglavlje */}
        <div className="karta no-print-sjena">
          <div className="zad-glava">
            <div>
              <label>{t('zad.kamionReg')} <span className="zad-ob">*</span></label>
              <input className={'pretraga-input' + (!(z.kamion_registracija || '').trim() ? ' zad-prazno-ob' : '')} value={z.kamion_registracija || ''}
                onChange={(e) => postavi('kamion_registracija', e.target.value)} placeholder={t('zad.regPh')} />
            </div>
            <div>
              <label>{t('zad.prikolicaReg')} <span className="zad-ob">*</span></label>
              <input className={'pretraga-input' + (!(z.prikolica_registracija || '').trim() ? ' zad-prazno-ob' : '')} value={z.prikolica_registracija || ''}
                onChange={(e) => postavi('prikolica_registracija', e.target.value)} placeholder={t('zad.regPh')} />
            </div>
            <div>
              <label>{t('zad.vozac')} <span className="zad-ob">*</span></label>
              <input className={'pretraga-input' + (!(z.vozac || '').trim() ? ' zad-prazno-ob' : '')} value={z.vozac || ''}
                onChange={(e) => postavi('vozac', e.target.value)} placeholder={t('zad.vozacPh')} />
            </div>
            <div>
              <label>{t('zad.datum')}</label>
              <input type="date" className="pretraga-input" value={z.datum || ''}
                onChange={(e) => postavi('datum', e.target.value)} />
            </div>
          </div>
        </div>

        {/* Popis opreme */}
        <ZadGrupa naslov={'🚚 ' + t('zad.kamion')} stavke={kamionStavke} grupa="kamion"
          stavkeSve={stavke} postaviStavku={postaviStavku} oznaciSve={oznaciSve} zakljucano={zavrseno} t={t} />
        <ZadGrupa naslov={'🛻 ' + t('zad.prikolica')} stavke={prikolicaStavke} grupa="prikolica"
          stavkeSve={stavke} postaviStavku={postaviStavku} oznaciSve={oznaciSve} zakljucano={zavrseno} t={t} />

        {/* Potpisnici */}
        <div className="karta">
          <div className="zad-potpisi">
            <div>
              <label>{t('zad.odradio')}</label>
              <input className="pretraga-input" value={z.odradio || ''} onChange={(e) => postavi('odradio', e.target.value)} />
            </div>
            <div>
              <label>{t('zad.predao')}</label>
              <input className="pretraga-input" value={z.predao || ''} onChange={(e) => postavi('predao', e.target.value)} />
            </div>
            <div>
              <label>{t('zad.preuzeo')}</label>
              <input className="pretraga-input" value={z.preuzeo || ''} onChange={(e) => postavi('preuzeo', e.target.value)} />
            </div>
          </div>
          <label style={{ marginTop: 8 }}>{t('zad.napomena')}</label>
          <textarea className="pretraga-input" rows={2} value={z.napomena || ''}
            onChange={(e) => postavi('napomena', e.target.value)} />
        </div>

        <p className="meta">{t('zad.predano', { n: brojPredanih, uk: stavke.length })}</p>
        {greska && <div className="greska">{greska}</div>}
        {poruka && <div className="uspjeh">{poruka}</div>}

        <div className="btn-red no-print" style={{ flexWrap: 'wrap', gap: 8 }}>
          <button className="btn" disabled={radi} onClick={() => spremi()}>💾 {t('zad.spremi')}</button>
          {!novo && !zavrseno && (
            <button className="btn" disabled={radi} onClick={() => spremi('zavrseno')}>✅ {t('zad.zavrsi')}</button>
          )}
          {!novo && zavrseno && (
            <button className="btn sekund" disabled={radi} onClick={() => spremi('u_tijeku')}>↩️ {t('zad.vratiTijek')}</button>
          )}
          {!novo && <button className="btn sekund" onClick={() => window.print()}>🖨️ {t('zad.ispisi')}</button>}
          {smijeBrisati && <button className="btn opasno" disabled={radi} onClick={obrisi}>🗑️ {t('zad.obrisi')}</button>}
        </div>
      </div>
    </Layout>
  )
}

// Jedna grupa opreme (kamion ili prikolica) — tablica sa +/- oznakama.
function ZadGrupa({ naslov, stavke, grupa, stavkeSve, postaviStavku, oznaciSve, zakljucano, t }) {
  // Indeks stavke u punom popisu (postaviStavku radi po globalnom indeksu).
  const idxOf = (s) => stavkeSve.indexOf(s)
  return (
    <div className="karta zad-grupa">
      <div className="zad-grupa-glava">
        <strong>{naslov}</strong>
        {!zakljucano && (
          <div className="no-print" style={{ display: 'flex', gap: 6 }}>
            <button className="btn sekund mali" onClick={() => oznaciSve(grupa, 'da')}>{t('zad.sviPredani')}</button>
            <button className="btn sekund mali" onClick={() => oznaciSve(grupa, '')}>{t('zad.ocisti')}</button>
          </div>
        )}
      </div>
      <table className="zad-tab">
        <thead>
          <tr>
            <th className="zad-br">#</th>
            <th>{t('zad.oprema')}</th>
            <th className="zad-kom">{t('zad.kom')}</th>
            <th className="zad-pm">+/−</th>
            <th className="zad-nap">{t('zad.napomenaKratko')}</th>
          </tr>
        </thead>
        <tbody>
          {stavke.map((s) => {
            const gi = idxOf(s)
            return (
              <tr key={grupa + '-' + s.br} className={s.stanje === 'ne' ? 'zad-manjka' : ''}>
                <td className="zad-br">{s.br}</td>
                <td>{s.oprema}</td>
                <td className="zad-kom">{s.kom}</td>
                <td className="zad-pm">
                  <div className="zad-toggle">
                    <button
                      type="button"
                      className={'zad-btn zad-plus' + (s.stanje === 'da' ? ' akt' : '')}
                      disabled={zakljucano}
                      onClick={() => postaviStavku(gi, { stanje: s.stanje === 'da' ? '' : 'da', kolicina: s.stanje === 'da' ? s.kolicina : s.kom })}
                      aria-label={t('zad.predana')}
                    >+</button>
                    <button
                      type="button"
                      className={'zad-btn zad-minus' + (s.stanje === 'ne' ? ' akt' : '')}
                      disabled={zakljucano}
                      onClick={() => postaviStavku(gi, { stanje: s.stanje === 'ne' ? '' : 'ne' })}
                      aria-label={t('zad.manjka')}
                    >−</button>
                  </div>
                </td>
                <td className="zad-nap">
                  <input
                    className="zad-nap-inp"
                    value={s.napomena || ''}
                    disabled={zakljucano}
                    onChange={(e) => postaviStavku(gi, { napomena: e.target.value })}
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
