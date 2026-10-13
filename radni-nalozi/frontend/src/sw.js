// Prilagođeni service worker: precache aseta (offline) + svjež HTML + push obavijesti.
import { clientsClaim } from 'workbox-core'
import { precacheAndRoute } from 'workbox-precaching'
import { registerRoute, NavigationRoute } from 'workbox-routing'
import { NetworkFirst } from 'workbox-strategies'

// Nova verzija odmah preuzima kontrolu (bez čekanja da se zatvore sve kartice) —
// inače PWA zna dugo posluživati staru verziju iz keša.
self.skipWaiting()
clientsClaim()

// Precache hashirane asete (JS/CSS/slike/fontovi) — oni su immutable pa su sigurni za keš.
// HTML NAMJERNO izostavljamo iz precachea: posluživao se cache-first, pa je nakon deploya
// stari index.html pokazivao na obrisani JS hash → prazan ekran. HTML sada ide network-first
// (vidi dolje), pa stranica uvijek dohvati SVJEŽI index s aktualnim hash-evima.
const asetiManifest = (self.__WB_MANIFEST || []).filter((unos) => {
  const url = typeof unos === 'string' ? unos : unos.url
  return !/\.html$/i.test(url)
})
precacheAndRoute(asetiManifest)

// Navigacije (otvaranje/osvježavanje stranice) → NETWORK-FIRST:
// uvijek se dohvati svjež index.html s mreže (aktualni hash-evi JS/CSS), pa nema praznog
// ekrana nakon deploya. Offline (ili spora mreža > 3 s) → padne na zadnji keširani index.
registerRoute(
  new NavigationRoute(
    new NetworkFirst({ cacheName: 'html-navigacije', networkTimeoutSeconds: 3 })
  )
)

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    data = { naslov: 'Bravel Nalozi', tijelo: event.data ? event.data.text() : '' }
  }
  const naslov = data.naslov || 'Bravel Radni Nalozi'
  const opcije = {
    body: data.tijelo || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    data: { url: data.url || '/' },
    vibrate: [100, 50, 100],
  }
  event.waitUntil(self.registration.showNotification(naslov, opcije))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((lista) => {
      for (const klijent of lista) {
        if ('focus' in klijent) {
          klijent.navigate(url)
          return klijent.focus()
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url)
    })
  )
})
