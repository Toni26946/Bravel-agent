// Tanki HTTP klijent oko fetch-a — dodaje JWT i baznu adresu.
const BASE = import.meta.env.VITE_API_URL || ''

export function getToken() {
  return localStorage.getItem('token')
}
export function setToken(t) {
  if (t) localStorage.setItem('token', t)
  else localStorage.removeItem('token')
}

export function medijUrl(putanja) {
  if (!putanja) return ''
  if (putanja.startsWith('http')) return putanja
  return BASE + putanja
}

async function zahtjev(putanja, { method = 'GET', body, form } = {}) {
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  let telo
  if (form) {
    telo = form // FormData — browser sam postavlja Content-Type
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    telo = JSON.stringify(body)
  }

  const res = await fetch(BASE + '/api' + putanja, { method, headers, body: telo })
  if (res.status === 401) {
    setToken(null)
    if (!location.pathname.startsWith('/prijava')) location.href = '/prijava'
    throw new Error('Sesija je istekla')
  }
  if (!res.ok) {
    let poruka = `Greška ${res.status}`
    try {
      const j = await res.json()
      if (j.detail) poruka = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch (e) { /* ignore */ }
    throw new Error(poruka)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  login: async (korisnicko_ime, lozinka) => {
    const fd = new URLSearchParams()
    fd.append('username', korisnicko_ime)
    fd.append('password', lozinka)
    const res = await fetch(BASE + '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: fd,
    })
    if (!res.ok) {
      let poruka = 'Prijava neuspješna'
      try { const j = await res.json(); if (j.detail) poruka = j.detail } catch (e) {}
      throw new Error(poruka)
    }
    return res.json()
  },
  me: () => zahtjev('/auth/me'),
  promijeniLozinku: (stara_lozinka, nova_lozinka) =>
    zahtjev('/auth/promijeni-lozinku', { method: 'POST', body: { stara_lozinka, nova_lozinka } }),

  // Vozila
  vozila: () => zahtjev('/vozila'),
  vozilo: (id) => zahtjev(`/vozila/${id}`),
  kreirajVozilo: (b) => zahtjev('/vozila', { method: 'POST', body: b }),
  uvozVozila: (tekst) => zahtjev('/vozila/uvoz', { method: 'POST', body: { tekst } }),

  // Povijest zamjene dijelova (po kamionu)
  povijestDijelova: (voziloId) => zahtjev(`/vozila/${voziloId}/dijelovi`),
  dodajZamjenuDijela: (voziloId, b) => zahtjev(`/vozila/${voziloId}/dijelovi`, { method: 'POST', body: b }),
  obrisiZamjenuDijela: (voziloId, id) => zahtjev(`/vozila/${voziloId}/dijelovi/${id}`, { method: 'DELETE' }),

  // Korisnici
  korisnici: (uloga) => zahtjev('/korisnici' + (uloga ? `?uloga=${uloga}` : '')),
  kreirajKorisnika: (b) => zahtjev('/korisnici', { method: 'POST', body: b }),
  azurirajKorisnika: (id, b) => zahtjev(`/korisnici/${id}`, { method: 'PATCH', body: b }),

  // Prijave
  prijave: () => zahtjev('/prijave'),
  prijava: (id) => zahtjev(`/prijave/${id}`),
  kreirajPrijavu: (fd) => zahtjev('/prijave', { method: 'POST', form: fd }),
  prijavaStatus: (id, status) => zahtjev(`/prijave/${id}/status`, { method: 'PATCH', body: { status } }),

  // Nalozi
  nalozi: (status) => zahtjev('/nalozi' + (status ? `?status=${status}` : '')),
  nalog: (id) => zahtjev(`/nalozi/${id}`),
  kreirajNalog: (b) => zahtjev('/nalozi', { method: 'POST', body: b }),
  azurirajNalog: (id, b) => zahtjev(`/nalozi/${id}`, { method: 'PATCH', body: b }),
  obrisiNalog: (id) => zahtjev(`/nalozi/${id}`, { method: 'DELETE' }),
  glasovniParse: (tekst, kategorije, voditelji, vozaci) =>
    zahtjev('/nalozi/glasovni-parse', { method: 'POST', body: { tekst, kategorije, voditelji, vozaci } }),
  nalogStatus: (id, status, napomena) => zahtjev(`/nalozi/${id}/status`, { method: 'PATCH', body: { status, napomena } }),
  dodjele: (id, radnici_ids) => zahtjev(`/nalozi/${id}/dodjele`, { method: 'PUT', body: { radnici_ids } }),
  dodajSate: (id, b) => zahtjev(`/nalozi/${id}/sati`, { method: 'POST', body: b }),
  obrisiSat: (id, sid) => zahtjev(`/nalozi/${id}/sati/${sid}`, { method: 'DELETE' }),
  dodajDio: (id, b) => zahtjev(`/nalozi/${id}/dijelovi`, { method: 'POST', body: b }),
  obrisiDio: (id, did) => zahtjev(`/nalozi/${id}/dijelovi/${did}`, { method: 'DELETE' }),
  dodajFoto: (id, fd) => zahtjev(`/nalozi/${id}/fotografije`, { method: 'POST', form: fd }),

  // Operacije i zadaci
  dodajOperaciju: (id, kategorija, zadaci = []) =>
    zahtjev(`/nalozi/${id}/operacije`, { method: 'POST', body: { kategorija, zadaci } }),
  obrisiOperaciju: (id, opId) => zahtjev(`/nalozi/${id}/operacije/${opId}`, { method: 'DELETE' }),
  dodajZadatak: (id, opId, opis) =>
    zahtjev(`/nalozi/${id}/operacije/${opId}/zadaci`, { method: 'POST', body: { opis } }),
  azurirajZadatak: (id, zadatakId, izmjene) =>
    zahtjev(`/nalozi/${id}/zadaci/${zadatakId}`, { method: 'PATCH', body: izmjene }),
  obrisiZadatak: (id, zadatakId) => zahtjev(`/nalozi/${id}/zadaci/${zadatakId}`, { method: 'DELETE' }),

  // Šteta
  stete: () => zahtjev('/stete'),
  procijeniStetu: (opis, vozilo_id) =>
    zahtjev('/stete/procjena', { method: 'POST', body: { opis, vozilo_id: vozilo_id || null } }),
  kreirajStetu: (b) => zahtjev('/stete', { method: 'POST', body: b }),
  azurirajStetu: (id, b) => zahtjev(`/stete/${id}`, { method: 'PATCH', body: b }),
  obrisiStetu: (id) => zahtjev(`/stete/${id}`, { method: 'DELETE' }),

  // Push
  pushKljuc: () => zahtjev('/push/kljuc'),
  pushPretplata: (subscription) => zahtjev('/push/pretplata', { method: 'POST', body: { subscription } }),
}
