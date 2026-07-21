# STANJE PROJEKTA — Bravel / Jarvis (ažurirano 21.7.2026.)

## Infrastruktura
- bravel-agent (fly.io, ams): Telegram bot + web API. Deploy: push na main
  → GitHub Actions. Manualni deploy samo iznimno.
- bravel-monitor (fly.io): monitoring bot, prima na
  http://bravel-monitor.internal:8080/ingest
- SharePoint: braveldoo.sharepoint.com/sites/tendenzanova, biblioteka
  "Zajednički dokumenti", mapa BRAVEL

## fly secrets (app bravel-agent) — SAMO NAZIVI, vrijednosti u password
manageru vlasnika (Toni) i NIKAD u repo/chat:
- TELEGRAM_TOKEN — Telegram bot
- FLY_TOKEN — deploy
- ANTHROPIC_API_KEY — Claude API (haiku konverzacija, sonnet vision)
- MONITOR_SECRET, MONITOR_INGEST_URL — veza na bravel-monitor
- GRAPH_CLIENT_ID, GRAPH_TENANT_ID, GRAPH_CLIENT_SECRET — Azure app
  "BravelBot-Graph" (Sites.ReadWrite.All). Secret ISTJEČE ~srpanj 2028,
  podsjetnik u kalendaru lipanj 2028.
- MOBILISIS_USER, MOBILISIS_PASS — Mobilisis API račun "bravel-api"
- FLOTA_OS_KEY — ključ za GET /api/pozicije (header X-Api-Key)
- WHATSAPP_TOKEN — WhatsApp Cloud API (System User token; MORA biti čist,
  bez sufiksa/razmaka — "malformed token" ako se zalijepi s opisom)
- WHATSAPP_PHONE_ID — 1270404739480944 (Phone number ID, nije osjetljivo)
- WHATSAPP_VERIFY_TOKEN — proizvoljan niz za verifikaciju webhooka; isti
  upisan u Meta App → WhatsApp → Configuration → Callback URL
- WHATSAPP_ALLOWED — brojevi zaposlenika (385…, zarezom) koji smiju slati
  račune/primke preko WhatsAppa; prazno = nitko (samo obavijest vlasnicima)
- WHATSAPP_DRIVERS — (opcionalno) mapa broj→ime vozača za tablicu; format
  "385994396448=Ivan Ivić:GB123-AB; 385…=Marko Marić" (dio ":GB" opcionalan,
  koristi se kao zadani GB na „.”). Prazno = koristi se WhatsApp profil/broj.
- WHATSAPP_PAGE_WINDOW — (opcionalno) sekunde čekanja daljnjih stranica kod
  višestraničnih dokumenata; default 8
- WHATSAPP_PODSJETNICI_ON — "1" uključuje automatske tjedne podsjetnike
  vozačima; prazno/≠1 = isključeno (raspored se ne okida). Ručni /wa_podsjetnici
  radi i dok je isključeno (force).
- WHATSAPP_PODSJETNIK_DAN/SAT/MIN — raspored (default petak=4, 15, 0)
- WHATSAPP_PODSJETNIK_DANI — preskoči vozača koji je slao unutar toliko dana (5)
- WHATSAPP_PODSJETNIK_PERIOD — tekst {{2}} u predlošku ("ovaj tjedan")
- WHATSAPP_PODSJETNIK_TMPL — naziv predloška ("podsjetnik_racun")
- BENZINSKE_ON — "1" uključuje automatsko osvježavanje cijena goriva;
  prazno/≠1 = isključeno (ručni /benzinske radi uvijek)
- BENZINSKE_SATI — sati osvježavanja, zarezom (default "7,13,19"; minuta 5)
- FLOTA_OS_SERVICE_KEY — servisni ključ kojim AI podrška čita flota-os API
  (prihod/profitabilnost/ture); MORA biti ista vrijednost kao fly secret
  SERVICE_KEY na app bravel-flota-os-api. Prazno = ti alati javljaju
  "nije konfigurirano". (opcionalno FLOTA_OS_API_URL, ima default)

## Mobilisis API (od 14.7.)
- Server: https://fleet2.mobilisis.hr/geocodeAndZoneAPI/api/v1
- Login: POST /positions/getSessionKey {"username","password"} → Bearer
  token 24h (produžuje se korištenjem)
- API račun se kreira na fleet platformi: Globalni podaci → Mobilisis →
  Dodaj API korisnički račun (username/lozinku generira sustav)
- Povezane grupe: Trenutna pozicija vozila, Gorivo (JOŠ NEISTRAŽENO —
  sljedeći korak za kalibraciju sonde), Radni nalozi/putni računi,
  Geokodiranje/zone
