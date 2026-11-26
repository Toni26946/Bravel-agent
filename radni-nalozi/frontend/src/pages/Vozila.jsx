import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { useAuth } from '../auth'
import { Spinner, datum } from '../ui'
import { useT } from '../i18n'
import { imeZadnjegVozaca, useZadnjiVozaci } from '../ZadnjiVozac'
import PovijestVozaca from '../PovijestVozaca'
import PovijestRadnika from '../PovijestRadnika'

// Operativni statusi (mjerodavni — „sveto pismo"). Redoslijed = redoslijed u izborniku.
const STATUSI = ['aktivno', 'u_radionici', 'pokvareno', 'spremno', 'nezaduzeno', 'u_najmu', 'prodano']
const EMO = { aktivno: '✅', u_radionici: '🔧', pokvareno: '🛑', prodano: '💰', nezaduzeno: '🛻', spremno: '🟢', u_najmu: '🤝' }

// Naziv kategorije: prevedi ako postoji ključ, inače prikaži sirovu vrijednost.
function katLabel(t, k) {
  const p = t('kat.' + k)
  return p === 'kat.' + k ? k : p
}

// Matični popis svih vozila iz flote; status se postavlja ručno i mjerodavan je.
export default function Vozila() {
  const { t } = useT()
  const { korisnik } = useAuth()
  const nav = useNavigate()
  const smijeUrediti = korisnik?.uloga === 'voditelj' || korisnik?.uloga === 'poslovodja'
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')
  const [pretraga, setPretraga] = useState('')
  const [kat, setKat] = useState('')
  const [stat, setStat] = useState('')
  const [parkinzi, setParkinzi] = useState([])
  const [uredjujem, setUredjujem] = useState(null)   // gb vozila koje se uređuje
  const [uvozOtvoren, setUvozOtvoren] = useState(false)
  const [novoOtvoreno, setNovoOtvoreno] = useState(false)
  const [poruka, setPoruka] = useState('')

  const vozaci = useZadnjiVozaci()   // ime zadnjeg vozača uz GB (#436)
  const [povijest, setPovijest] = useState(null)   // null = zatvoreno; '' / GB = otvoreno (#437)
  const [povijestRadnika, setPovijestRadnika] = useState(false)   // 👷 tko je što radio (#438)
  const ucitaj = () => api.vozilaRegistar().then(setD).catch((e) => setGreska(e.message))
  useEffect(() => { ucitaj(); api.parkinzi().then(setParkinzi).catch(() => {}) }, [])

  const promijeniLokalno = (gb, izmjena) =>
    setD((prev) => (prev ? prev.map((v) => (v.gb === gb ? { ...v, ...izmjena } : v)) : prev))

  const kategorije = useMemo(
    () => [...new Set((d || []).map((v) => v.kategorija).filter(Boolean))].sort(),
    [d],
  )
  const brojac = useMemo(() => {
    const b = {}
    for (const v of d || []) b[v.status] = (b[v.status] || 0) + 1
    // „U radionici" je IZVEDENO: ručni/Mobilisis status ILI (GPS u krugu radione I otvoren nalog).
    b.u_radionici = (d || []).filter((v) => v.u_radionici).length
    return b
  }, [d])

  const filtrirana = useMemo(() => {
    const p = pretraga.trim().toLowerCase()
    return (d || []).filter((v) => {
      if (kat && v.kategorija !== kat) return false
      if (stat) {
        if (stat === 'u_radionici') { if (!v.u_radionici) return false }
        else if (v.status !== stat) return false
      }
      if (!p) return true
      return [v.gb, v.registracija, v.tip, v.vozilo, v.vrsta, v.broj_sasije, imeZadnjegVozaca(vozaci, v.gb)]
        .some((x) => (x || '').toLowerCase().includes(p))
    })
  }, [d, pretraga, kat, stat, vozaci])

  if (greska) return <Layout naslov={t('tab.vozila')}><div className="greska">{greska}</div></Layout>
  if (!d) return <Layout naslov={t('tab.vozila')}><Spinner /></Layout>

  return (
    <Layout naslov={t('tab.vozila')}>
      <p className="meta" style={{ marginTop: 0 }}>{t('vozila.opis')}</p>

      {smijeUrediti && (
        <div className="btn-red" style={{ marginBottom: 8 }}>
          <button className="btn mali" onClick={() => { setNovoOtvoreno((o) => !o); setUvozOtvoren(false); setPoruka('') }}>
            ＋ Novo vozilo
          </button>
          <button className="btn sekund mali" onClick={() => { setUvozOtvoren((o) => !o); setNovoOtvoreno(false) }}>
            ⬆️ Uvoz više vozila
          </button>
        </div>
      )}
      {poruka && <div className="uspjeh" style={{ marginBottom: 8 }}>{poruka}</div>}
      {novoOtvoreno && smijeUrediti && (
        <NovoVozilo
          onGotovo={(r) => {
            setNovoOtvoreno(false)
            setPoruka(r.u_floti
              ? `✅ GB ${r.gb} upisan — u Radnim nalozima i u Floti.`
              : `✅ GB ${r.gb} upisan u Radne naloge. Flota se ne javlja — upisat će se sama čim proradi.`)
            setPretraga(r.gb)
            ucitaj()
          }}
          onOdustani={() => setNovoOtvoreno(false)} />
      )}
      {uvozOtvoren && smijeUrediti && (
        <UvozPanel onGotovo={() => { setUvozOtvoren(false); ucitaj() }} onOdustani={() => setUvozOtvoren(false)} />
      )}

      <div className="btn-red" style={{ marginBottom: 8 }}>
        <button type="button" className="btn sekund mali" onClick={() => setPovijest('')}>
          📜 Povijest vozača (tko je vozio koje vozilo)
        </button>
        <button type="button" className="btn sekund mali" onClick={() => setPovijestRadnika(true)}>
          👷 Povijest radnika (tko je što radio)
        </button>
      </div>
      {povijest !== null && <PovijestVozaca pocetno={povijest} onZatvori={() => setPovijest(null)} />}
      {povijestRadnika && <PovijestRadnika onZatvori={() => setPovijestRadnika(false)} />}

      <input
        className="pretraga-input"
        placeholder={t('vozila.pretraga')}
        value={pretraga}
        onChange={(e) => setPretraga(e.target.value)}
      />

      <div className="vz-filteri">
        <button className={'vz-fil' + (kat === '' ? ' akt' : '')} onClick={() => setKat('')}>{t('vozila.sve')}</button>
        {kategorije.map((k) => (
          <button key={k} className={'vz-fil' + (kat === k ? ' akt' : '')} onClick={() => setKat(kat === k ? '' : k)}>
            {katLabel(t, k)}
          </button>
        ))}
      </div>
      <div className="vz-filteri">
        <button className={'vz-fil' + (stat === '' ? ' akt' : '')} onClick={() => setStat('')}>{t('vozila.sviStatusi')}</button>
        {STATUSI.map((s) => (
          <button
            key={s}
            className={'vz-fil sv-' + s + (stat === s ? ' akt' : '')}
            onClick={() => setStat(stat === s ? '' : s)}
          >
            {EMO[s]} {t('sv.' + s)} {brojac[s] ? `(${brojac[s]})` : ''}
          </button>
        ))}
      </div>
      {stat === 'u_radionici' && <p className="meta" style={{ marginTop: -4 }}>{t('vozila.uRadioniciObjasnjenje')}</p>}

      <div className="sekcija-naslov">{filtrirana.length} / {d.length} {t('vozila.vozila')}</div>
      {filtrirana.length === 0 && <p className="meta">{t('vozila.nema')}</p>}
      {filtrirana.map((v) => (
        <div key={v.gb}>
          <div className="karta vz-red">
            <div className="vz-info" onClick={() => v.nalog_id && nav(`/nalozi/${v.nalog_id}`)}>
              <div className="vz-gb">{v.gb}{v.vozilo ? ` · ${v.vozilo}` : ''}</div>
              {imeZadnjegVozaca(vozaci, v.gb) && (
                <div className="meta vz-vozac">
                  <button type="button" className="vz-vozac-btn" title="Povijest vozača ovog vozila"
                    onClick={(e) => { e.stopPropagation(); setPovijest(v.gb) }}>🧑 {imeZadnjegVozaca(vozaci, v.gb)} · 📜</button>
                </div>
              )}
              <div className="meta">
                {[v.registracija, v.vrsta || v.tip].filter(Boolean).join(' · ') || '—'}
                {v.nalog_id ? ` · ${v.broj}` : ''}
                {v.u_radionici && v.status !== 'u_radionici' && <span className="vz-uradu"> · 🔧 {t('sv.u_radionici')}</span>}
              </div>
              {(v.broj_sasije || v.norma || v.prva_registracija) && (
                <div className="meta">
                  {[v.norma, v.prva_registracija && `1. reg. ${v.prva_registracija}`, v.broj_sasije && `šasija ${v.broj_sasije}`]
                    .filter(Boolean).join(' · ')}
                </div>
              )}
              {v.km_trenutni != null && (
                <div className="meta">🧭 {v.km_trenutni.toLocaleString('hr-HR')} km{v.km_azuriran ? ` · ${datum(v.km_azuriran)}` : ''}</div>
              )}
              {v.opis && <div className="meta">📝 {v.opis}</div>}
              {v.status === 'spremno' && v.lokacija && (
                <div className="meta vz-lok">📍 {v.lokacija}</div>
              )}
              <div className="meta vz-mob">
                {t('vozila.mobilisis')}: {v.mobilisis_status || '—'}
                {v.rucno && <span className="vz-rucno"> · {t('vozila.rucno')}</span>}
              </div>
            </div>
            <div className="vz-akcije">
              <StatusChip v={v} parkinzi={parkinzi} onPromjena={(izmjena) => promijeniLokalno(v.gb, izmjena)} />
              {smijeUrediti && (
                <button type="button" className="vz-uredi" title="Uredi podatke"
                  onClick={() => setUredjujem(uredjujem === v.gb ? null : v.gb)}>✏️</button>
              )}
            </div>
          </div>
          {uredjujem === v.gb && smijeUrediti && (
            <UrediVozilo v={v}
              onSpremi={(izmjena) => { promijeniLokalno(v.gb, izmjena); setUredjujem(null) }}
              onOdustani={() => setUredjujem(null)} />
          )}
        </div>
      ))}
    </Layout>
  )
}

