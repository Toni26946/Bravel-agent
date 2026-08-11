// Prilagođeni service worker: precache (offline) + push obavijesti.
import { precacheAndRoute } from 'workbox-precaching'

precacheAndRoute(self.__WB_MANIFEST || [])

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
