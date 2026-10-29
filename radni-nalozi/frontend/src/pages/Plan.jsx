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

  // Iframe sam skrola (ima svoju traku) — ugasi vanjski skrol .sadrzaj-a dok smo na
  // Planu, inače su DVIJE trake. Padding/maxWidth se tu ponište da iframe ide od
  // ruba do ruba i pune visine; po izlasku se vrati staro.
  useEffect(() => {
    const el = document.querySelector('.sadrzaj')
    if (!el) return
    const prev = { overflow: el.style.overflow, padding: el.style.padding, maxWidth: el.style.maxWidth }
    el.style.overflow = 'hidden'
    el.style.padding = '0'
    el.style.maxWidth = 'none'
    return () => { el.style.overflow = prev.overflow; el.style.padding = prev.padding; el.style.maxWidth = prev.maxWidth }
  }, [])

  return (
    <Layout naslov="Plan radione">
      <div style={{ height: '100%' }}>
        <iframe
          src="/plan-demo.html"
          title="Plan radione"
          style={{ width: '100%', height: '100%', border: 0, display: 'block', background: '#fff' }}
        />
      </div>
    </Layout>
  )
}
