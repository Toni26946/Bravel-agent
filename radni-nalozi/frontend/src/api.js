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

  // keepalive: odgođeno brisanje (↶ Poništi) se pri zatvaranju kartice mora stići poslati.
  const res = await fetch(BASE + '/api' + putanja, { method, headers, body: telo, keepalive: method === 'DELETE' })
  if (res.status === 401) {
    setToken(null)
    // Aplikacija Valjci ima svoju prijavu — ostaje na /valjci.
    if (location.pathname.startsWith('/valjci')) location.reload()
    else if (!location.pathname.startsWith('/prijava')) location.href = '/prijava'
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
  postaviSlikuVozila: (id, fd) => zahtjev(`/vozila/${id}/slika`, { method: 'POST', form: fd }),
  obrisiSlikuVozila: (id) => zahtjev(`/vozila/${id}/slika`, { method: 'DELETE' }),

  // Povijest zamjene dijelova (po kamionu)
  povijestDijelova: (voziloId) => zahtjev(`/vozila/${voziloId}/dijelovi`),
  dodajZamjenuDijela: (voziloId, b) => zahtjev(`/vozila/${voziloId}/dijelovi`, { method: 'POST', body: b }),
  obrisiZamjenuDijela: (voziloId, id) => zahtjev(`/vozila/${voziloId}/dijelovi/${id}`, { method: 'DELETE' }),
  pretraziDijelove: (q) => zahtjev('/dijelovi/pretraga?q=' + encodeURIComponent(q || '')),
  povijestRada: (voziloId) => zahtjev(`/vozila/${voziloId}/povijest-rada`),

  // Korisnici
  korisnici: (uloga) => zahtjev('/korisnici' + (uloga ? `?uloga=${uloga}` : '')),
  kreirajKorisnika: (b) => zahtjev('/korisnici', { method: 'POST', body: b }),
  uvozKorisnika: (tekst, uloga = 'radnik', lozinka) =>
    zahtjev('/korisnici/uvoz', { method: 'POST', body: { tekst, uloga, lozinka } }),
  azurirajKorisnika: (id, b) => zahtjev(`/korisnici/${id}`, { method: 'PATCH', body: b }),
  postaviOdsutnost: (id, b) => zahtjev(`/korisnici/${id}/odsutnost`, { method: 'PATCH', body: b }),

  // Prijave
  prijave: () => zahtjev('/prijave'),
  prijava: (id) => zahtjev(`/prijave/${id}`),
  kreirajPrijavu: (fd) => zahtjev('/prijave', { method: 'POST', form: fd }),
  prijavaStatus: (id, status) => zahtjev(`/prijave/${id}/status`, { method: 'PATCH', body: { status } }),

  // Nalozi
  nalozi: (status) => zahtjev('/nalozi' + (status ? `?status=${status}` : '')),
  nadzor: () => zahtjev('/nalozi/nadzor'),
  izasli: () => zahtjev('/nalozi/izasli'),
  izasliObavijest: () => zahtjev('/nalozi/izasli/obavijesti', { method: 'POST' }),
  nezaduzena: () => zahtjev('/nalozi/nezaduzena'),
  nezaduzenaDijagnostika: () => zahtjev('/nalozi/nezaduzena/dijagnostika'),
  vozilaRegistar: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString()
    return zahtjev('/vozila/registar' + (q ? `?${q}` : ''))
  },
  postaviStatusVozila: (gb, b) => zahtjev(`/vozila/registar/${encodeURIComponent(gb)}`, { method: 'PATCH', body: b }),
  vratiNaMobilisis: (gb) => zahtjev(`/vozila/registar/${encodeURIComponent(gb)}`, { method: 'PATCH', body: { rucno: false } }),
  urediPodatkeVozila: (gb, b) => zahtjev(`/vozila/registar/${encodeURIComponent(gb)}/podaci`, { method: 'PATCH', body: b }),
  uvozRegistar: (tekst) => zahtjev('/vozila/registar/uvoz', { method: 'POST', body: { tekst } }),
  novoVozilo: (b) => zahtjev('/vozila/novo', { method: 'POST', body: b }),
  provjeriGb: (gb) => zahtjev('/vozila/novo/provjera?gb=' + encodeURIComponent(gb)),
  spremneSlepe: () => zahtjev('/vozila/spremne'),
  prikljucna: () => zahtjev('/vozila/prikljucna'),
  paznja: () => zahtjev('/paznja'),
  zabiljeziPrikapcanje: (b) => zahtjev('/vozila/prikapcanje', { method: 'POST', body: b }),
  dnevnikPrikapcanja: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null)).toString()
    return zahtjev('/vozila/prikapcanje' + (q ? `?${q}` : ''))
  },
  prikapcanjeTrenutno: () => zahtjev('/vozila/prikapcanje/trenutno'),
  servisi: () => zahtjev('/vozila/servisi'),
  servisiUvoz: (stavke) => zahtjev('/vozila/servisi/uvoz', { method: 'POST', body: stavke }),
  servisiKmUvoz: (stavke) => zahtjev('/vozila/servisi/km-uvoz', { method: 'POST', body: stavke }),
  servisVozila: (gb) => zahtjev(`/vozila/servisi/vozilo/${encodeURIComponent(gb)}`),
  servisiUredi: (gb, b) => zahtjev(`/vozila/servisi/${encodeURIComponent(gb)}`, { method: 'PATCH', body: b }),
  pregledi: () => zahtjev('/vozila/pregledi'),
  pregledVozila: (gb) => zahtjev(`/vozila/pregledi/vozilo/${encodeURIComponent(gb)}`),
  urediPregled: (gb, b) => zahtjev(`/vozila/pregledi/${encodeURIComponent(gb)}`, { method: 'PATCH', body: b }),
  parkinzi: () => zahtjev('/vozila/parkinzi'),
  dodajParking: (naziv) => zahtjev('/vozila/parkinzi', { method: 'POST', body: { naziv } }),
  obrisiParking: (id) => zahtjev(`/vozila/parkinzi/${id}`, { method: 'DELETE' }),
  parkiranje: () => zahtjev('/nalozi/parkiranje'),
  parkingLokacija: (id, lokacija) => zahtjev(`/nalozi/${id}/parking`, { method: 'POST', body: { lokacija } }),
  parkingOtvoreno: (id) => zahtjev(`/nalozi/${id}/parking/otvoreno`, { method: 'POST' }),
  nalog: (id) => zahtjev(`/nalozi/${id}`),
  nalogLokacija: (id) => zahtjev(`/nalozi/${id}/lokacija`),
  izdatnice: (nalogId) => zahtjev(`/nalozi/${nalogId}/izdatnice`),
  dodajIzdatnicu: (nalogId, b) => zahtjev(`/nalozi/${nalogId}/izdatnice`, { method: 'POST', body: b }),
  obrisiIzdatnicu: (nalogId, id) => zahtjev(`/nalozi/${nalogId}/izdatnice/${id}`, { method: 'DELETE' }),
  // Narudžbe (dijelovi za naručiti) — unos iz naloga + skupni popis za skladištara
  narudzbeNaloga: (nalogId) => zahtjev(`/narudzbe/nalog/${nalogId}`),
  dodajNarudzbu: (nalogId, b) => zahtjev(`/narudzbe/nalog/${nalogId}`, { method: 'POST', body: b }),
  obrisiNarudzbu: (id) => zahtjev(`/narudzbe/${id}`, { method: 'DELETE' }),
  narudzbaFoto: (fd) => zahtjev('/narudzbe/foto', { method: 'POST', form: fd }),
  narudzbe: (status) => zahtjev(`/narudzbe${status ? `?status=${status}` : ''}`),
  narudzbaStatus: (id, status) => zahtjev(`/narudzbe/${id}/status`, { method: 'POST', body: { status } }),
  kreirajNalog: (b) => zahtjev('/nalozi', { method: 'POST', body: b }),
  azurirajNalog: (id, b) => zahtjev(`/nalozi/${id}`, { method: 'PATCH', body: b }),
  obrisiNalog: (id) => zahtjev(`/nalozi/${id}`, { method: 'DELETE' }),
  glasovniParse: (tekst, kategorije, voditelji, vozaci, radnici) =>
    zahtjev('/nalozi/glasovni-parse', { method: 'POST', body: { tekst, kategorije, voditelji, vozaci, radnici } }),
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
  azurirajOperaciju: (id, opId, izmjene) => zahtjev(`/nalozi/${id}/operacije/${opId}`, { method: 'PATCH', body: izmjene }),
  dodajZadatak: (id, opId, opis) =>
    zahtjev(`/nalozi/${id}/operacije/${opId}/zadaci`, { method: 'POST', body: { opis } }),
  azurirajZadatak: (id, zadatakId, izmjene) =>
    zahtjev(`/nalozi/${id}/zadaci/${zadatakId}`, { method: 'PATCH', body: izmjene }),
  zadatakMjerac: (id, zadatakId, akcija) =>
    zahtjev(`/nalozi/${id}/zadaci/${zadatakId}/mjerac`, { method: 'POST', body: { akcija } }),
  odjavaZadatak: (id, zadatakId) =>
    zahtjev(`/nalozi/${id}/zadaci/${zadatakId}/odjava`, { method: 'POST' }),
  obrisiZadatak: (id, zadatakId) => zahtjev(`/nalozi/${id}/zadaci/${zadatakId}`, { method: 'DELETE' }),
  // 📺 Upute iz videa (YouTube link uz zadatak)
  videoUpute: (zadatakId) => zahtjev(`/video-upute/zadatak/${zadatakId}`),
  videoUputePostavi: (zadatakId, url) => zahtjev(`/video-upute/zadatak/${zadatakId}`, { method: 'POST', body: { url } }),
  videoUputeObrisi: (zadatakId) => zahtjev(`/video-upute/zadatak/${zadatakId}`, { method: 'DELETE' }),

  // Samostalni rad (npr. vulkanizer): sam otvara posao i sam se prijavljuje
  samostalno: (kao) => zahtjev('/samostalno' + (kao ? `?kao=${kao}` : '')),
  samostalnoPosao: (gb, opis) => zahtjev('/samostalno/posao', { method: 'POST', body: { gb, opis } }),
  samostalnoAkcija: (zid, akcija) => zahtjev(`/samostalno/${zid}/${akcija}`, { method: 'POST' }),

  // Moja radiona (radnik vidi svoje operacije iz plana)
  planMoje: () => zahtjev('/plan/moje'),
  planPotvrdi: (zid) => zahtjev(`/plan/zadatak/${zid}/potvrdi`, { method: 'POST' }),
  planPrekini: (zid, razlog) => zahtjev(`/plan/zadatak/${zid}/prekini`, { method: 'POST', body: { razlog } }),

  // Zaduženje kamiona i prikolice (primopredajni obrazac)
  zaduzenja: () => zahtjev('/zaduzenja'),
  zaduzenje: (id) => zahtjev(`/zaduzenja/${id}`),
  zaduzenjePredlozak: () => zahtjev('/zaduzenja/predlozak'),
  zaduzenjeVozaci: () => zahtjev('/zaduzenja/vozaci'),

  // Šifrarnik vozača
  // Slobodni vozači (disponenti: vozači bez kamiona / kamion na popravku)
  slobodniVozaci: (sve) => zahtjev('/slobodni-vozaci' + (sve ? '?sve=true' : '')),
  dodajSlobodnogVozaca: (b) => zahtjev('/slobodni-vozaci', { method: 'POST', body: b }),
  urediSlobodnogVozaca: (id, b) => zahtjev(`/slobodni-vozaci/${id}`, { method: 'PUT', body: b }),
  zatvoriSlobodnogVozaca: (id) => zahtjev(`/slobodni-vozaci/${id}/zatvori`, { method: 'POST' }),
  vozaci: (aktivni) => zahtjev('/vozaci' + (aktivni ? '?aktivni=true' : '')),
  dodajVozaca: (b) => zahtjev('/vozaci', { method: 'POST', body: b }),
  azurirajVozaca: (id, b) => zahtjev(`/vozaci/${id}`, { method: 'PATCH', body: b }),
  obrisiVozaca: (id) => zahtjev(`/vozaci/${id}`, { method: 'DELETE' }),
  kreirajZaduzenje: (b) => zahtjev('/zaduzenja', { method: 'POST', body: b }),
  azurirajZaduzenje: (id, b) => zahtjev(`/zaduzenja/${id}`, { method: 'PATCH', body: b }),
  obrisiZaduzenje: (id) => zahtjev(`/zaduzenja/${id}`, { method: 'DELETE' }),
  razduziZaduzenje: (id) => zahtjev(`/zaduzenja/${id}/razduzenje`, { method: 'POST' }),

  // AI Poslovođa (norme, postavke, učinak)
  norme: () => zahtjev('/poslovodja/norme'),
  azurirajNormu: (id, b) => zahtjev(`/poslovodja/norme/${id}`, { method: 'PATCH', body: b }),
  preracunajNorme: () => zahtjev('/poslovodja/norme/preracunaj', { method: 'POST' }),
  poslovodjaPostavke: () => zahtjev('/poslovodja/postavke'),
  azurirajPoslovodjaPostavke: (b) => zahtjev('/poslovodja/postavke', { method: 'PATCH', body: b }),
  ucinak: (dana = 30) => zahtjev(`/poslovodja/ucinak?dana=${dana}`),
  obracunInfo: () => zahtjev('/poslovodja/obracun-info'),
  rekalibriraj: () => zahtjev('/poslovodja/rekalibriraj', { method: 'POST' }),
  ljestvica: (dana = 7) => zahtjev(`/ucinak/ljestvica?dana=${dana}`),
  mojUcinak: (dana = 7) => zahtjev(`/ucinak/moj?dana=${dana}`),
  sumnjivoBrzi: (dana = 1, prag = 120) => zahtjev(`/ucinak/sumnjivo-brzi?dana=${dana}&prag_sek=${prag}`),
  klikBonus: (dana = 30) => zahtjev(`/ucinak/klik-bonus?dana=${dana}`),
  klikPostavke: (izmjene) => zahtjev('/ucinak/klik-postavke', { method: 'POST', body: izmjene }),

  // Integracije (vlasnik) — APROSS / Zagreb Data
  gpsUredaji: () => zahtjev('/integracije/gps-uredaji'),
  cartecUredjaji: () => zahtjev('/cartec/uredjaji'),
  cartecOdobri: (id, odobren) => zahtjev(`/cartec/uredjaji/${id}`, { method: 'POST', body: { odobren } }),
  cartecObrisi: (id) => zahtjev(`/cartec/uredjaji/${id}`, { method: 'DELETE' }),
  testoviKocnica: ({ status = '', nalogId = '', gb = '' } = {}) => {
    const q = new URLSearchParams()
    if (status) q.set('status', status)
    if (nalogId) q.set('nalog_id', nalogId)
    if (gb) q.set('gb', gb)
    return zahtjev(`/cartec/testovi?${q.toString()}`)
  },
  cartecNaloziZaGb: (gb) => zahtjev(`/cartec/otvoreni-nalozi?gb=${encodeURIComponent(gb)}`),
  testKocnicaVezi:(id, nalogId) => zahtjev(`/cartec/testovi/${id}/vezi`, { method: 'POST', body: { nalog_id: nalogId } }),
  testKocnicaPoveznica: (id) => zahtjev(`/cartec/testovi/${id}/poveznica`),
  kocniceJavno: (oznaka) => zahtjev(`/cartec/javno/${encodeURIComponent(oznaka)}`),
  kocniceJavnoGb: (oznaka, gb, nalogId) => zahtjev(`/cartec/javno/${encodeURIComponent(oznaka)}/gb`, { method: 'POST', body: { gb, nalog_id: nalogId || null } }),
  testKocnicaNaWhatsapp: (id) => zahtjev(`/cartec/testovi/${id}/posalji-wa`, { method: 'POST' }),
  valjciUpozorenja: () => zahtjev('/cartec/upozorenja'),
  // Valjci — mjerenje kočnica preko mobitela
  valjciAktivna: () => zahtjev('/valjci/aktivna'),
  valjciNova: (podaci) => zahtjev('/valjci/sesija', { method: 'POST', body: podaci }),
  valjciSesija: (id) => zahtjev(`/valjci/sesija/${id}`),
  valjciOdabir: (id, odabir) => zahtjev(`/valjci/sesija/${id}/odabir`, { method: 'POST', body: odabir }),
  valjciZavrsi: (id) => zahtjev(`/valjci/sesija/${id}/zavrsi`, { method: 'POST' }),
  valjciOdustani: (id) => zahtjev(`/valjci/sesija/${id}/odustani`, { method: 'POST' }),
  kocniceJavnoPonisti: (oznaka) => zahtjev(`/cartec/javno/${encodeURIComponent(oznaka)}/ponisti`, { method: 'POST' }),
  gpsPoveziUredaj: (b) => zahtjev('/integracije/gps-uredaji', { method: 'POST', body: b }),
  arossStanje: () => zahtjev('/integracije/aross'),
  arossSpremi: (b) => zahtjev('/integracije/aross', { method: 'POST', body: b }),
  arossTest: () => zahtjev('/integracije/aross/test', { method: 'POST' }),
  arossZalihe: ({ nule = 0, osvjezi = 0 } = {}) => zahtjev(`/integracije/aross/zalihe?nule=${nule}&osvjezi=${osvjezi}`),
  arossSkladistaPopis: () => zahtjev('/integracije/aross/skladista'),
  arossPartneri: (q = '') => zahtjev(`/integracije/aross/partneri?q=${encodeURIComponent(q)}`),
  arossArtikliTrazi: (q = '') => zahtjev(`/integracije/aross/artikli?q=${encodeURIComponent(q)}`),
  arossPosaljiPrimku: (b) => zahtjev('/integracije/aross/primka', { method: 'POST', body: b }),
  arossPredloziArtikle: (stavke) => zahtjev('/integracije/aross/predlozi-artikle', { method: 'POST', body: { stavke } }),
  arossNoviArtikli: (stavke, jmj) => zahtjev('/integracije/aross/artikli/novi', { method: 'POST', body: { stavke, jmj } }),
  arossMjestaTroska: (q = '') => zahtjev(`/integracije/aross/mjesta-troska?q=${encodeURIComponent(q)}`),
  arossIzdatnicaPriprema: (nalogId) => zahtjev(`/integracije/aross/izdatnica/${nalogId}`),
  arossPosaljiIzdatnicu: (b) => zahtjev('/integracije/aross/izdatnica', { method: 'POST', body: b }),
  // Cjenik nabavnih cijena (uvoz iz „Kocka stanja")
  cjenikStanje: () => zahtjev('/integracije/cjenik'),
  cjenikUvoz: (file) => { const fd = new FormData(); fd.append('datoteka', file); return zahtjev('/integracije/cjenik/uvoz', { method: 'POST', form: fd }) },
  arossKreirajArtikl: (b) => zahtjev('/integracije/aross/artikl', { method: 'POST', body: b }),

  // Šteta
  stete: () => zahtjev('/stete'),
  glasovniParseStete: (tekst, vozaci) =>
    zahtjev('/stete/glasovni-parse', { method: 'POST', body: { tekst, vozaci } }),
  procijeniStetu: (opis, vozilo_id) =>
    zahtjev('/stete/procjena', { method: 'POST', body: { opis, vozilo_id: vozilo_id || null } }),
  kreirajStetu: (b) => zahtjev('/stete', { method: 'POST', body: b }),
  azurirajStetu: (id, b) => zahtjev(`/stete/${id}`, { method: 'PATCH', body: b }),
  obrisiStetu: (id) => zahtjev(`/stete/${id}`, { method: 'DELETE' }),
  dodajStetaFoto: (id, fd) => zahtjev(`/stete/${id}/fotografije`, { method: 'POST', form: fd }),
  obrisiStetaFoto: (id, fid) => zahtjev(`/stete/${id}/fotografije/${fid}`, { method: 'DELETE' }),

  // Primke robe (otpremnice dobavljača — skladište)
  primke: () => zahtjev('/primke'),
  izdatniceSve: () => zahtjev('/primke/izdatnice'),
  trosakPoVozilu: (od = '', do_ = '') => zahtjev(`/primke/trosak-po-vozilu?od=${od}&do=${do_}`),
  primka: (id) => zahtjev(`/primke/${id}`),
  uploadStranicaOtpremnice: (fd) => zahtjev('/primke/stranica', { method: 'POST', form: fd }),
  // Čitanje u POZADINI: start vrati id posla, pa se stanje provjerava svake 2,5 s
  // (duga otpremnica se čita i preko minute — jedan dugi zahtjev mobitel prekine).
  procitajOtpremnicu: async (fotke) => {
    const s = await zahtjev('/primke/procitaj/start', { method: 'POST', body: { fotke } })
    if (!s.ai) return { ai: false }
    const kraj = Date.now() + 6 * 60 * 1000
    let greskeMreze = 0
    while (Date.now() < kraj) {
      await new Promise((r) => setTimeout(r, 2500))
      let p
      try { p = await zahtjev(`/primke/procitaj/posao/${s.posao_id}`) }
      catch (e) {
        // kratki prekid mreže (npr. mobitel mijenja signal) — probaj dalje; 404 = posao izgubljen
        if (/nije pronađeno/.test(e.message || '') || ++greskeMreze > 10) throw e
        continue
      }
      greskeMreze = 0
      if (p.status === 'gotovo') return p.rezultat
      if (p.status === 'greska') throw new Error(p.greska || 'AI nije uspio pročitati otpremnicu.')
    }
    throw new Error('Čitanje traje predugo (više od 6 min) — pokušaj ponovno s manje stranica.')
  },
  kreirajPrimku: (b) => zahtjev('/primke', { method: 'POST', body: b }),
  azurirajPrimku: (id, b) => zahtjev(`/primke/${id}`, { method: 'PATCH', body: b }),
  obrisiPrimku: (id) => zahtjev(`/primke/${id}`, { method: 'DELETE' }),
  narucitelji: () => zahtjev('/primke/narucitelji'),
  urediStavku: (id, idx, b) => zahtjev(`/primke/${id}/stavka/${idx}`, { method: 'PATCH', body: b }),
  dodajRazduzenje: (id, idx, b) => zahtjev(`/primke/${id}/stavka/${idx}/razduzenje`, { method: 'POST', body: b }),
  obrisiRazduzenje: (id, idx, rid) => zahtjev(`/primke/${id}/stavka/${idx}/razduzenje/${rid}`, { method: 'DELETE' }),
  // Dispečer dijelovi: operacije koje čekaju dijelove (po GB) + „dio stigao → vrati mehaničaru"
  cekaDijelove: (gb) => zahtjev('/dispecer/ceka-dijelove' + (gb ? `?gb=${encodeURIComponent(gb)}` : '')),
  dioStigao: (zadatakId) => zahtjev(`/dispecer/dio-stigao/${zadatakId}`, { method: 'POST' }),
  preuzmiPrimkeExcel: async () => {
    const res = await fetch(BASE + '/api/primke/izvoz.xlsx', {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
    if (!res.ok) throw new Error(`Izvoz nije uspio (${res.status})`)
    return res.blob()
  },
  preuzmiPrimkuExcel: async (id) => {
    const res = await fetch(BASE + `/api/primke/${id}/izvoz.xlsx`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
    if (!res.ok) throw new Error(`Izvoz nije uspio (${res.status})`)
    return res.blob()
  },

  // Evidencija radnog vremena
  evidencijaMjesec: (godina, mjesec) => zahtjev(`/evidencija?godina=${godina}&mjesec=${mjesec}`),
  spremiEvidenciju: (b) => zahtjev('/evidencija', { method: 'PUT', body: b }),
  uzimanjaPopis: (godina, mjesec) => zahtjev(`/evidencija/uzimanja?godina=${godina}&mjesec=${mjesec}`),
  uzimanjeDodaj: (b) => zahtjev('/evidencija/uzimanja', { method: 'POST', body: b }),
  uzimanjeObrisi: (id) => zahtjev(`/evidencija/uzimanja/${id}`, { method: 'DELETE' }),
  preuzmiEvidencijuExcel: async (godina, mjesec) => {
    const res = await fetch(BASE + `/api/evidencija/izvoz.xlsx?godina=${godina}&mjesec=${mjesec}`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
    if (!res.ok) throw new Error(`Izvoz nije uspio (${res.status})`)
    return res.blob()
  },

  // Flota OS (GPS) dijagnostika
  flotaStatus: () => zahtjev('/flota/status'),
  flotaProvjeri: () => zahtjev('/flota/provjeri', { method: 'POST' }),

  // Imenik telefona — samo čitanje (izvor je Flota OS)
  imenik: (osvjezi = false) => zahtjev('/imenik' + (osvjezi ? '?osvjezi=1' : '')),
  // Upis SAMO za odjel RADIONA (ide u Flotu; vraća svježi imenik)
  imenikRadionaSpremi: (zapis) => zahtjev('/imenik/radiona', { method: 'POST', body: zapis }),
  imenikRadionaAktivan: (id, aktivan) => zahtjev(`/imenik/radiona/${id}/aktivan?aktivan=${aktivan}`, { method: 'POST' }),

  // Push
  pushKljuc: () => zahtjev('/push/kljuc'),
  pushPretplata: (subscription) => zahtjev('/push/pretplata', { method: 'POST', body: { subscription } }),
  pushTest: () => zahtjev('/push/test', { method: 'POST' }),
}
