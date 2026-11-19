import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './auth'
import { JezikProvider } from './i18n'
import './styles.css'

// Valjci su ZASEBNA aplikacija (svoja ikona na mobitelu): na /valjci vlastiti manifest i naslov.
if (window.location.pathname.startsWith('/valjci')) {
  document.title = 'Valjci'
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', '#e65100')
  document.querySelectorAll('link[rel="icon"], link[rel="apple-touch-icon"]').forEach((l) => {
    l.href = '/icons/valjci-192.png'
    l.removeAttribute('type')
  })
  const postavi = () => {
    const linkovi = document.querySelectorAll('link[rel="manifest"]')
    if (!linkovi.length) {
      const l = document.createElement('link'); l.rel = 'manifest'; l.href = '/valjci.webmanifest'
      document.head.appendChild(l)
      return
    }
    linkovi.forEach((l) => { if (!l.href.endsWith('/valjci.webmanifest')) l.href = '/valjci.webmanifest' })
  }
  postavi()
  new MutationObserver(postavi).observe(document.head, { childList: true })   // ako PWA doda svoj kasnije
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <JezikProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </JezikProvider>
    </BrowserRouter>
  </React.StrictMode>
)

// Češće provjeravaj novu verziju aplikacije (SW je autoUpdate + skipWaiting,
// pa se nova verzija sama primijeni čim je pronađena).
if ('serviceWorker' in navigator) {
  const provjeri = () =>
    navigator.serviceWorker.getRegistration().then((r) => r && r.update()).catch(() => {})
  setInterval(provjeri, 60000)
  window.addEventListener('focus', provjeri)
}
