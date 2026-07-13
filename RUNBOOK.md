# RUNBOOK — Bravel sustav (Telegram bot + monitor)

> Priručnik za održavanje sustava ako Toni nije dostupan. Sve je izvedeno iz
> stvarnog stanja koda i konfiguracije (repo `Bravel-agent`, Fly.io, SharePoint,
> Azure). Gdje podatak nije poznat iz koda, stoji `[POPUNITI]`.
>
> Zadnji pregled koda: 2026-07-13.

---

## 1. ŠTO SUSTAV RADI

Bravel je **Telegram bot** (`bravel-agent`) koji radnicima služi za (a) podsjetnike
(jednokratne i ponavljajuće), (b) AI razgovor i dnevni izvještaj rada (Claude), te
(c) obradu **fotografija računa i primki** — automatski prepoznaje vrstu, OCR-om
izvuče podatke (Claude vision), i nakon potvrde upisuje retke u **Excel tablice na
SharePointu** (Microsoft Graph API), uz spremanje originalne fotke. Bot je stateful
u **SQLite bazi** na Fly volumenu (`/data/bot.db`), koja se **jednom dnevno backupira
na SharePoint**. Uz njega radi zaseban **monitor bot** (`bravel-monitor`) koji prima
greške/logove i "puls" (heartbeat) glavnog bota i **alarmira administratora na Telegram**
ako nešto pukne ili bot zašuti. Sve vanjske integracije su best-effort: kvar SharePointa,
Claudea ili monitoringa ne smije srušiti bota.

```
   Radnik (Telegram)
        │  poruka / fotka
        ▼
  ┌───────────────────────┐        Claude API (Anthropic)
  │   bravel-agent        │◀──────▶  - haiku-4-5 (razgovor/sažetak)
  │   (Fly.io, ams)       │          - sonnet-4-6 (čitanje dokumenata)
  │   python main.py      │
  │   polling, /data vol. │        Microsoft Graph API
  │                       │◀──────▶  SharePoint: braveldoo/sites/tendenzanova
  └─────────┬─────────────┘          BRAVEL/ (Excel, slike, backup)
            │ heartbeat + greške (HTTP, X-Monitor-Secret)
            ▼
  ┌───────────────────────┐
  │   bravel-monitor      │──────▶  Telegram alarm adminu
  │   (Fly.io, ams)       │
  │   python monitor.py   │
  │   :8080 /ingest (interno)
  └───────────────────────┘
```

---

## 2. GDJE ŠTO ŽIVI

### Fly.io aplikacije (organizacija: `personal`)
| App | Regija | VM | Volumen | Proces | Mreža |
|-----|--------|----|---------|--------|-------|
| **bravel-agent** | `ams` | shared-cpu-1x, 512 MB | `data` → `/data` | `python main.py` | polling (nema javnog porta) |
| **bravel-monitor** | `ams` | shared-cpu-1x, 256 MB | nema (ephemeral) | `python monitor.py` | `:8080` `/ingest` **samo interno** (`.internal`) |

- `bravel-agent`: konfiguracija u `fly.toml`. SQLite baza `/data/bot.db` živi na volumenu
  (preživi restart/redeploy).
- `bravel-monitor`: konfiguracija u `fly.monitor.toml`. **Nema volumen** → `monitor.db`
  je ephemeral (povijest grešaka se gubi na restart, ali alarmi rade uživo). Dostupan
  samo preko Fly privatne mreže (`http://bravel-monitor.internal:8080/ingest`), nema
  javni `fly.dev` ni `.flycast` (jer nema `[[services]]`).
- (Napomena: `bravel-flota-os` i `bravel-flota-os-api` postoje kao zasebni Fly appovi,
  ali NISU dio ovog repoa/sustava.)

### SharePoint
- Site: **`braveldoo.sharepoint.com/sites/tendenzanova`**
- Biblioteka: **„Zajednički dokumenti"** (koristi se default drive sajta; fajlovi se
  adresiraju po ASCII putanji, ne po imenu biblioteke — zbog hrvatskih znakova).
- Folder **`BRAVEL/`** sadrži:
  - `Racuni_terena.xlsx` — tablica **`Racuni`** (fiskalni računi)
  - `Primke_terena.xlsx` — tablica **`Primke`** (veleprodajne primke/otpremnice)
  - `Dokumenti_slike/` — originalne fotke dokumenata (`{vrsta}_{OIB}_{broj}_{datum}.jpg`)
  - `Backup/` — dnevni backupi baze (`bot_db_YYYY-MM-DD.db`, retencija 30 dana)

