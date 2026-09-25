import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'
import { api } from '../api'
import { Spinner, Prazno, datum } from '../ui'
import { useT } from '../i18n'

// Popis zaduženja kamiona/prikolica (primopredajni obrasci).
export default function Zaduzenja() {
  const { t } = useT()
  const nav = useNavigate()
  const [redovi, setRedovi] = useState(null)
  const [q, setQ] = useState('')

  const ucitaj = () => api.zaduzenja().then(setRedovi).catch(() => setRedovi([]))
  useEffect(() => { ucitaj() }, [])

  const upit = q.trim().toLowerCase()
  const filt = (redovi || []).filter((z) => {
    if (!upit) return true
    return [z.kamion_registracija, z.prikolica_registracija, z.preuzeo]
      .some((v) => (v || '').toString().toLowerCase().includes(upit))
  })

  const akcija = (
    <button className="btn mali" onClick={() => nav('/zaduzenja/novo')}>+ {t('zad.novo')}</button>
  )

  return (
    <Layout naslov={t('tab.zaduzenja')} akcija={akcija}>
      <p className="meta" style={{ marginTop: 0 }}>{t('zad.opis')}</p>
      <input
        className="pretraga-input"
        style={{ marginBottom: 10 }}
        placeholder={t('zad.trazi')}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {redovi === null ? <Spinner /> : filt.length === 0 ? (
        <Prazno emo="🧾" tekst={upit ? t('zad.nemaRezultata') : t('zad.nema')} />
      ) : (
        <div className="karta">
          <table className="di-tab">
            <thead>
              <tr>
                <th>{t('zad.datum')}</th>
                <th>{t('zad.kamion')}</th>
                <th>{t('zad.prikolica')}</th>
                <th>{t('zad.preuzeo')}</th>
                <th>{t('zad.status')}</th>
              </tr>
            </thead>
            <tbody>
              {filt.map((z) => (
                <tr key={z.id} className="klik-red" onClick={() => nav(`/zaduzenja/${z.id}`)}>
                  <td>{datum(z.datum)}</td>
                  <td><strong>🚚 {z.kamion_registracija || '—'}</strong></td>
                  <td>🛻 {z.prikolica_registracija || '—'}</td>
                  <td>{z.preuzeo || '—'}</td>
                  <td>
                    <span className={'zad-znak ' + (z.status === 'zavrseno' ? 'zad-ok' : 'zad-tijek')}>
                      {z.status === 'zavrseno' ? t('zad.zavrseno') : t('zad.uTijeku')}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Layout>
  )
}