- Modul: mobilisis.py (login, token cache, get_devices, get_positions,
  all_positions; REG↔GB iz "GARAŽNI BROJEVI.xlsx" na SharePointu,
  kolone GB i REG OZNAKA, keš 24h)

## Web API (od 14.7.)
- GET /zdrav → {"status":"ok"} (bez ključa)
- GET /api/pozicije → pozicije flote; header X-Api-Key = FLOTA_OS_KEY;
  keš 30 s; 401 bez ključa; 503 + "zastarjelo" ako Mobilisis padne
- GET /api/benzinske → registar lanaca (Adria Oil, Tifon, Shell, Petrol,
  Brebrić, AS24, DKV) s lokacijom/izvorom + zadnjim cijenama i promjenom;
  header X-Api-Key = FLOTA_OS_KEY; čita iz baze (bez vanjskih poziva)
- WS /api/podrska/ws?key=FLOTA_OS_KEY&ime=… → živi chat podrške (interni
  korisnici Flote OS ↔ vlasnici na Telegramu); GET /api/podrska = demo/test
  stranica chata (bez frontenda)
- Namjena: Flota OS (Jarvis) živa karta — FAZA 2 u tijeku

## Podrška — živi chat s AI-jem (od 20.7., modul podrska.py)
- Namjena: interni korisnici (dispečeri) na Floti OS razgovaraju s AI ASISTENTOM
  (Claude haiku) o korištenju Flote OS. NIJE most na čovjeka — AI odgovara.
- Backend: WebSocket u web_api (aiohttp) — /api/podrska/ws (štiti key=FLOTA_OS_KEY).
  Korisnikova poruka → callback _podrska_ai_odgovori (main.py): agentic tool-use
  petlja (client.messages.create s PODRSKA_SYSTEM_PROMPT + PODRSKA_TOOLS + povijest)
  → odgovor natrag preko WS-a. Povijest po sesiji u RAM-u (_podrska_hist), briše se
  na zatvaranje (set_on_zatvoreno → _podrska_zatvori).
- ALATI (čita žive podatke): cijene_goriva (benzinske.trenutno), pozicija_vozila
  (mobilisis.lookup po reg/GB), te FLOTA OS API (prihod, profitabilnost, ture) —
  bravel-agent zove bravel-flota-os-api sa zaglavljem X-Service-Key (=fly secret
  FLOTA_OS_SERVICE_KEY; ista tajna kao SERVICE_KEY na flota-os backendu). Ključ
  nikad ne ide korisniku. FLOTA_OS_API_URL default https://bravel-flota-os-api.fly.dev.
  ⚠️ Radi tek kad se postavi ista tajna na OBJE strane (v. dolje).
- Niti: AI poziv (blokirajući) ide u run_in_executor (ne blokira aiohttp loop);
  odgovor u sesijin asyncio.Queue preko call_soon_threadsafe. Sesije ephemeralne.
- Telegram (owner): /podrska (popis aktivnih sesija; odgovara AI), /podrska <id>
  <tekst> = ručni ljudski upad (override) ako baš treba.
- Demo/test: GET /api/podrska (samostalna HTML chat stranica; FLOTA_OS_KEY + ime).
- Flota OS (repo toni26946/flota-os): frontend widget PodrskaChat.jsx + backend
  WS proxy /api/podrska/ws (dodaje server-side ključ) → spaja se na ovaj WS.
  Poruke: šalje {tekst}, prima {tip:"podrska"|"sustav", od, tekst, vrijeme}.

## Benzinske / cijene goriva (od 16.7., modul benzinske.py)
- Registar lanaca koje Bravel koristi: maloprodaja (Adria Oil, Tifon, Shell,
  Petrol, Brebrić) → javni dnevni cjenik; kartice (AS24, DKV) → B2B, cijena
  ugovorna, bez javnog cjenika (pratimo samo mrežu/lokaciju).
- Cijene: scraping (nema službenog HR API-ja za cijene goriva). Generički
  ekstraktor (ključna riječ goriva + najbliža cijena, sanity 0,3–3,0 €/l).
  Pohrana povijesti u bot.db (tablica benzinske_cijene) — upis SAMO na
  promjenu cijene. Snapshot preko benzinske.trenutno() (zadnja + prethodna +
  smjer) služi /api/benzinske.
- Scheduler: check_reminders okida osvježavanje ako je BENZINSKE_ON=1, u
  satima BENZINSKE_SATI (default "7,13,19"), u minuti 5; kod promjene javi
  sažetak vlasnicima na Telegram. UKLJUČENO ✅ (21.7., BENZINSKE_ON=1 u fly.toml [env]).
