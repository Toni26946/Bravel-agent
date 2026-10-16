import Layout from '../Layout'

// „Plan radione" — vidljivo SAMO vlasniku (ai_poslovodja). Spojeno na stvarne
// naloge/operacije/mjerače. Iframe popunjava cijeli prostor sadržaja (bez rubova).
export default function Plan() {
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
