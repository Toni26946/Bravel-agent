import { lazy, Suspense, useMemo, useState } from 'react'
import { useT } from '../i18n'
import { Spinner } from '../ui'
import { statusiZona } from '../shemaMapiranje'
import ShemaCrtez2D from './ShemaCrtez2D'
import ShemaDetalji from './ShemaDetalji'

const ShemaGL = lazy(() => import('./ShemaGL'))

// Shema vozila u nalogu: 2D nacrt (zadano) ili 3D; zajednički popis dijelova.
export default function Shema({ nalog }) {
  const { t } = useT()
  const [nacin, setNacin] = useState('2d')
  const [selektiran, setSelektiran] = useState(null)
  const statusi = useMemo(() => statusiZona(nalog?.operacije || []), [nalog])

  return (
    <div className="shema-wrap">
      <div className="chips" style={{ marginBottom: 10 }}>
        <span className={`chip ${nacin === '2d' ? 'akt' : ''}`} onClick={() => setNacin('2d')}>📐 {t('shema.nacrt')}</span>
        <span className={`chip ${nacin === '3d' ? 'akt' : ''}`} onClick={() => setNacin('3d')}>🧊 {t('shema.3d')}</span>
      </div>

      {nacin === '2d' ? (
        <ShemaCrtez2D nalog={nalog} statusi={statusi} selektiran={selektiran} onSelect={setSelektiran} />
      ) : (
        <Suspense fallback={<div className="shema-canvas shema-load"><Spinner /></div>}>
          <ShemaGL nalog={nalog} statusi={statusi} selektiran={selektiran} onSelect={setSelektiran} />
        </Suspense>
      )}

      <p className="meta shema-uputa">{nacin === '2d' ? t('shema.uputa2d') : t('shema.uputa3d')}</p>

      <ShemaDetalji nalog={nalog} statusi={statusi} selektiran={selektiran} onSelect={setSelektiran} />
    </div>
  )
}