### GitHub
- Repo: **`github.com/Toni26946/Bravel-agent`**, glavna grana **`main`**.
- CI/CD: `.github/workflows/fly-deploy.yml` (deploy na push u `main`).

### Azure (Microsoft Entra) — app registracija za Graph
- App-only pristup (client credentials, MSAL). Kredencijali: `GRAPH_CLIENT_ID`,
  `GRAPH_TENANT_ID`, `GRAPH_CLIENT_SECRET`.
- Potrebna dozvola: **Application permission `Sites.ReadWrite.All`** + **admin consent**
  (omogućuje čitanje i pisanje fajlova).
- Naziv app registracije u Azureu: `[POPUNITI]` (traži po `GRAPH_CLIENT_ID`).

---

## 3. TAJNE (fly secrets) — samo imena i namjena, NE vrijednosti

> Ispis imena: `fly secrets list --app <app>` (prikazuje imena + digest, ne vrijednosti).

### `bravel-agent`
| Secret | Čemu služi |
|--------|-----------|
| `TELEGRAM_TOKEN` | Token glavnog Telegram bota (BotFather) |
| `ANTHROPIC_API_KEY` | Claude API ključ (Anthropic Console) |
| `GRAPH_CLIENT_ID` | Azure app (client) ID |
| `GRAPH_TENANT_ID` | Azure tenant (directory) ID |
| `GRAPH_CLIENT_SECRET` | Azure client secret — **ISTIČE ~07/2028** (vidi obnovu dolje) |
| `MONITOR_INGEST_URL` | URL monitorovog ingesta (`http://bravel-monitor.internal:8080/ingest`) |
| `MONITOR_SECRET` | Dijeljena tajna za `X-Monitor-Secret` (mora se poklapati s monitorom) |
| `FLY_TOKEN` | Fly API token na razini appa — **nije referenciran u kodu** (leftover; deploy koristi GitHub secret `FLY_API_TOKEN`, ne ovaj) |

- `ALLOWED_USERS` **nije** postavljen kao secret → koristi se hardkodirana lista u
  `main.py`: `[5191857104, 7599693099]`. Novog radnika dodaješ preko
  `fly secrets set ALLOWED_USERS=5191857104,7599693099,NOVI_ID --app bravel-agent`.

### `bravel-monitor`
| Secret | Čemu služi |
|--------|-----------|
| `MONITOR_BOT_TOKEN` | Token zasebnog monitor Telegram bota (šalje alarme adminu) |
| `MONITOR_SECRET` | Ista dijeljena tajna kao na agentu (**digest se mora poklapati**) |

- `MONITOR_ADMIN_ID` **nije** secret → default `7599693099` u `monitor.py` (Telegram chat
  id admina kome stižu alarmi).

### GitHub Actions secret (nije Fly secret)
| Secret | Čemu služi |
|--------|-----------|
| `FLY_API_TOKEN` | Fly deploy token za CI (GitHub → Settings → Secrets → Actions) |

### Gdje se koja tajna obnavlja
- **`GRAPH_CLIENT_SECRET` (istječe ~07/2028!)** — Azure Portal → *App registrations* →
  (app po `GRAPH_CLIENT_ID`) → *Certificates & secrets* → **New client secret** → kopiraj
  vrijednost → `fly secrets set GRAPH_CLIENT_SECRET=... --app bravel-agent`. Provjeri da
  je **admin consent** za `Sites.ReadWrite.All` i dalje odobren. Test: `graph_smoke.py`.
- **`ANTHROPIC_API_KEY` / krediti** — Anthropic Console (`console.anthropic.com`) →
  *Billing* (krediti) i *API Keys*. Ako krediti presuše, Claude vraća greške (u logu
  `[claude]` / monitor ERROR "Claude API greska"). Novi ključ → `fly secrets set
  ANTHROPIC_API_KEY=... --app bravel-agent`.
- **Telegram tokeni** — `@BotFather` na Telegramu (`/token` za regeneraciju). Nakon
  promjene: `fly secrets set TELEGRAM_TOKEN=... --app bravel-agent` (glavni bot) ili
  `MONITOR_BOT_TOKEN=... --app bravel-monitor` (monitor bot).
