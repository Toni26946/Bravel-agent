import { useEffect, useMemo, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, Prazno } from '../ui'
import { lijepBroj } from '../imenik'

// ☎ IMENIK — službeni brojevi radnika. Izvor istine je Flota OS; ovdje se povlače uživo
// (predmemorija 5 min), pa na oba portala uvijek piše isto. Ostali odjeli su samo za čitanje;
// brojeve odjela RADIONA smije se dodati/ispraviti i odavde (upis ide izravno u Flotu, koja
// sama pazi da se ne dira nijedan drugi odjel).
const RADIONA = 'RADIONA'
const PRAZNO = { id: null, ime: '', opis: '', broj: '', kratki: '', tarifa: '', napomena: '' }
const bezKvacica = (s) => String(s || '').toLowerCase().replace(/đ/g, 'd').normalize('NFD').replace(/[̀-ͯ]/g, '')

function vrijeme(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}. ${p(d.getHours())}:${p(d.getMinutes())}`
}

export default function Imenik() {
  const [d, setD] = useState(null)
  const [greska, setGreska] = useState('')
  const [q, setQ] = useState('')
  const [odjel, setOdjel] = useState('')
  const [osvjezava, setOsvjezava] = useState(false)
  const [uredi, setUredi] = useState(null)          // zapis u obrascu (samo RADIONA)
  const [sprema, setSprema] = useState(false)
  const [poruka, setPoruka] = useState('')

  const ucitaj = (osvjezi = false) => {
    setOsvjezava(osvjezi)
    return api.imenik(osvjezi).then((x) => { setD(x); setGreska('') })
      .catch((e) => setGreska(e.message)).finally(() => setOsvjezava(false))
  }
  useEffect(() => { ucitaj() }, [])

  const smijeUpis = !!d?.upis_radiona
  const zapisi = d?.zapisi || []
  const odjeli = useMemo(() => {
    const s = [...(d?.odjeli || [])]
    zapisi.forEach((z) => { if (!s.includes(z.odjel)) s.push(z.odjel) })
    return s.filter((o) => zapisi.some((z) => z.odjel === o))
  }, [d]) // eslint-disable-line react-hooks/exhaustive-deps

  const filt = useMemo(() => {
    const upit = bezKvacica(q).trim()
    const znam = upit.replace(/\D/g, '')
    return zapisi.filter((z) => (!odjel || z.odjel === odjel)
      && (!upit || bezKvacica(`${z.ime || ''} ${z.opis || ''}`).includes(upit)
        || (znam.length >= 3 && (String(z.broj).replace(/\D/g, '').includes(znam) || String(z.kratki || '').includes(znam)))))
  }, [zapisi, q, odjel])

  const otvori = (z) => {
    setPoruka('')
    setUredi(z ? { ...PRAZNO, ...Object.fromEntries(Object.keys(PRAZNO).map((k) => [k, z[k] ?? ''])) } : { ...PRAZNO })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const spremi = async () => {
    if (!uredi.broj.trim()) { setPoruka('⚠ Upiši broj.'); return }
    setSprema(true); setPoruka('')
    try {
      setD(await api.imenikRadionaSpremi(uredi))         // backend vraća svježi imenik
      setUredi(null); setPoruka('✓ Spremljeno u Flota OS.')
    } catch (e) { setPoruka(`⚠ ${e.message}`) }
    setSprema(false)
  }

  const deaktiviraj = async () => {
    if (!window.confirm(`Maknuti ${uredi.ime || 'ovaj broj'} iz imenika (deaktivacija u Flota OS-u)?`)) return
    setSprema(true); setPoruka('')
    try {
      setD(await api.imenikRadionaAktivan(uredi.id, false))
      setUredi(null); setPoruka('✓ Deaktivirano.')
    } catch (e) { setPoruka(`⚠ ${e.message}`) }
    setSprema(false)
  }

  const akcija = (
    <span style={{ display: 'flex', gap: 6 }}>
      {smijeUpis && <button className="btn mali" onClick={() => otvori(null)}>➕ Dodaj broj</button>}
      <button className="btn mali sekund" disabled={osvjezava} onClick={() => ucitaj(true)} title="Povuci svježe iz Flota OS-a">
        {osvjezava ? '…' : '↻'}
      </button>
    </span>
  )

  const polje = (k, oznaka, extra = {}) => (
    <label style={{ display: 'block' }}>
      <span className="meta" style={{ fontSize: 12 }}>{oznaka}</span>
      <input className="pretraga-input" style={{ marginBottom: 6 }} value={uredi[k] || ''}
        onChange={(e) => setUredi({ ...uredi, [k]: e.target.value })} {...extra} />
    </label>
  )

  return (
    <Layout naslov="Imenik" akcija={akcija}>
      <p className="meta" style={{ marginTop: 0 }}>
        Službeni brojevi radnika iz <strong>Flota OS-a</strong>.
        {smijeUpis ? ' Brojeve odjela RADIONA možeš dodati ili ispraviti i ovdje (klik na red); ostali odjeli su samo za čitanje.'
          : ' Samo za čitanje — brojevi se mijenjaju u Flota OS-u.'}
      </p>

      {greska && <div className="greska">{greska}</div>}
      {d?.greska && <div className="greska">⚠ {d.greska}{d.zastarjelo && d.broj ? ` Prikazano stanje od ${vrijeme(d.dohvaceno)}.` : ''}</div>}
      {poruka && <p className={poruka.startsWith('⚠') ? 'greska' : 'meta'}>{poruka}</p>}

      {uredi && (
        <div className="karta" style={{ padding: '12px 14px', marginBottom: 10 }}>
          <div className="sekcija-naslov" style={{ marginTop: 0 }}>{uredi.id ? 'Ispravak broja' : 'Novi broj'} · odjel RADIONA</div>
          {polje('ime', 'Ime (prezime ime)')}
          {polje('broj', 'Broj', { inputMode: 'tel', placeholder: '091 123 4567' })}
          {polje('kratki', 'Kratki broj', { inputMode: 'numeric' })}
          {polje('opis', 'Opis / uloga')}
          {polje('tarifa', 'Tarifa')}
          {polje('napomena', 'Napomena')}
          <div className="btn-red">
            <button className="btn mali" disabled={sprema} onClick={spremi}>{sprema ? '…' : 'Spremi'}</button>
            <button className="btn sekund mali" disabled={sprema} onClick={() => setUredi(null)}>Odustani</button>
            {uredi.id && <button className="btn sekund mali" disabled={sprema} onClick={deaktiviraj}>🚫 Makni iz imenika</button>}
          </div>
        </div>
      )}

      <input className="pretraga-input" placeholder="Traži ime, broj ili kratki broj…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="vz-filteri">
        <button className={'vz-fil' + (odjel === '' ? ' akt' : '')} onClick={() => setOdjel('')}>Svi ({zapisi.length})</button>
        {odjeli.map((o) => (
          <button key={o} className={'vz-fil' + (odjel === o ? ' akt' : '')} onClick={() => setOdjel(odjel === o ? '' : o)}>
            {o} ({zapisi.filter((z) => z.odjel === o).length})
          </button>
        ))}
      </div>

      {d === null && !greska ? <Spinner /> : filt.length === 0 ? (
        <Prazno emo="☎️" tekst={q || odjel ? 'Nema rezultata.' : 'Imenik je prazan.'} />
      ) : (
        <div className="karta">
          <table className="di-tab">
            <thead>
              <tr><th>Ime</th><th>Broj</th><th>Kratki</th><th>Odjel</th></tr>
            </thead>
            <tbody>
              {filt.map((z) => {
                const uredivo = smijeUpis && z.odjel === RADIONA
                return (
                  <tr key={z.id} onClick={uredivo ? () => otvori(z) : undefined}
                    style={uredivo ? { cursor: 'pointer' } : undefined} title={uredivo ? 'Klik za ispravak' : undefined}>
                    <td>
                      {z.ime || <span className="meta">(bez imena)</span>}{uredivo && <span className="meta"> ✏️</span>}
                      {z.opis && <div className="meta" style={{ fontSize: 12 }}>{z.opis}</div>}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <a href={'tel:' + z.broj} onClick={(e) => e.stopPropagation()}>{lijepBroj(z.broj)}</a>
                    </td>
                    <td>{z.kratki || '—'}</td>
                    <td className="meta" style={{ fontSize: 12 }}>{z.odjel}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {d?.dohvaceno && <p className="meta" style={{ fontSize: 11.5 }}>Povučeno iz Flota OS-a: {vrijeme(d.dohvaceno)}</p>}
    </Layout>
  )
}
