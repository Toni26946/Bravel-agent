// Registracija push pretplate (poziva se nakon prijave, ako je push omogućen).
import { api } from './api'

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

export async function omoguciPush() {
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return
    const info = await api.pushKljuc()
    if (!info.omoguceno || !info.vapid_public_key) return

    const dozvola = await Notification.requestPermission()
    if (dozvola !== 'granted') return

    const reg = await navigator.serviceWorker.ready
    let sub = await reg.pushManager.getSubscription()
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(info.vapid_public_key),
      })
    }
    await api.pushPretplata(sub)
  } catch (e) {
    console.warn('Push nije omogućen:', e)
  }
}
