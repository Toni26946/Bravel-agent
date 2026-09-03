import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Bedz, MikrofonGumb, Spinner, ULOGA } from '../ui'
import { useT } from '../i18n'

// mala slova + bez kvačica — za pretragu neosjetljivu na dijakritike
function _norm(s) {
  return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
}

export default function Sifrarnik() {
  const { t } = useT()
  const [tab, setTab] = useState('korisnici')
  return (
    <Layout naslov={t('sif.title')}>
      <div className="chips">
        <span className={`chip ${tab === 'korisnici' ? 'akt' : ''}`} onClick={() => setTab('korisnici')}>{t('sif.korisnici')}</span>
        <span className={`chip ${tab === 'vozila' ? 'akt' : ''}`} onClick={() => setTab('vozila')}>{t('sif.vozila')}</span>
      </div>
      {tab === 'korisnici' && <Korisnici />}
      {tab === 'vozila' && <Vozila />}
    </Layout>
  )
}

function Korisnici() {
  const { t } = useT()
  const [lista, setLista] = useState(null)
  const [greska, setGreska] = useState('')
  const [otvori, setOtvori] = useState(false)
  const [f, setF] = useState({ ime: '', korisnicko_ime: '', lozinka: '', uloga: 'radnik', telefon: '' })

  // uvoz radnika
  const [uvozOtvori, setUvozOtvori] = useState(false)
  const [uvozTekst, setUvozTekst] = useState('')
  const [uvozLozinka, setUvozLozinka] = useState('radnik123')
  const [uvozRezultat, setUvozRezultat] = useState(null)
  const [uvozRadi, setUvozRadi] = useState(false)

  const ucitaj = () => api.korisnici().then(setLista).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj() }, [])

  const uvezi = async () => {
    setGreska(''); setUvozRezultat(null); setUvozRadi(true)
    try {
      const r = await api.uvozKorisnika(uvozTekst, 'radnik', uvozLozinka)
      setUvozRezultat(r); setUvozTekst(''); ucitaj()
    } catch (e) { setGreska(e.message) } finally { setUvozRadi(false) }
  }

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

      {/* Uvoz radnika iz popisa imena */}
      {!uvozOtvori ? (
        <button className="btn sekund" onClick={() => setUvozOtvori(true)}>{t('sif.uvoziRadnike')}</button>
      ) : (
        <div className="karta">
          <label style={{ marginTop: 0 }}>{t('sif.zalijepiImena')}</label>
          <p className="meta" style={{ marginTop: 0 }}>{t('sif.uvozRadHint')}</p>
          <textarea
            value={uvozTekst}
            onChange={(e) => setUvozTekst(e.target.value)}
            placeholder={'Kobeščak Davor\nAzinović Mario\nKarthik Raju'}
            style={{ minHeight: 140 }}
          />
          <label>{t('sif.pocetnaLozinka')}</label>
          <input value={uvozLozinka} onChange={(e) => setUvozLozinka(e.target.value)} />
          {uvozRezultat && (
            <>
              <div className="uspjeh">{t('sif.uvozRadRezultat', { d: uvozRezultat.dodano, p: uvozRezultat.preskoceno, l: uvozRezultat.lozinka })}</div>
              {uvozRezultat.korisnici.length > 0 && (
                <div className="dio-lista" style={{ marginTop: 8 }}>
                  {uvozRezultat.korisnici.map((u) => (
                    <div key={u.korisnicko_ime} className="steta-stavka">
                      <span>{u.ime}</span>
                      <span className="c">@{u.korisnicko_ime}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
          <div className="btn-red">
            <button className="btn mali" onClick={uvezi} disabled={uvozRadi || !uvozTekst.trim()}>{uvozRadi ? t('sif.uvozim') : t('sif.uveziBtn')}</button>
            <button className="btn sekund mali" onClick={() => { setUvozOtvori(false); setUvozRezultat(null) }}>{t('sif.zatvori')}</button>
          </div>
        </div>
      )}

      {!otvori && <button className="btn" onClick={() => setOtvori(true)} style={{ marginTop: 12 }}>{t('sif.noviKorisnik')}</button>}
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
    if (nova.length < 8) { naGresku(t('sif.lozKratka')); return }
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

  // Tražilica vozila po garažnom broju (i registraciji/marki)
  const [q, setQ] = useState('')

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

  const nq = _norm(q.trim())
  const trazi = nq.length > 0
  const prikazana = trazi
    ? lista.filter((v) => _norm(`${v.gb} ${v.registracija || ''} ${v.marka || ''} ${v.model || ''}`).includes(nq))
    : lista

  return (
    <>
      {greska && <div className="greska">{greska}</div>}

      {/* Tražilica vozila po garažnom broju */}
      <div className="polje-mik">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('sif.traziVozilo')} />
        <MikrofonGumb naslov={t('sif.traziVozilo')} onTekst={(tekst) => setQ(tekst)} />
      </div>

      {trazi && <p className="meta" style={{ marginTop: 12 }}>{prikazana.length} {t('sif.rezultata')}</p>}
      {prikazana.length === 0 ? (
        <p className="meta" style={{ marginTop: 12 }}>{t('sif.nemaRezultata', { q: q.trim() })}</p>
      ) : prikazana.map((v) => (
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