- **`MONITOR_SECRET`** — proizvoljan string, ali **mora biti isti** na oba appa. Promjena:
  postavi isti na `bravel-agent` i `bravel-monitor`.
- **`FLY_API_TOKEN` (GitHub)** — `fly tokens create deploy` → spremi u GitHub repo secrets.

> Napomena: postavljanje bilo kojeg fly secreta **restarta app** (novi release).

---

## 4. DEPLOY

### Pravilo: push na `main` → automatski deploy (glavni bot)
1. `git push origin main`
2. GitHub Actions (`fly-deploy.yml`) buildira Docker image, pusha ga u `registry.fly.io`
   i pokreće `flyctl deploy --app bravel-agent --image ...`.
3. **Auto-deploy vrijedi SAMO za `bravel-agent`.** Prati tijek u repo *Actions* tabu.

### Monitor se deploya ručno
`bravel-monitor` nema auto-deploy (isti Dockerfile/image, drugi proces):
```
fly deploy -c fly.monitor.toml
```

### Ručni deploy glavnog bota (samo iznimka)
Ako Actions ne radi ili treba hitno:
```
fly deploy --app bravel-agent
```
(Fly tada sam gradi image.) **Preferiraj push na `main`** — jedan izvor istine.

### Rollback
- **Preferirano (kroz Git):** `git revert <loš-commit>` → `git push origin main` → Actions
  redeploya prethodno stanje. Čist trag u historiji.
- **Brzo (bez rebuilda):** `fly releases --app bravel-agent` (vidi verzije/SHA) →
  `fly deploy --app bravel-agent --image registry.fly.io/bravel-agent:<stari-sha>`.
- **Restart bez promjene koda:** `fly apps restart bravel-agent` (ili restart pojedinog
  stroja, vidi §5).

---

## 5. DIJAGNOSTIKA

### Osnovne Fly komande
```
fly logs --app bravel-agent            # logovi uživo (glavni bot)
fly logs --app bravel-monitor          # logovi monitora
fly status --app bravel-agent          # strojevi, health, zadnji release
fly machine list --app bravel-agent    # popis strojeva (id, stanje)
fly machine restart <machine-id> --app bravel-agent
fly apps restart bravel-agent          # restart cijelog appa
fly ssh console --app bravel-agent     # shell unutar kontejnera
```

### Dijagnostičke skripte (samo čitaju, ne mijenjaju SharePoint)
```
fly ssh console -a bravel-agent -C "python graph_smoke.py"
```
→ provjeri Azure kredencijale i dozvole: token, site ID, drive ID, postoji li
`Racuni_terena.xlsx`. Kod `403` → nedostaje `Sites.ReadWrite.All` / admin consent.