- Lokacije postaja: automatski iz OpenStreetMapa (Overpass API) po brendu
  (benzinske.dohvati_postaje, tjedni keš); /api/benzinske vraća "postaje"
  (lat/lon/naziv/grad) po lancu. Fallback: ručna točka iz registra (Brebrić).
  Keš se zagrijava na startu (thread) i osvježava uz cijene (tjedni TTL).
- Telegram (owner): /benzinske (osvježi cijene), /benzinske stanje (zadnje iz
  baze), /benzinske postaje (osvježi+prebroji lokacije iz OSM-a),
  /benzinske probe <URL> (dijagnostika izvora — dostupnost + uzorak HTML-a).
- Izvor cijena: cijene-goriva.autoportal.hr (po kompaniji; podaci iz
  ministarskog mzoe-gor.hr). POTVRĐENO s Fly-a (16.7.): autoportal se
  razrješava i parser hvata cijene; cijenegoriva.hr NE (DNS greška),
  nafta.hr 200 ali bez cijena u HTML-u. Slugovi potvrđeni: tifon-doo,
  adria-oil-doo; shell(coral-croatia-doo)/petrol-doo/benzinska-pumpa-brebric
  su POGODAK — potvrditi /benzinske probe.
- ✅ STATUS (21.7.): potvrđeni slugovi i parser za svih 5 lanaca (Tifon, Adria
  Oil, Shell, Petrol, Brebrić); lokacije iz OSM-a (251 postaja); automatsko
  praćenje UKLJUČENO (BENZINSKE_ON=1). AS24/DKV ostaju bez cijene (kartica).
- ✅ RIJEŠENO (21.7.): fly app SADA doseže fleet2.mobilisis.hr (Mobilisis IP
  whitelist za "bravel-api" sređen). /api/pozicije, /gdje (Telegram) i
  📍 lokacija na WhatsAppu RADE s Fly-a. Živa karta (Flota OS) povlači pozicije.
  (Povijesna napomena: 15.7.–20.7. je bila ConnectTimeout blokada dok fly
  izlazna IP nije bila dopuštena.)

## Telegram bot — funkcije
- Računi/primke: slika → Claude vision → potvrda → SharePoint Excel
  (Racuni_terena.xlsx, Primke_terena.xlsx) + slika u BRAVEL/Dokumenti_slike/
  + HYPERLINK u koloni "Slika" (Graph formule: ZAREZ separator, en-US!)
- /gdje <GB ili registracija> → živa pozicija kamiona (Mobilisis)
- Backup bot.db dnevno u 03:00 → BRAVEL/Backup/ (retencija 30 dana)

## WhatsApp (dvosmjerno RADI, app LIVE, stanje 15.7.)
- Meta app "Bravel" (App ID 910214341385042), display name "Bravel",
  OBJAVLJEN/LIVE 15.7. (business verification BRAVEL D.O.O. ✅ 14.7.),
  preko bratovog (Roko) računa. Privacy Policy + Data deletion URL =
  https://bravel-agent.fly.dev/privatnost (ruta u web_api.py).
  WABA "Bravel doo", WABA ID 1482419453685574 (raniji 2489346474912515 je
  vjerojatno Business Portfolio ID, ne WABA)
- Broj +385 1 6539 906 REGISTRIRAN na Cloud API (Connected), Phone number
  ID 1270404739480944, dvokoračni PIN postavljen (u password manageru)
- Broj je na Yealink VoIP centrali — buduće verifikacije: Yealink →
  Menu → Features → Call Forward → Always Forward na mobitel → primi
  kod → Forward OFF
