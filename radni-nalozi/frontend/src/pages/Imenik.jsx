import { useEffect, useMemo, useState } from 'react'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, Prazno } from '../ui'
import { lijepBroj } from '../imenik'

// ☎ IMENIK — službeni brojevi radnika, SAMO ZA ČITANJE. Uređuju se u Flota OS-u (stranica IMENIK);
// ovdje se povlače uživo (predmemorija 5 min), pa na oba portala uvijek piše isto.
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

  const ucitaj = (osvjezi = false) => {
    setOsvjezava(osvjezi)
    return api.imenik(osvjezi).then((x) => { setD(x); setGreska('') })
      .catch((e) => setGreska(e.message)).finally(() => setOsvjezava(false))
  }
  useEffect(() => { ucitaj() }, [])

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

  const akcija = (
    <button className="btn mali sekund" disabled={osvjezava} onClick={() => ucitaj(true)} title="Povuci svježe iz Flota OS-a">
      {osvjezava ? '…' : '↻'}
    </button>
  )

  return (
    <Layout naslov="Imenik" akcija={akcija}>
      <p className="meta" style={{ marginTop: 0 }}>
        Službeni brojevi radnika — samo za čitanje. Brojevi se mijenjaju u <strong>Flota OS-u</strong> (stranica IMENIK),
        ovdje se vide za najviše 5 min.
      </p>

      {greska && <div className="greska">{greska}</div>}
      {d?.greska && <div className="greska">⚠ {d.greska}{d.zastarjelo && d.broj ? ` Prikazano stanje od ${vrijeme(d.dohvaceno)}.` : ''}</div>}

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
              {filt.map((z) => (
                <tr key={z.id}>
                  <td>
                    {z.ime || <span className="meta">(bez imena)</span>}
                    {z.opis && <div className="meta" style={{ fontSize: 12 }}>{z.opis}</div>}
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}><a href={'tel:' + z.broj}>{lijepBroj(z.broj)}</a></td>
                  <td>{z.kratki || '—'}</td>
                  <td className="meta" style={{ fontSize: 12 }}>{z.odjel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d?.dohvaceno && <p className="meta" style={{ fontSize: 11.5 }}>Povučeno iz Flota OS-a: {vrijeme(d.dohvaceno)}</p>}
    </Layout>
  )
}
