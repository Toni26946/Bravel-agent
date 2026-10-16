import Layout from '../Layout'

// Pregled „Plan radione" — vidljivo SAMO vlasniku (ai_poslovodja). Zasad je ovo
// samostalni prototip (mock podaci) ugrađen u app; sljedeći korak je spajanje na
// stvarne naloge/operacije i push potvrde.
export default function Plan() {
  return (
    <Layout naslov="Plan radione (pregled)">
      <p className="meta" style={{ marginTop: 0 }}>
        Pregled toka plana radione — vidljivo samo tebi. Zasad demo (nije spojeno na stvarne naloge).
      </p>
      <iframe
        src="/plan-demo.html"
        title="Plan radione"
        style={{
          width: '100%', height: 'calc(100dvh - 170px)', minHeight: 420,
          border: '1px solid var(--rub)', borderRadius: 12, background: '#fff', display: 'block',
        }}
      />
    </Layout>
  )
}
