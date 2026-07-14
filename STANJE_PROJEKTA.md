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

## Telegram bot — funkcije
- Računi/primke: slika → Claude vision → potvrda → SharePoint Excel
  (Racuni_terena.xlsx, Primke_terena.xlsx) + slika u BRAVEL/Dokumenti_slike/
  + HYPERLINK u koloni "Slika" (Graph formule: ZAREZ separator, en-US!)
- /gdje <GB ili registracija> → živa pozicija kamiona (Mobilisis)
- Backup bot.db dnevno u 03:00 → BRAVEL/Backup/ (retencija 30 dana)

## WhatsApp (u tijeku, stanje 14.7.)
- WABA ID 2489346474912515, "Bravel d.o.o.", broj +385 1 6539 906
  VERIFICIRAN (status Pending = čeka registraciju na Cloud API kroz app)
- Broj je na Yealink VoIP centrali — buduće verifikacije: Yealink →
  Menu → Features → Call Forward → Always Forward na mobitel → primi
  kod → Forward OFF
- BLOKADA: Meta app još ne postoji. Tonijev FB odbijen za developer
  registraciju; radi se preko bratovog (Roko) računa — stalo na SMS
  verifikaciji. Nakon app-a: system user "bravel-bot" (Admin) → token
  (Never, whatsapp_business_messaging + management) → fly secrets
  WHATSAPP_TOKEN + WHATSAPP_PHONE_ID
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
