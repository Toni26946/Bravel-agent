import { useEffect, useMemo, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { MikrofonGumb, Prazno, Spinner, datum } from '../ui'
import { useT } from '../i18n'
import GlasovnaSteta from '../GlasovnaSteta'

// Formatiranje eura (približno — cijele brojke).
function eur(n) {
  const v = Math.round(Number(n) || 0)
  try {
    return v.toLocaleString('hr-HR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
  } catch (_) {
    return `${v} €`
  }
}

export default function Steta() {
  const { t } = useT()
  const [lista, setLista] = useState(null)
  const [vozila, setVozila] = useState([])
  const [vozaci, setVozaci] = useState([])
  const [greska, setGreska] = useState('')
  const [otvori, setOtvori] = useState(false)

  const ucitaj = () => api.stete().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => {
    ucitaj()
    api.vozila().then(setVozila).catch(() => {})
    api.korisnici('vozac').then(setVozaci).catch(() => {})
  }, [])

  const ukupno = useMemo(() => (lista || []).reduce((s, x) => s + (x.procjena || 0), 0), [lista])

  // Zbroj po vozaču (za odgovornost) — najveći prvi.
  const poVozacu = useMemo(() => {
    const m = new Map()
    for (const s of lista || []) {
      const ime = s.vozac?.ime || 'Bez vozača'
      m.set(ime, (m.get(ime) || 0) + (s.procjena || 0))
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [lista])

  const obrisi = async (s) => {
    if (!window.confirm(t('steta.obrisati'))) return
    try { await api.obrisiStetu(s.id); ucitaj() } catch (e) { setGreska(e.message) }
  }

  if (lista === null) return <Layout naslov={t('tab.steta')}><Spinner /></Layout>

  return (
    <Layout naslov={t('tab.steta')}>
      {greska && <div className="greska">{greska}</div>}

      {/* Ukupno + razrada po vozaču */}
      <div className="karta steta-total">
        <div className="iznos">{eur(ukupno)}</div>
        <div className="opis">{t('steta.ukupno')} · {lista.length} {t('steta.stavki')}</div>
      </div>
      {poVozacu.length > 0 && (
        <div className="karta">
          <div className="sekcija-naslov" style={{ margin: '0 0 6px' }}>{t('steta.poVozacu')}</div>
          {poVozacu.map(([ime, iznos]) => (
            <div key={ime} className="steta-stavka">
              <span>{ime}</span>
              <span className="c">{eur(iznos)}</span>
            </div>
          ))}
        </div>
      )}

      {!otvori && <button className="btn" onClick={() => setOtvori(true)}>{t('steta.nova')}</button>}
      {otvori && (
        <NovaSteta
          vozila={vozila}
          vozaci={vozaci}
          naGresku={setGreska}
          naSpremljeno={() => { setOtvori(false); ucitaj() }}
          naOdustani={() => setOtvori(false)}
        />
      )}

      {/* Popis šteta */}
      {lista.length === 0 && !otvori && <Prazno emo="💥" tekst={t('steta.prazno')} />}
      {lista.map((s) => (
        <div key={s.id} className="karta">
          <div className="naslov-red">
            <div>
              <h3 style={{ margin: 0 }}>🚚 {s.vozilo?.gb || t('steta.bezKamiona')}</h3>
              {s.vozac && <p className="meta" style={{ margin: '4px 0 0' }}>🚛 {s.vozac.ime}</p>}
            </div>
            <span className="steta-iznos-veliki">{eur(s.procjena)}</span>
          </div>
          <p style={{ margin: '10px 0 0', whiteSpace: 'pre-wrap' }}>{s.opis}</p>

          {s.stavke && s.stavke.length > 0 && (
            <div style={{ marginTop: 10 }}>
              {s.stavke.map((st, i) => (
                <div key={i} className="steta-stavka">
                  <span>{st.naziv}</span>
                  <span className="c">{eur(st.cijena)}</span>
                </div>
              ))}
            </div>
          )}
          {s.obrazlozenje && <p className="meta" style={{ marginTop: 8, fontStyle: 'italic' }}>🤖 {s.obrazlozenje}</p>}

          <div className="naslov-red" style={{ marginTop: 12, alignItems: 'center' }}>
            <span className="meta">{s.kreirao?.ime} · {datum(s.kreiran)}</span>
            <button className="btn opasno mali" onClick={() => obrisi(s)}>{t('common.obrisi')}</button>
          </div>
        </div>
      ))}
    </Layout>
  )
}

// --- Forma: nova šteta -------------------------------------------------------
function NovaSteta({ vozila, vozaci, naSpremljeno, naOdustani, naGresku }) {
  const { t } = useT()
  const [gb, setGb] = useState('')
  const [vozacId, setVozacId] = useState('')
  const [opis, setOpis] = useState('')
  const [procjena, setProcjena] = useState('')
  const [stavke, setStavke] = useState([])
  const [obrazlozenje, setObrazlozenje] = useState('')
  const [aiRadi, setAiRadi] = useState(false)
  const [aiPoruka, setAiPoruka] = useState('')
  const [radi, setRadi] = useState(false)
  const [glasOtvoren, setGlasOtvoren] = useState(false)
  const [napomene, setNapomene] = useState([])

  const vozilo = vozila.find((v) => v.gb.toLowerCase() === gb.trim().toLowerCase())
  const gbNijeNadjen = gb.trim() && !vozilo

  const primiGlas = ({ vozilo: v, vozacId: zid, opis: o, napomene: nap }) => {
    if (v) setGb(v.gb)
    if (zid) setVozacId(zid)
    if (o) setOpis(o)
    setNapomene(nap || [])
    setGlasOtvoren(false)
  }

  const procijeni = async () => {
    if (!opis.trim()) return
    setAiRadi(true); setAiPoruka(''); naGresku('')
    try {
      const r = await api.procijeniStetu(opis.trim(), vozilo?.id || null)
      setProcjena(String(Math.round(r.procjena || 0)))
      setStavke(r.stavke || [])
      setObrazlozenje(r.obrazlozenje || '')
    } catch (e) {
      // Ako AI nije konfiguriran (503) ili padne — dopusti ručni unos.
      setAiPoruka(e.message + t('steta.rucno'))
    } finally { setAiRadi(false) }
  }

  const spremi = async () => {
    if (!opis.trim()) { naGresku(t('steta.opisiSto')); return }
    if (gbNijeNadjen) { naGresku(t('steta.gbNePostoji')); return }
    setRadi(true); naGresku('')
    try {
      await api.kreirajStetu({
        opis: opis.trim(),
        vozilo_id: vozilo?.id || null,
        vozac_id: vozacId ? Number(vozacId) : null,
        procjena: Number(procjena) || 0,
        obrazlozenje: obrazlozenje || null,
        stavke,
      })
      naSpremljeno()
    } catch (e) { naGresku(e.message); setRadi(false) }
  }

  return (
    <div className="karta">
      <button type="button" className="btn" style={{ marginTop: 0 }} onClick={() => setGlasOtvoren(true)}>
        {t('steta.izgovori')}
      </button>
      {napomene.length > 0 && (
        <div className="greska" style={{ background: '#fff8e1', color: '#8d6e00' }}>
          {napomene.map((n, i) => <div key={i}>⚠️ {n}</div>)}
        </div>
      )}
      {glasOtvoren && (
        <GlasovnaSteta
          vozila={vozila}
          vozaci={vozaci}
          onPopuni={primiGlas}
          onZatvori={() => setGlasOtvoren(false)}
        />
      )}

      <label>{t('steta.kamion')}</label>
      <input
        list="steta-gb"
        value={gb}
        onChange={(e) => setGb(e.target.value)}
        placeholder={t('steta.phGb')}
        autoCapitalize="characters"
      />
      <datalist id="steta-gb">
        {vozila.map((v) => (
          <option key={v.id} value={v.gb}>{[v.marka, v.registracija].filter(Boolean).join(' · ')}</option>
        ))}
      </datalist>
      {gbNijeNadjen && <p className="meta" style={{ color: 'var(--crvena)' }}>{t('steta.gbNema')}</p>}

      <label>{t('steta.vozac')}</label>
      <select value={vozacId} onChange={(e) => setVozacId(e.target.value)}>
        <option value="">{t('steta.bezVozaca')}</option>
        {vozaci.map((v) => <option key={v.id} value={v.id}>{v.ime}</option>)}
      </select>

      <label>{t('steta.sto')}</label>
      <div className="polje-mik">
        <textarea
          value={opis}
          onChange={(e) => setOpis(e.target.value)}
          placeholder={t('steta.phOpis')}
        />
        <MikrofonGumb naslov={t('steta.diktiraj')} onTekst={(tekst) => setOpis((v) => (v ? v + ' ' : '') + tekst)} />
      </div>

      <button type="button" className="btn sekund" onClick={procijeni} disabled={aiRadi || !opis.trim()}>
        {aiRadi ? t('steta.procjenjujem') : t('steta.procijeni')}
      </button>
      {aiPoruka && <p className="meta" style={{ color: 'var(--narancasta)', marginTop: 6 }}>{aiPoruka}</p>}

      {stavke.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {stavke.map((st, i) => (
            <div key={i} className="steta-stavka">
              <span>{st.naziv}</span>
              <span className="c">{eur(st.cijena)}</span>
            </div>
          ))}
        </div>
      )}
      {obrazlozenje && <p className="meta" style={{ marginTop: 8, fontStyle: 'italic' }}>🤖 {obrazlozenje}</p>}

      <label>{t('steta.trosak')}</label>
      <input
        type="number"
        inputMode="numeric"
        step="10"
        min="0"
        value={procjena}
        onChange={(e) => setProcjena(e.target.value)}
        placeholder="0"
      />

      <div className="btn-red">
        <button className="btn mali" onClick={spremi} disabled={radi || !opis.trim()}>
          {radi ? t('common.spremam') : t('steta.spremiStetu')}
        </button>
        <button className="btn sekund mali" onClick={naOdustani}>{t('common.odustani')}</button>
      </div>
    </div>
  )
}
