import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { useT } from '../i18n'
import { KategorijaPicker, MikrofonGumb, voziloLabel } from '../ui'
import GlasovniUnos from '../GlasovniUnos'

export default function NoviNalog() {
  const nav = useNavigate()
  const { korisnik } = useAuth()
  const { t } = useT()
  const [params] = useSearchParams()
  const prijavaId = params.get('prijava')

  const [vozila, setVozila] = useState([])
  const [voditelji, setVoditelji] = useState([])
  const [vozaci, setVozaci] = useState([])

  // korak 1 — kamion po GB
  const [gb, setGb] = useState('')
  const [vozilo, setVozilo] = useState(null)
  const [gbGreska, setGbGreska] = useState('')

  // korak 2 — osobe
  const [voditeljId, setVoditeljId] = useState('')
  const [vozacId, setVozacId] = useState('')

  // korak 3 — operacije
  const [operacije, setOperacije] = useState([]) // [{kategorija, zadaci:[str]}]

  const [greska, setGreska] = useState('')
  const [radi, setRadi] = useState(false)

  // glasovni unos
  const [glasOtvoren, setGlasOtvoren] = useState(false)
  const [glasNapomene, setGlasNapomene] = useState([])

  const primiGlas = ({ vozilo: v, voditeljId: vid, vozacId: zid, operacije: ops, napomene }) => {
    if (v) { setVozilo(v); setGb(v.gb); setGbGreska('') }
    if (vid) setVoditeljId(vid)
    if (zid) setVozacId(zid)
    if (ops && ops.length) setOperacije(ops)
    setGlasNapomene(napomene || [])
    setGlasOtvoren(false)
  }

  useEffect(() => {
    Promise.all([api.vozila(), api.korisnici('voditelj'), api.korisnici('vozac')])
      .then(([v, vd, vz]) => {
        setVozila(v); setVoditelji(vd); setVozaci(vz)
        if (korisnik.uloga === 'voditelj') setVoditeljId(String(korisnik.id))
      })
      .catch((e) => setGreska(e.message))
  }, [])

  // Predpopuni GB iz prijave kvara
  useEffect(() => {
    if (!prijavaId || vozila.length === 0) return
    api.prijava(prijavaId).then((p) => {
      const v = vozila.find((x) => x.id === p.vozilo_id)
      if (v) { setVozilo(v); setGb(v.gb) }
    }).catch(() => {})
  }, [prijavaId, vozila])

  const pronadji = () => {
    setGbGreska('')
    const trazeni = gb.trim().toLowerCase()
    if (!trazeni) return
    const v = vozila.find((x) => x.gb.toLowerCase() === trazeni)
    if (!v) { setVozilo(null); setGbGreska(t('noviNalog.gbNema')); return }
    setVozilo(v)
  }

  const dodajOperaciju = (kategorija) => {
    const k = (kategorija || '').trim()
    if (!k) return
    setOperacije((o) => [...o, { kategorija: k, zadaci: [''] }])
  }
  const makniOperaciju = (i) => setOperacije((o) => o.filter((_, idx) => idx !== i))
  const promijeniZadatak = (oi, zi, val) =>
    setOperacije((o) => o.map((op, idx) => idx !== oi ? op : { ...op, zadaci: op.zadaci.map((z, j) => j === zi ? val : z) }))
  const dodajZadatak = (oi) =>
    setOperacije((o) => o.map((op, idx) => idx !== oi ? op : { ...op, zadaci: [...op.zadaci, ''] }))
  const makniZadatak = (oi, zi) =>
    setOperacije((o) => o.map((op, idx) => idx !== oi ? op : { ...op, zadaci: op.zadaci.filter((_, j) => j !== zi) }))

  const spremi = async () => {
    setGreska('')
    if (!vozilo) { setGreska(t('noviNalog.prvoKamion')); return }
    if (!voditeljId) { setGreska(t('noviNalog.odaberiVoditelja')); return }
    setRadi(true)
    try {
      const cisteOperacije = operacije
        .map((op) => ({ kategorija: op.kategorija, zadaci: op.zadaci.map((z) => z.trim()).filter(Boolean) }))
        .filter((op) => op.kategorija)
      const r = await api.kreirajNalog({
        vozilo_id: vozilo.id,
        voditelj_id: Number(voditeljId),
        vozac_id: vozacId ? Number(vozacId) : null,
        prijava_id: prijavaId ? Number(prijavaId) : null,
        operacije: cisteOperacije,
      })
      nav(`/nalozi/${r.nalog.id}${r.spojeno ? '?spojeno=1' : ''}`, { replace: true })
    } catch (err) {
      setGreska(err.message); setRadi(false)
    }
  }

  return (
    <Layout naslov={t('noviNalog.title')} nazad={true}>
      {greska && <div className="greska">{greska}</div>}

      <button type="button" className="btn" onClick={() => setGlasOtvoren(true)}>
        {t('noviNalog.diktiraj')}
      </button>
      {glasNapomene.length > 0 && (
        <div className="greska" style={{ background: '#fff8e1', color: '#8d6e00' }}>
          {glasNapomene.map((n, i) => <div key={i}>⚠️ {n}</div>)}
        </div>
      )}

      {glasOtvoren && (
        <GlasovniUnos
          vozila={vozila}
          voditelji={voditelji}
          vozaci={vozaci}
          onPopuni={primiGlas}
          onZatvori={() => setGlasOtvoren(false)}
        />
      )}

      {/* Korak 1 — kamion */}
      <div className="sekcija-naslov">{t('noviNalog.korak1')}</div>
      {!vozilo ? (
        <div className="karta">
          <div className="btn-red" style={{ marginTop: 0 }}>
            <input
              value={gb}
              onChange={(e) => setGb(e.target.value)}
              placeholder={t('noviNalog.phGb')}
              onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), pronadji())}
              autoCapitalize="characters"
            />
            <button type="button" className="btn mali" onClick={pronadji} style={{ minWidth: 100 }}>{t('noviNalog.pronadji')}</button>
          </div>
          {gbGreska && <p className="meta" style={{ color: 'var(--crvena)', marginTop: 8 }}>{gbGreska}</p>}
        </div>
      ) : (
        <div className="karta">
          <div className="naslov-red">
            <div>
              <h3 style={{ margin: 0 }}>🚚 {vozilo.gb}</h3>
              <p className="meta" style={{ margin: '4px 0 0' }}>
                {[vozilo.marka, vozilo.model, vozilo.registracija].filter(Boolean).join(' · ') || '—'}
              </p>
            </div>
            <button type="button" className="btn sekund mali" onClick={() => { setVozilo(null); setGb('') }}>{t('noviNalog.promijeni')}</button>
          </div>
        </div>
      )}

      {/* Korak 2 — osobe (tek kad je kamion nađen) */}
      {vozilo && (
        <>
          <div className="sekcija-naslov">{t('noviNalog.korak2')}</div>
          <div className="karta">
            <label style={{ marginTop: 0 }}>{t('noviNalog.voditelj')}</label>
            <select value={voditeljId} onChange={(e) => setVoditeljId(e.target.value)}>
              <option value="">{t('noviNalog.odaberi')}</option>
              {voditelji.map((v) => <option key={v.id} value={v.id}>{v.ime}</option>)}
            </select>
            <label>{t('noviNalog.vozacOpc')}</label>
            <select value={vozacId} onChange={(e) => setVozacId(e.target.value)}>
              <option value="">{t('noviNalog.bezVozaca')}</option>
              {vozaci.map((v) => <option key={v.id} value={v.id}>{v.ime}</option>)}
            </select>
          </div>
        </>
      )}

      {/* Korak 3 — operacije (tek kad je kamion nađen) */}
      {vozilo && (
        <>
          <div className="sekcija-naslov">{t('noviNalog.korak3')}</div>

          {operacije.map((op, oi) => (
            <div key={oi} className="karta">
              <div className="naslov-red">
                <h3 style={{ margin: 0 }}>{op.kategorija}</h3>
                <span className="x" onClick={() => makniOperaciju(oi)}>×</span>
              </div>
              {op.zadaci.map((z, zi) => (
                <div key={zi} className="btn-red" style={{ marginTop: 8, alignItems: 'stretch' }}>
                  <input value={z} onChange={(e) => promijeniZadatak(oi, zi, e.target.value)} placeholder={`${t('noviNalog.zadatak')} ${zi + 1}`} />
                  <MikrofonGumb naslov={t('op.diktirajZadatak')} onTekst={(tekst) => promijeniZadatak(oi, zi, (z ? z + ' ' : '') + tekst)} />
                  {op.zadaci.length > 1 && <span className="x" onClick={() => makniZadatak(oi, zi)}>×</span>}
                </div>
              ))}
              <button type="button" className="btn sekund mali" style={{ marginTop: 8 }} onClick={() => dodajZadatak(oi)}>{t('noviNalog.dodajZadatak')}</button>
            </div>
          ))}

          <div className="karta">
            <label style={{ marginTop: 0 }}>{t('noviNalog.dodajOperaciju')}</label>
            <KategorijaPicker onOdaberi={dodajOperaciju} />
          </div>

          <button className="btn" onClick={spremi} disabled={radi} style={{ marginTop: 8 }}>
            {radi ? t('noviNalog.kreiram') : t('noviNalog.kreiraj')}
          </button>
        </>
      )}
    </Layout>
  )
}
