# STANJE PROJEKTA — Bravel / Jarvis (ažurirano 14.7.2026.)

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
- Namjena: Flota OS (Jarvis) živa karta — FAZA 2 u tijeku
- ⚠️ BLOKADA (15.7.): fly app NE MOŽE do fleet2.mobilisis.hr —
  ConnectTimeout (TCP spajanje istekne, nema odgovora). /api/pozicije i
  /gdje padaju S FLY-A. Potpis firewalla koji tiho odbacuje pakete →
  vjerojatno IP whitelist na Mobilisis strani (fly izlazna IP nije
  dopuštena). Rješenje: whitelistati fly izlaznu IP
  (fly ssh console -a bravel-agent -C "curl -s https://api.ipify.org")
  kod API računa "bravel-api"; fly IP se zna mijenjati → možda treba
  fiksni egress/proxy. NAPOMENA: živa karta zove /api/pozicije svakih
  30 s → dok Mobilisis pada, monitoring se puni istim errorom
  (kandidat za rate-limit)

## Telegram bot — funkcije
- Računi/primke: slika → Claude vision → potvrda → SharePoint Excel
  (Racuni_terena.xlsx, Primke_terena.xlsx) + slika u BRAVEL/Dokumenti_slike/
  + HYPERLINK u koloni "Slika" (Graph formule: ZAREZ separator, en-US!)
- /gdje <GB ili registracija> → živa pozicija kamiona (Mobilisis)
- Backup bot.db dnevno u 03:00 → BRAVEL/Backup/ (retencija 30 dana)

## WhatsApp (dvosmjerno RADI, stanje 15.7.)
- Meta app "BravelBot" (unpublished), preko bratovog (Roko) računa.
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
- PRIMANJE: webhook GET/POST /whatsapp/webhook (web_api.py) VERIFICIRAN;
  dolazne poruke → Telegram obavijest svim ALLOWED_USERS
  (main.py wa_dolazna_poruka). Verify token = WHATSAPP_VERIFY_TOKEN;
  pretplata na polje "messages" u Meta Configuration.
- POTVRĐENO 15.7.: /wa_send šalje (bot → korisnik) I webhook prima
  (Test događaj stigao na Telegram).
- TODO: token provjeriti da je permanentni (System User, Never-expire) —
  inače istječe za 24 h; predlošci poruka_dispecera / potvrda_racuna na
  odobrenje (+ payment method za business-initiated izvan 24 h prozora);
  PUBLISH app (dok je unpublished, slanje samo na test-primatelje I webhook
  prima samo TEST događaje iz dashboarda — stvarne dolazne poruke tek nakon
  objave + business verification)
- Template-i Faza 1 (skicirani): poruka_dispecera, potvrda_racuna;
  fale: podsjetnik_racun, podsjetnik_voznje

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