- Modul whatsapp.py: register(pin), send_text, send_template. Admin
  Telegram komande (owner-only):
  - /wa_register <pin> — registracija broja / prikaz točne Meta greške
  - /wa_test <broj>    — hello_world (RADI SAMO s Metinog Public Test
    Numbera, ne s pravog broja → koristi se samo za dijagnostiku)
  - /wa_send <broj> <tekst> — obična poruka; RADI unutar 24 h prozora
    (korisnik mora prvi pisati poslovnom broju). Broj se normalizira
    (0994396448 → 385994396448)
  - /wa_token — dijagnostika tokena preko Graph /debug_token (ne otkriva
    token): tip, valjanost, kad istječe (expires_at=0 → permanentni ✅),
    dozvole. Ako nije permanentan → uputa za System User token „Never"
    POTVRĐENO 16.7.: token je SYSTEM_USER, permanentni (istječe NIKAD) ✅
  - /wa_predlosci [WABA_ID] — status predložaka; bez arg. lista SVE WABA-e
    tokena (list_wabas), s arg. ciljanu. Naši označeni ⭐. WABA iz
    WHATSAPP_WABA_ID (fallback 1482419453685574)
  - /wa_kreiraj_predloske [WABA_ID] — kreira 4 UTILITY predloška (hr) na WABA-i
    (default 1482) preko Graph API-ja (whatsapp.create_template)
  - /wa_predlozak <broj> <naziv> [var1 | var2 | ...] — pošalji BILO KOJI
    odobreni predložak (jezik hr; varijable odvojene s „|")
  - /wa_podsjetnici — ručno okine tjedne podsjetnike (force; v. dolje)
  VAŽNO (16.7.): predlošci su bili kreirani na Test WABA-i (1596…), a broj je
  na „Bravel doo" (1482…). Presloženi (kreirani) na 1482 preko
  /wa_kreiraj_predloske → sad na ISTOJ WABA-i kao broj. Čekaju odobrenje.
  Profilna slika (logo „B" iz brand loga) POSTAVLJENA ✅ (21.7.). Display name
  „Bravel doo" odobren.
- PRIMANJE: webhook GET/POST /whatsapp/webhook (web_api.py) VERIFICIRAN;
  dolazne poruke → Telegram obavijest svim ALLOWED_USERS
  (main.py wa_dolazna_poruka). Verify token = WHATSAPP_VERIFY_TOKEN;
  pretplata na polje "messages" u Meta Configuration.
- POTVRĐENO 15.7.: /wa_send šalje (bot → korisnik) I webhook prima
  (Test događaj stigao na Telegram).
- APP LIVE 15.7. → webhook prima STVARNE dolazne poruke; slanje nije
  ograničeno na test-brojeve.
- Display name "Bravel doo" ODOBREN i vidljiv klijentima (15.7.), Quality High.
- Payment method DODAN na WABA "Bravel doo" (MasterCard, 15.7.) → otključano
  slanje business-initiated predložaka (podsjetnici izvan 24 h prozora).
  Balance 0 € dok se ne pošalje naplativi predložak.
- Token: POTVRĐEN permanentnim (System User, Never-expire) ✅ (16.7., /wa_token).
- PREDLOŠCI (5, definirani u main.py _WA_PREDLOSCI_DEF; svi UTILITY, hr):
  potvrda_racuna, podsjetnik_racun, podsjetnik_voznje, poruka_dispecera,
  podsjetnik_opci. Kreiranje /wa_kreiraj_predloske (na WABA 1482), status
  /wa_predlosci. Čekaju Meta odobrenje (PENDING → APPROVED/REJECTED). Puni
  submission/approval vodič + compliance checklist + rejection playbook:
  WHATSAPP_PREDLOSCI.md. Pri slanju send_template s lang_code="hr" (default en_US).
- SELIDBA NA WHATSAPP — FAZA 1 RADI (potvrđeno 15.7.): ovlašteni zaposlenik
  (WHATSAPP_ALLOWED) šalje FOTO računa/primke → whatsapp_racuni.py: slika →
  racuni._read_document (vision) → pita GB → gumbi ✅/❌ → racuni._prepare_image
  (upload slike) → racuni._write_once (upis na SharePoint). Ponovno koristi
  ČISTU jezgru iz racuni.py; Telegram tok netaknut (vlasnici ostaju na TG).
  Obrada u zasebnom threadu (webhook odmah 200 → nema duplikata).
  v2 RADI (15.7.): provjera duplikata (racuni._find_duplicate, dup se NE upisuje)
  + "Ispravi" polje (3. gumb, racuni._edit_aliases/_edit_field_names).
  v3 (15.7.): tri stavke gotove u kodu (whatsapp_racuni.py):
  - "Promijeni vrstu" (račun↔primka): tijekom potvrde napiši „vrsta” →
    racuni._read_document(images, force_vrsta=…), ponovni sažetak. Ide tekstom
    a ne 4. gumbom jer WhatsApp interactive dopušta max 3 reply-gumba.
  - Višestranični dokumenti: uzastopne fotke se sakupe (debounce _PAGE_WINDOW,
    default 8 s; „gotovo” završava odmah) → _read_document čita sve stranice,
    _prepare_image uploada _str1/_str2… Buffer po broju (_pending), thread-safe.
  - Imena vozača po broju: WHATSAPP_DRIVERS (broj→ime[:GB]) → pravo ime u
    tablicu; „.” u koraku GB prihvaća zadani GB iz mape.
  v3 ZAVRŠENO ✅ (21.7.): 📍 lokacija vozila na WhatsAppu (whatsapp_meni.py,
  _gdje_lookup → Mobilisis) RADI — Mobilisis whitelist sređen, ništa blokirano.
- AUTOMATSKI PODSJETNICI (kod gotov, whatsapp_podsjetnici.py): petkom (env
  DAN/SAT/MIN) bot šalje predložak podsjetnik_racun vozačima iz WHATSAPP_DRIVERS
  koji nisu slali zadnjih N dana (aktivne preskače; aktivnost se bilježi u
  tablicu wa_aktivnost pri uspješnom WhatsApp upisu). Prekidač
  WHATSAPP_PODSJETNICI_ON=1 (default OFF). Ručni test: /wa_podsjetnici (force).
  Šalje TEK kad Meta odobri predložak podsjetnik_racun; do tad send_template
  vraća grešku koja se uredno prikaže u sažetku (ne ruši).
- WhatsApp IZBORNIK / upravljačka ploča (whatsapp_meni.py, #37): dolazni tekst
  vozača/radnika → interaktivni izbornik (prijava kvara, podsjetnik, evidencija
  sati…). Vlastiti podsjetnik radnika ide predloškom podsjetnik_opci izvan prozora.
- EVIDENCIJA SATI (#39): radnik preko WhatsAppa upisuje radne sate → uz bazu i
  u SharePoint Excel.
- Predlošci: v. gore (5 komada, čekaju Meta odobrenje) — WHATSAPP_PREDLOSCI.md.

## Poznate zamke
- monitoring.install() guta iznimke threadova → greške idu u monitoring
  bot, NE u fly logs
- fly secrets set = brzi restart → utrka oko porta 8080 → web_api ima
  bind retry (6×/2 s); svaki boot mora imati "[web_api] HTTP server
  sluša" u logu
- Prazni retci u Excel tablicama razvlače formule i kvare append —
  brisati Delete → Table Rows
- PowerShell: curl.exe (ne curl); API ključevi samo slova+brojevi
- Graph API formule: zarez separator; upload slike PRIJE append retka
- WhatsApp: hello_world ide SAMO s Public Test Numbera (#131058) — s
  pravog broja koristi vlastite odobrene predloške ili /wa_send unutar
  24 h prozora; WHATSAPP_TOKEN mora biti čist (bez " za whatsapp" i sl.,
  inače #190 malformed)

## TODO / planirano

### Savjetnik za točenje goriva (KADA + GDJE) — planirano
Cilj: AI javi KADA kamion treba točiti i GDJE vozač može natočiti (kartice/mreže),
posebno na EU rutama. Razrada:
- KADA (razina goriva/domet):
  - Mobilisis sonda goriva (stvarna razina %) — PREDUVJET, sonda još
    nekalibrirana / grupa "Gorivo" neistražena; treba istražiti + kalibrirati.
  - Fallback procjena: zadnje točenje + prijeđeni km + prosječna potrošnja
    (l/100km iz Flote OS) → procijenjeni domet.
  - Prag: razina/domet ispod praga ILI ne može do odredišta + rezerva → "točiti".
- GDJE (postaje mreža kojima se plaća karticom, po Europi):
  - AS24 (kamionska mreža) — vlastite postaje, iz OSM-a po Europi (bounded). ✅ prioritet.
  - Shell — OSM po brendu (velik → clustering).
  - DKV/UTA — kartica na ~60k partnerskih pumpi; NEMA brenda u OSM-u → treba
    njihov službeni station-finder (kasnija faza).
  - HR: Adria Oil/Tifon/Petrol/Brebrić (već imamo).
  - Najbliže po RUTI (Flota OS već ima kamionski routing), ne zračnoj liniji.
- Kako AI javlja:
  - Na upit (podrska AI): "gdje kamion GB X može natočiti?" → GPS pozicija →
    najbliže postaje mreža → adrese + udaljenost.
  - Proaktivno: raspored provjerava razine; nisko + daleko od cilja → obavijest
    vlasnicima ("kamion X ≈120 km dometa, najbliža AS24: Y, 18 km").
- Redoslijed: Faza 1 GDJE na upit (AS24 index + AI alat najbliza_pumpa); Faza 2
  KADA (Mobilisis gorivo/procjena + pragovi + proaktivno); Faza 3 DKV/UTA finder.
- OTVORENO (treba od vlasnika): (1) koje kartice/mreže vozači stvarno koriste na
  EU rutama (AS24/DKV/Shell/UTA…) → određuje koje postaje indeksiramo; (2) imamo
  li pristup razini goriva iz Mobilisisa ili idemo na procjenu iz potrošnje.
