import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../Layout'

// „Plan radione" — vidljivo SAMO vlasniku (ai_poslovodja). Spojeno na stvarne
// naloge/operacije/mjerače. Iframe popunjava cijeli prostor sadržaja (bez rubova).
export default function Plan() {
  const nav = useNavigate()

  // Klik na garažni broj u iframeu → poruka iz plan-demo.html → otvori cijeli nalog.
  useEffect(() => {
    const naPoruku = (e) => {
      if (e.origin !== window.location.origin) return
      const d = e.data
      if (d && d.tip === 'plan-otvori-nalog' && d.id != null) nav(`/nalozi/${d.id}`)
    }
    window.addEventListener('message', naPoruku)
    return () => window.removeEventListener('message', naPoruku)
  }, [nav])

  return (
    <Layout naslov="Plan radione">
      {/* Poništi padding .sadrzaj-a da iframe ide od ruba do ruba i pune visine. */}
      <div style={{ margin: '-16px', marginBottom: 'calc(-88px - env(safe-area-inset-bottom, 0px))' }}>
        <iframe
          src="/plan-demo.html"
          title="Plan radione"
          style={{
            width: '100%', height: 'calc(100dvh - 54px)', border: 0,
            display: 'block', background: '#fff',
          }}
        />
      </div>
    </Layout>
  )
}