function StatusChip({ v, parkinzi = [], onPromjena }) {
  const { t } = useT()
  const [otvoren, setOtvoren] = useState(false)
  const [radi, setRadi] = useState(false)
  const [trazimLok, setTrazimLok] = useState(false)   // upisujemo lokaciju za „Spremno"
  const [lok, setLok] = useState(v.lokacija || '')
  const [greskaLok, setGreskaLok] = useState('')

  const posalji = async (body, izmjena) => {
    setRadi(true); setGreskaLok('')
    try {
      const r = await api.postaviStatusVozila(v.gb, body)
      onPromjena({ status: r.status, rucno: r.rucno, lokacija: r.lokacija, ...izmjena })
      setOtvoren(false); setTrazimLok(false)
    } catch (e) { setGreskaLok(e.message || 'Greška') } finally { setRadi(false) }
  }

  const odabir = (s) => {
    if (s === 'spremno') { setTrazimLok(true); setLok(v.lokacija || '') }  // traži lokaciju prvo
    else posalji({ status: s })
  }
  const spremiSpremno = () => {
    if (!lok.trim()) { setGreskaLok(t('spremne.lokObavezna')); return }
    posalji({ status: 'spremno', lokacija: lok.trim() })
  }
  const vratiMobilisis = async () => {
    setRadi(true)
    try {
      const r = await api.vratiNaMobilisis(v.gb)
      onPromjena({ status: r.status, rucno: r.rucno })
      setOtvoren(false)
    } catch (_) { /* tiho */ } finally { setRadi(false) }
  }

  return (
    <span className="chip-wrap">
      <button type="button" className={'slobodni-chip sv-' + v.status} onClick={() => { setOtvoren((o) => !o); setTrazimLok(false) }} disabled={radi}>
        {EMO[v.status] || ''} {t('sv.' + v.status)}
      </button>
      {otvoren && (
        <div className="chip-menu" onClick={(e) => e.stopPropagation()}>
          {!trazimLok ? (
            <>
              {STATUSI.map((s) => (
                <button key={s} className={'cm-opt' + (v.status === s ? ' akt' : '')} disabled={radi} onClick={() => odabir(s)}>
                  {EMO[s]} {t('sv.' + s)}
                </button>
              ))}
              {v.rucno && (
                <button className="cm-opt" disabled={radi} onClick={vratiMobilisis} title={t('vozila.vratiMobilisisOpis')}>
                  ↺ {t('vozila.vratiMobilisis')}
                </button>
              )}
            </>
          ) : (
            <div className="cm-form">
              <div className="cm-naslov">🟢 {t('spremne.gdjeParkirana')}</div>
              {parkinzi.length === 0 ? (
                <div className="meta" style={{ marginBottom: 6 }}>{t('spremne.trebaParking')}</div>
              ) : (
                <select className="pretraga-input" style={{ marginBottom: 6 }} value={lok}
                  onChange={(e) => setLok(e.target.value)} autoFocus>
                  <option value="">{t('spremne.odaberiParking')}</option>
                  {parkinzi.map((p) => <option key={p.id} value={p.naziv}>{p.naziv}</option>)}
                </select>
              )}
              {greskaLok && <div className="greska" style={{ margin: '2px 0' }}>{greskaLok}</div>}
              <div className="btn-red" style={{ marginTop: 4 }}>
                <button className="btn mali" disabled={radi || parkinzi.length === 0} onClick={spremiSpremno}>{radi ? '…' : t('common.spremi')}</button>
                <button className="btn sekund mali" disabled={radi} onClick={() => setTrazimLok(false)}>{t('common.odustani')}</button>
              </div>
            </div>
          )}
        </div>
      )}
    </span>
  )
}

