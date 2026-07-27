# Detektor anomalija potrošnje goriva

Kako bot provjerava je li potrošnja goriva nekog kamiona anomalija (mogući
curenje / krađa / kvar). Cilj: kratka, pouzdana lista — a ne prijava pola flote.

## Postupak, korak po korak

### 1. Izračun potrošnje po kamionu (l/100km)
Za svaki kamion, po mjesecu, koristi se **vlasnikova metodologija s tank-korekcijom**:

```
potrošeno L = tank na početku + Σ utočeno (računi) − tank na kraju
l/100km     = potrošeno L ÷ (km ÷ 100)
```

Tank-korekcija sprječava da kamion koji zadnji dan u mjesecu natoči pun tank
ispadne proždrljiv (ili obrnuto). Izvor: točenja (`tocenja`) + km po danu
(`voznje_dan`) + očitanja tanka (sonda).

### 2. Gleda SAMO kamione
Uzimaju se samo vozila označena kao „KAMION" (stupac TIP u „GARAŽNI BROJEVI").
Laka vozila (kombi, auto, priključno) se izbacuju da ne kvare usporedbu.

### 3. Osobna povijest svakog kamiona — zadnjih 6 mjeseci
Svaki kamion se mjeri **protiv sebe**, ne protiv drugih kamiona. Broj mjeseci je
podesiv (param `mjeseci`, default 6).

### 4. Izbacivanje „prljavih" mjeseci
U računicu NE ulaze:
- mjeseci s **< 25 l/100km** — fizički nemoguće za natovaren kamion, znači da je
  gorivo pripisano krivom vozilu (kartica ≠ stvarni kamion);
- mjeseci s **< 1000 km** — premalo za pouzdan l/100km.

Kamion se ocjenjuje tek ako ima **barem 3 čista mjeseca**.

### 5. Provjera skoka (jedina anomalija)
- Izračuna se **medijan prethodnih čistih mjeseci** tog kamiona = njegov
  „uobičajeni" l/100km.
- Usporedi se sa **zadnjim čistim mjesecom**.
- Ako je zadnji mjesec **≥ 40 % iznad** uobičajenog → **🔴 nagli skok = anomalija**.

Primjer: GB 454 vozi ~34,9 l/100km pet mjeseci, pa mu zadnji mjesec skoči na
51,0 → **+46 %** → prijava.

## Što NAMJERNO NE radi (i zašto)
- **Ne uspoređuje s prosjekom flote.** Na stvarnim podacima kamioni prirodno idu
  35–67 l/100km, a pripis goriva ima ±30 % mjesečnog šuma. „Iznad prosjeka /
  statistički outlier" zato uvijek prijavi sve teške kamione (~25–30 od 120) —
  a oni samo rade svoj posao. Zato je ta usporedba maknuta.
- **Najveći potrošači** se prikazuju **zasebno, kao informacija** (nije problem —
  obično su to teški kamioni koji stalno troše više).

## Kako se vidi
- **`/gorivo`** (Telegram, owner) — provjera na zahtjev.
- **Tjedni auto-izvještaj** — ponedjeljak 07:00, javi vlasnicima **samo ako ima
  skokova** (bez tjednog šuma). Iza prekidača.
- **AI podrška** (chat u Flota OS-u) — kad tražiš „pregled poslovanja", uključi i
  ove skokove (alat `gorivo_anomalije`).

## Tehnički detalji

**Endpoint (Flota OS):** `GET /api/flota/gorivo-anomalije`
- `prag_svoj` (default 40) — koliki skok (%) vs vlastiti prosjek se broji;
- `mjeseci` (default 6) — koliko mjeseci osobne povijesti po kamionu;
- `min_km` (default 1000) — najmanje km da mjesec uđe u računicu;
- `svi` (default false) — `true` uključuje i ne-kamione.
- Odgovor: `{anomalije[], najveci[], fleet{median…}, pragovi{…}, ukupno_vozila}`.

**Kod:**
- Flota OS: `backend/app/potrosnja.py` → `anomalije()` (+ `izracunaj()`);
  endpoint u `backend/app/main.py`.
- bravel-agent: `main.py` → `_gorivo_tekst()` / `handle_gorivo` (`/gorivo`) i
  `_gorivo_auto()` (tjedni izvještaj, u petlji `check_reminders`).

**Prekidači (Fly secrets, bravel-agent) — tjedni izvještaj:**
- `GORIVO_ANOM_ON=1` — uključi tjedni izvještaj (default isključeno);
- `GORIVO_ANOM_DAN` / `GORIVO_ANOM_SAT` / `GORIVO_ANOM_MIN` — raspored
  (default pon 07:00);
- `GORIVO_ANOM_UVIJEK=1` — šalji i kad nema skokova (potvrda da radi).

**Ugađanje osjetljivosti:** prag skoka mijenja se preko `prag_svoj` (npr. 30 =
osjetljivije, 50 = strože), a duljina osobne baze preko `mjeseci`.

---
*Zadnja izmjena: 27.7.2026.*
