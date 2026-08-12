import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Bedz, MikrofonGumb, Spinner, ULOGA, datum, voziloLabel } from '../ui'
import { useT } from '../i18n'

export default function Sifrarnik() {
  const { t } = useT()
  const [tab, setTab] = useState('korisnici')
  return (
    <Layout naslov={t('sif.title')}>
      <div className="chips">
        <span className={`chip ${tab === 'korisnici' ? 'akt' : ''}`} onClick={() => setTab('korisnici')}>{t('sif.korisnici')}</span>
        <span className={`chip ${tab === 'vozila' ? 'akt' : ''}`} onClick={() => setTab('vozila')}>{t('sif.vozila')}</span>
        <span className={`chip ${tab === 'dijelovi' ? 'akt' : ''}`} onClick={() => setTab('dijelovi')}>{t('sif.dijelovi')}</span>
      </div>
      {tab === 'korisnici' && <Korisnici />}
      {tab === 'vozila' && <Vozila />}
      {tab === 'dijelovi' && <PretragaDijelova />}
    </Layout>
  )
}

// Globalna pretraga povijesti dijelova po nazivu (kroz sve kamione).
function PretragaDijelova() {
  const { t } = useT()
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')

  useEffect(() => {
    let poništen = false
    const tmr = setTimeout(() => {
      api.pretraziDijelove(q)
        .then((r) => { if (!poništen) setLista(r) })
        .catch((e) => { if (!poništen) setGreska(e.message) })
    }, 250)
    return () => { poništen = true; clearTimeout(tmr) }
  }, [q])

  return (
    <>
      {greska && <div className="greska">{greska}</div>}
      <div className="polje-mik">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('sif.pretraziDio')}
          autoFocus
        />
        <MikrofonGumb naslov={t('sif.izgovoriDio')} onTekst={(tekst) => setQ(tekst)} />
      </div>

      {lista === null ? (
        <p className="meta" style={{ marginTop: 12 }}>{t('common.ucitavam')}</p>
      ) : lista.length === 0 ? (
        <p className="meta" style={{ marginTop: 12 }}>
          {q.trim() ? t('sif.nemaRezultata', { q: q.trim() }) : t('sif.josNema')}
        </p>
      ) : (
        <>
          <p className="meta" style={{ marginTop: 12 }}>{lista.length} {t('sif.rezultata')}</p>
          <div className="dio-lista">
            {lista.map((z) => (
              <div key={z.id} className="dio-zapis dio-klik" onClick={() => nav(`/vozila/${z.vozilo.id}`)}>
                <div className="dio-glava">
                  <strong>{z.naziv}</strong>
                  <span className="dio-datum">{datum(z.datum)}</span>
                </div>
                <p className="meta" style={{ margin: '2px 0 0' }}>🚚 <strong>{z.vozilo.gb}</strong></p>
                {z.razlog && <p className="dio-razlog">{z.razlog}</p>}
                <p className="meta">
                  {z.kilometraza != null && <>🧭 {z.kilometraza.toLocaleString('hr-HR')} km · </>}
                  {z.promijenio?.ime} ›
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  )
}

function Korisnici() {
  const { t } = useT()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [otvori, setOtvori] = useState(false)
  const [f, setF] = useState({ ime: '', korisnicko_ime: '', lozinka: '', uloga: 'radnik', telefon: '' })

  const ucitaj = () => api.korisnici().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])

  const spremi = async (e) => {
    e.preventDefault()
    setGreska('')
    try {
      await api.kreirajKorisnika(f)
      setF({ ime: '', korisnicko_ime: '', lozinka: '', uloga: 'radnik', telefon: '' })
      setOtvori(false); ucitaj()
    } catch (err) { setGreska(err.message) }
  }

  const prebaciAktivan = async (k) => {
    await api.azurirajKorisnika(k.id, { aktivan: !k.aktivan }); ucitaj()
  }

  if (lista === null) return <Spinner />
  return (
    <>
      {greska && <div className="greska">{greska}</div>}
      {!otvori && <button className="btn" onClick={() => setOtvori(true)}>{t('sif.noviKorisnik')}</button>}
      {otvori && (
        <form className="karta" onSubmit={spremi}>
          <label>{t('sif.ime')}</label>
          <input value={f.ime} onChange={(e) => setF({ ...f, ime: e.target.value })} required />
          <label>{t('sif.korime')}</label>
          <input value={f.korisnicko_ime} onChange={(e) => setF({ ...f, korisnicko_ime: e.target.value })} autoCapitalize="none" required />
          <label>{t('sif.lozinka')}</label>
          <input value={f.lozinka} onChange={(e) => setF({ ...f, lozinka: e.target.value })} required />
          <label>{t('sif.uloga')}</label>
          <select value={f.uloga} onChange={(e) => setF({ ...f, uloga: e.target.value })}>
            {Object.keys(ULOGA).map((k) => <option key={k} value={k}>{t('uloga.' + k)}</option>)}
          </select>
          <label>{t('sif.telefonOpc')}</label>
          <input value={f.telefon} onChange={(e) => setF({ ...f, telefon: e.target.value })} />
          <div className="btn-red">
            <button className="btn mali">{t('common.spremi')}</button>
            <button type="button" className="btn sekund mali" onClick={() => setOtvori(false)}>{t('common.odustani')}</button>
          </div>
        </form>
      )}
      {lista.map((k) => (
        <div key={k.id} className="karta">
          <div className="naslov-red">
            <h3 style={{ opacity: k.aktivan ? 1 : 0.5 }}>{k.ime}</h3>
            <Bedz vrsta="srednji" tekst={t('uloga.' + k.uloga)} />
          </div>
          <p className="meta">@{k.korisnicko_ime}{k.telefon ? ` · ${k.telefon}` : ''}</p>
          <div className="btn-red">
            <button className="btn sekund mali" onClick={() => prebaciAktivan(k)}>
              {k.aktivan ? t('sif.deaktiviraj') : t('sif.aktiviraj')}
            </button>
          </div>
          <ResetLozinke korisnikId={k.id} naGresku={setGreska} />
        </div>
      ))}
    </>
  )
}

function ResetLozinke({ korisnikId, naGresku }) {
  const { t } = useT()
  const [otvori, setOtvori] = useState(false)
  const [nova, setNova] = useState('')
  const [uspjeh, setUspjeh] = useState(false)
  const [radi, setRadi] = useState(false)

  if (uspjeh) return <p className="meta" style={{ color: 'var(--zelena)', marginTop: 8 }}>{t('sif.resetiran')}</p>
  if (!otvori) {
    return (
      <button className="btn sekund mali" style={{ marginTop: 8 }} onClick={() => setOtvori(true)}>
        {t('sif.resetLoz')}
      </button>
    )
  }
  const spremi = async () => {
    if (nova.length < 4) { naGresku(t('sif.lozKratka')); return }
    setRadi(true)
    try {
      await api.azurirajKorisnika(korisnikId, { lozinka: nova })
      setUspjeh(true)
    } catch (e) { naGresku(e.message) } finally { setRadi(false) }
  }
  return (
    <div style={{ marginTop: 8 }}>
      <input type="text" placeholder={t('sif.novaLoz')} value={nova} onChange={(e) => setNova(e.target.value)} />
      <div className="btn-red">
        <button className="btn mali" onClick={spremi} disabled={radi || !nova}>{t('sif.postavi')}</button>
        <button className="btn sekund mali" onClick={() => setOtvori(false)}>{t('common.odustani')}</button>
      </div>
    </div>
  )
}

function Vozila() {
  const { t } = useT()
  const nav = useNavigate()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [otvori, setOtvori] = useState(false)
  const [uvozOtvori, setUvozOtvori] = useState(false)
  const [uvozTekst, setUvozTekst] = useState('')
  const [uvozRezultat, setUvozRezultat] = useState(null)
  const [uvozRadi, setUvozRadi] = useState(false)
  const [f, setF] = useState({ gb: '', registracija: '', marka: '', model: '' })

  const ucitaj = () => api.vozila().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])

  const spremi = async (e) => {
    e.preventDefault()
    setGreska('')
    try {
      await api.kreirajVozilo(f)
      setF({ gb: '', registracija: '', marka: '', model: '' })
      setOtvori(false); ucitaj()
    } catch (err) { setGreska(err.message) }
  }

  const uvezi = async () => {
    setGreska(''); setUvozRezultat(null); setUvozRadi(true)
    try {
      const r = await api.uvozVozila(uvozTekst)
      setUvozRezultat(r); setUvozTekst(''); ucitaj()
    } catch (err) { setGreska(err.message) } finally { setUvozRadi(false) }
  }

  if (lista === null) return <Spinner />
  return (
    <>
      {greska && <div className="greska">{greska}</div>}

      {/* Uvoz postojećih kamiona */}
      {!uvozOtvori ? (
        <button className="btn sekund" onClick={() => setUvozOtvori(true)}>{t('sif.uvezi')}</button>
      ) : (
        <div className="karta">
          <label style={{ marginTop: 0 }}>{t('sif.zalijepi')}</label>
          <p className="meta" style={{ marginTop: 0 }}>{t('sif.uvozHint')}</p>
          <textarea
            value={uvozTekst}
            onChange={(e) => setUvozTekst(e.target.value)}
            placeholder={'GB-101\nGB-102, ZG1234AB, MAN\nGB-103, ZG5678CD, Scania'}
            style={{ minHeight: 140, fontFamily: 'monospace' }}
          />
          {uvozRezultat && (
            <div className="uspjeh">{t('sif.uvozRezultat', { d: uvozRezultat.dodano, p: uvozRezultat.preskoceno, u: uvozRezultat.ukupno })}</div>
          )}
          <div className="btn-red">
            <button className="btn mali" onClick={uvezi} disabled={uvozRadi || !uvozTekst.trim()}>{uvozRadi ? t('sif.uvozim') : t('sif.uveziBtn')}</button>
            <button className="btn sekund mali" onClick={() => { setUvozOtvori(false); setUvozRezultat(null) }}>{t('sif.zatvori')}</button>
          </div>
        </div>
      )}

      {!otvori && <button className="btn" onClick={() => setOtvori(true)} style={{ marginTop: 12 }}>{t('sif.novoVozilo')}</button>}
      {otvori && (
        <form className="karta" onSubmit={spremi}>
          <label>{t('sif.gb')}</label>
          <input value={f.gb} onChange={(e) => setF({ ...f, gb: e.target.value })} required />
          <label>{t('sif.registracija')}</label>
          <input value={f.registracija} onChange={(e) => setF({ ...f, registracija: e.target.value })} />
          <label>{t('sif.marka')}</label>
          <input value={f.marka} onChange={(e) => setF({ ...f, marka: e.target.value })} />
          <label>{t('sif.model')}</label>
          <input value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} />
          <div className="btn-red">
            <button className="btn mali">{t('common.spremi')}</button>
            <button type="button" className="btn sekund mali" onClick={() => setOtvori(false)}>{t('common.odustani')}</button>
          </div>
        </form>
      )}
      {lista.map((v) => (
        <div key={v.id} className="karta klik" onClick={() => nav(`/vozila/${v.id}`)}>
          <div className="naslov-red">
            <div>
              <h3 style={{ margin: 0 }}>{v.gb}</h3>
              <p className="meta" style={{ margin: '4px 0 0' }}>{[v.marka, v.model, v.registracija].filter(Boolean).join(' · ') || '—'}</p>
            </div>
            <span className="meta" style={{ fontSize: 13 }}>{t('sif.povijest')}</span>
          </div>
        </div>
      ))}
    </>
  )
}