// Polja matičnih podataka vozila (ključ u modelu → oznaka u formi).
const VOZILO_POLJA = [
  ['vozilo', 'Vozilo (marka/model)'],
  ['registracija', 'Reg. oznaka'],
  ['vrsta', 'Vrsta (tegljač/dizalica/šlepa/prikolica)'],
  ['tip', 'Tip (kamion / priključno)'],
  ['prva_registracija', 'Prva registracija'],
  ['norma', 'Norma (EURO 5/6)'],
  ['broj_sasije', 'Broj šasije'],
  ['firma', 'Firma'],
  ['iznos_registracije', 'Iznos registracije'],
]

function UrediVozilo({ v, onSpremi, onOdustani }) {
  const poc = {}
  for (const [k] of VOZILO_POLJA) poc[k] = v[k] || ''
  poc.opis = v.opis || ''
  const [f, setF] = useState(poc)
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const postavi = (k, val) => setF((p) => ({ ...p, [k]: val }))

  const spremi = async () => {
    setRadi(true); setGreska('')
    try {
      const r = await api.urediPodatkeVozila(v.gb, f)
      onSpremi({
        registracija: r.registracija, tip: r.tip, kategorija: r.kategorija,
        vrsta: r.vrsta, vozilo: r.vozilo, prva_registracija: r.prva_registracija,
        firma: r.firma, iznos_registracije: r.iznos_registracije, norma: r.norma,
        broj_sasije: r.broj_sasije, opis: r.opis,
      })
    } catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }

  return (
    <div className="karta vz-uredi-form">
      <div className="cm-naslov" style={{ marginBottom: 6 }}>✏️ Uredi vozilo {v.gb}</div>
      <div className="vz-polja">
        {VOZILO_POLJA.map(([k, oznaka]) => (
          <label key={k} className="vz-polje">
            <span>{oznaka}</span>
            <input className="pretraga-input" value={f[k]} onChange={(e) => postavi(k, e.target.value)} />
          </label>
        ))}
      </div>
      <label className="vz-polje" style={{ marginTop: 6 }}>
        <span>Napomena / opis</span>
        <textarea className="pretraga-input" rows={2} value={f.opis} onChange={(e) => postavi('opis', e.target.value)} />
      </label>
      {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
      <div className="btn-red" style={{ marginTop: 6 }}>
        <button className="btn mali" disabled={radi} onClick={spremi}>{radi ? '…' : 'Spremi'}</button>
        <button className="btn sekund mali" disabled={radi} onClick={onOdustani}>Odustani</button>
      </div>
    </div>
  )
}

// Novo vozilo — jedan obrazac umjesto uvoza datoteke (Toni 26.11.2026.). Upiše se u Radne
// naloge i ODMAH u Flotin šifrarnik Garažni brojevi (glavni popis vozila).
const VRSTE_NOVO = ['DIZALICA', 'TEGLJAČ', 'ŠLEPA', 'PRIKOLICA', 'KOMBI', 'AUTO', 'OSTALO']
const FIRME_NOVO = ['BRAVEL', 'BRAVEL LOGS']

function NovoVozilo({ onGotovo, onOdustani }) {
  const [f, setF] = useState({ gb: '', vrsta: '', vozilo: '', registracija: '', broj_sasije: '', prva_registracija: '', firma: 'BRAVEL' })
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const [postoji, setPostoji] = useState(null)
  const postavi = (k, val) => setF((p) => ({ ...p, [k]: val }))

  // GB = samo broj: razmak (npr. zalijepljeno „498 VOLVO FH64R") odmah upozori.
  const gb = f.gb.trim()
  const gbKrivo = gb && /\s/.test(gb)

  useEffect(() => {
    setPostoji(null)
    if (!gb || gbKrivo) return undefined
    const tm = setTimeout(() => {
      api.provjeriGb(gb).then((r) => setPostoji(r.postoji ? r : null)).catch(() => {})
    }, 300)
    return () => clearTimeout(tm)
  }, [gb, gbKrivo])

  const spremi = async () => {
    setRadi(true); setGreska('')
    try {
      const r = await api.novoVozilo({ ...f, gb, vrsta: f.vrsta === 'OSTALO' ? '' : f.vrsta })
      onGotovo(r)
    } catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }

  const moze = gb && !gbKrivo && !postoji && f.vrsta && !radi

  return (
    <div className="karta vz-uredi-form">
      <div className="cm-naslov" style={{ marginBottom: 6 }}>＋ Novo vozilo</div>
      <p className="meta" style={{ marginTop: 0 }}>Upisuje se i u Flotu (Garažni brojevi) — nigdje drugdje ne treba.</p>
      <div className="vz-polja">
        <label className="vz-polje">
          <span>Garažni broj (GB) *</span>
          <input className="pretraga-input" inputMode="numeric" autoFocus value={f.gb}
            onChange={(e) => postavi('gb', e.target.value)} placeholder="npr. 505" />
        </label>
        <label className="vz-polje">
          <span>Vozilo (marka i model)</span>
          <input className="pretraga-input" value={f.vozilo} onChange={(e) => postavi('vozilo', e.target.value)} placeholder="npr. VOLVO FH64R" />
        </label>
      </div>
      {gbKrivo && <div className="greska" style={{ margin: '4px 0' }}>GB je samo broj (npr. 498) — marku i model upiši u „Vozilo”.</div>}
      {postoji && <div className="greska" style={{ margin: '4px 0' }}>GB {postoji.gb} već postoji{postoji.opis ? ` — ${postoji.opis}` : ''}.</div>}
      <div className="vz-polje" style={{ marginTop: 6 }}>
        <span>Vrsta *</span>
        <div className="vz-filteri" style={{ marginTop: 4 }}>
          {VRSTE_NOVO.map((v) => (
            <button key={v} type="button" className={'vz-fil' + (f.vrsta === v ? ' akt' : '')} onClick={() => postavi('vrsta', v)}>{v}</button>
          ))}
        </div>
      </div>
      <div className="vz-polja">
        <label className="vz-polje">
          <span>Reg. oznaka</span>
          <input className="pretraga-input" value={f.registracija} onChange={(e) => postavi('registracija', e.target.value)} placeholder="ako je već ima" />
        </label>
        <label className="vz-polje">
          <span>Broj šasije</span>
          <input className="pretraga-input" value={f.broj_sasije} onChange={(e) => postavi('broj_sasije', e.target.value)} />
        </label>
        <label className="vz-polje">
          <span>Godina (prva registracija)</span>
          <input className="pretraga-input" inputMode="numeric" value={f.prva_registracija} onChange={(e) => postavi('prva_registracija', e.target.value)} placeholder="npr. 2019" />
        </label>
        <label className="vz-polje">
          <span>Firma</span>
          <select className="pretraga-input" value={f.firma} onChange={(e) => postavi('firma', e.target.value)}>
            {FIRME_NOVO.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </label>
      </div>
      {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
      <div className="btn-red" style={{ marginTop: 6 }}>
        <button className="btn mali" disabled={!moze} onClick={spremi}>{radi ? '…' : 'Spremi vozilo'}</button>
        <button className="btn sekund mali" disabled={radi} onClick={onOdustani}>Odustani</button>
      </div>
    </div>
  )
}

function UvozPanel({ onGotovo, onOdustani }) {
  const [tekst, setTekst] = useState('')
  const [radi, setRadi] = useState(false)
  const [greska, setGreska] = useState('')
  const [rezultat, setRezultat] = useState(null)

  const uvezi = async () => {
    setRadi(true); setGreska(''); setRezultat(null)
    try {
      const r = await api.uvozRegistar(tekst)
      setRezultat(r)
    } catch (e) { setGreska(e.message || 'Greška') } finally { setRadi(false) }
  }

  return (
    <div className="karta">
      <div className="cm-naslov" style={{ marginBottom: 4 }}>⬆️ Uvoz vozila iz tablice</div>
      <p className="meta" style={{ marginTop: 0 }}>
        Zalijepi stupce iz Excela (GARAŽNI BROJEVI): GB, VOZILO, REG OZNAKA, VRSTA,
        PRVA REGISTRACIJA, TIP, FIRMA, IZNOS REGISTRACIJE, NORMA, BROJ ŠASIJE.
        Postojeća vozila (po GB) se ažuriraju, prazno ne briše.
      </p>
      <textarea className="pretraga-input" rows={6} value={tekst}
        onChange={(e) => setTekst(e.target.value)} placeholder="Zalijepi ovdje…" />
      {greska && <div className="greska" style={{ margin: '4px 0' }}>{greska}</div>}
      {rezultat && (
        <div className="meta" style={{ margin: '4px 0' }}>
          ✅ Dodano: {rezultat.dodano} · Ažurirano: {rezultat.azurirano} · Ukupno: {rezultat.ukupno}
        </div>
      )}
      <div className="btn-red" style={{ marginTop: 6 }}>
        {rezultat
          ? <button className="btn mali" onClick={onGotovo}>Gotovo</button>
          : <button className="btn mali" disabled={radi || !tekst.trim()} onClick={uvezi}>{radi ? '…' : 'Uvezi'}</button>}
        <button className="btn sekund mali" disabled={radi} onClick={onOdustani}>Zatvori</button>
      </div>
    </div>
  )
}