```
fly ssh console -a bravel-agent -C "python table_debug.py"
```
→ ispiše STVARNO stanje Excel tablice preko Grapha (adresa/raspon, broj redaka,
usedRange) + openpyxl pogled. Koristi za dijagnozu praznih („duh") redaka.

Ručni backup baze (test): u Telegramu adminu → **`/backup_sada`** (okine odmah;
inače automatski svaki dan u 03:00 Europe/Zagreb, log prefiks `[backup]`).

### Značenje log prefiksa
| Prefiks | Što |
|---------|-----|
| `[startup]` | Pokretanje, popis registriranih handlera (redoslijed = prioritet matchanja) |
| `[monitoring]` | Stanje monitoring klijenta (`aktivno`/`neaktivno`, heartbeat URL) |
| `[graph]` | Svaki Graph HTTP poziv (metoda, path, status) + dohvat tokena |
| `[racuni]` | Obrada računa/primki: čitanje, dedupe, upis retka, spremanje slike |
| `[photo]` / `[document]` | Ulaz fotke / dokumenta u handler (prva linija = uvijek vidljiv dolazak) |
| `[backup]` | Dnevni backup baze: `OK bot_db_...` / `GREŠKA: ...`, retencija |
| `[DELETE]` | Brisanje podsjetnika (callback) |

Monitor alarmi stižu adminu (`MONITOR_ADMIN_ID`, default `7599693099`) preko monitor
bota. Naredbe monitora: `/greske [N]`, `/logovi [N]`, `/stats`, `/clear`, `/start`.

### Najčešći kvarovi i rješenja
- **409 „Conflict: terminated by other getUpdates request" (dupli polling)** — dvije
  instance bota istovremeno traže update (npr. dva Fly stroja, ili lokalno pokrenut bot
  dok Fly radi). → Osiguraj **jednu instancu**: `fly scale count 1 --app bravel-agent`;
  ne pokreći bota lokalno dok je Fly živ. (Na startu `delete_webhook(drop_pending_updates=True)`
  čisti zaostale update.)
- **423 lock (Excel fajl zaključan)** — netko drži `.xlsx` otvoren (Excel/SharePoint). Bot
  automatski retrya s backoffom (15/30/60/120/240 s) pa javi korisniku „🔒 fajl otvoren".
  → Zatvori fajl i ponovno pošalji fotku.
- **Prazni retci u tablici (POZNATA ZAMKA)** — prazan „duh" redak UNUTAR tablice
  (`Racuni_terena` / `Primke_terena`), tipično nakon ručnog brisanja retka u Excelu na
  krivi način. Dvije posljedice:
  1. **Graph API append dodaje nove retke tek ISPOD praznih** (na dno tablice) — podaci
     „preskoče" prazninu.
  2. **Excel HYPERLINK formulu u koloni „Slika" tretira kao izračunatu (calculated)
     kolonu** i sam je razvuče na sve prazne retke → lažni linkovi u praznim retcima.
  - **Rješenje:** prazne retke brisati **isključivo** preko desni klik → *Delete* →
    **Table Rows** (Izbriši retke tablice), NE brisati samo sadržaj ćelija (Delete/tipka
    Backspace) i NE koristiti „Clear Contents". Tablica **mora završavati zadnjim retkom
    s podacima** — ne ostavljati „rezervne" prazne retke ispod podataka.
  - Kod je otporan koliko može: upis popunjava **prvi prazan redak bilo gdje u tablici**
    (`append_or_fill_table_rows`), ali gornje pravilo brisanja i dalje vrijedi da se
    izbjegne razvučena HYPERLINK formula. Za provjeru stvarnog stanja: `table_debug.py`.
- **Deploy usred testa** — push na `main` tijekom testiranja pokrene redeploy i restart
  stroja: kratki prekid pollinga, monitor može javiti „bot zašutio" pa „oporavak".
  → Ne pushaj dok aktivno testiraš na produkciji.
- **`[monitoring] neaktivno`** — `MONITOR_INGEST_URL` nije postavljen na `bravel-agent`
  (trenutno JE postavljen). Ako se pojavi: provjeri secret i da monitor stroj radi.
- **Backup greška** — `[backup] GREŠKA: ...` i monitor ERROR „Backup nije uspio". Najčešće
  Graph/dozvole ili zaključan folder. Bot NASTAVLJA raditi; provjeri `graph_smoke.py`.

---

## 6. KONTAKTI / RAČUNI

> Popuni pristupe (tko ima login) gdje je `[POPUNITI]`.

| Servis | Identifikacija | Tko ima pristup |
|--------|---------------|-----------------|
| **Fly.io** | org `personal` | Toni (vlasnik); ostali: `[POPUNITI]` |
| **Anthropic Console** | `console.anthropic.com` (Claude API, billing) | `[POPUNITI e-mail/vlasnik]` |
| **Azure / Microsoft 365** | tenant `braveldoo` (`braveldoo.sharepoint.com`), app reg. za Graph | Global/App admin: `[POPUNITI]` |
| **GitHub** | `github.com/Toni26946/Bravel-agent` | `Toni26946` (vlasnik); suradnici: `[POPUNITI]` |
| **Telegram BotFather** | `@BotFather` (tokeni `TELEGRAM_TOKEN`, `MONITOR_BOT_TOKEN`) | Vlasnik botova: `[POPUNITI]` |
| **Meta Business** | `[POPUNITI — trenutno NIJE integrirano u kodu]` | `[POPUNITI]` |

### Ključne osobe / ID-evi (iz koda)
- Dozvoljeni korisnici bota (`ALLOWED_USERS`): `5191857104`, `7599693099`.
- Admin za monitor alarme (`MONITOR_ADMIN_ID`): `7599693099`.
- Vlasnik / glavni održavatelj: **Toni** — kontakt: `[POPUNITI]`.
- Zamjena / sekundarni kontakt: `[POPUNITI]`.
