# Bravel Radni Nalozi

PWA aplikacija za **radne naloge servisa kamiona**. Vozači prijavljuju kvarove,
voditelj radionice iz prijave otvara radni nalog i dodjeljuje ga mehaničarima,
a mehaničari prate status, upisuju sate, dijelove i fotografije.

Zasebna aplikacija (vlastiti backend + baza), neovisna o Telegram/WhatsApp botu.

## Uloge i tok rada

| Uloga | Što radi |
|-------|----------|
| **Vozač** | Prijavljuje kvar (vozilo, opis, foto, hitnost). Vidi status svojih prijava. |
| **Voditelj** | Vidi sve prijave i naloge. Iz prijave otvara radni nalog, dodjeljuje radnicima, postavlja prioritet/rok, zatvara. Upravlja korisnicima i vozilima (šifrarnik). |
| **Radnik (mehaničar)** | Vidi samo naloge dodijeljene njemu. Mijenja status (otvoren → u radu → čeka dijelove → gotov), upisuje radne sate, ugrađene dijelove i foto. |

## Tehnologija

- **Backend:** Python, FastAPI, SQLAlchemy, JWT prijava, bcrypt. Baza: PostgreSQL (produkcija) ili SQLite (lokalno/zadano).
- **Frontend:** React + Vite, **PWA** (instalabilno na mobitel, offline cache, push obavijesti).
- **Deploy:** jedan Docker image — backend poslužuje i API (`/api`) i izgrađeni PWA (`/`).

## Struktura

```
radni-nalozi/
├── backend/          FastAPI aplikacija
│   ├── app/
│   │   ├── main.py, config.py, database.py, models.py, schemas.py, auth.py
│   │   ├── push.py, storage.py, seed.py
│   │   └── routers/  auth, korisnici, vozila, prijave, nalozi, push
│   └── requirements.txt
├── frontend/         React + Vite PWA
│   └── src/          api.js, auth.jsx, pages/…
├── Dockerfile        multi-stage build (frontend → backend)
└── fly.toml          fly.io konfiguracija
```

## Lokalno pokretanje

### Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # po potrebi uredi
uvicorn app.main:app --reload --port 8000
```
API na http://localhost:8000/api · dokumentacija na http://localhost:8000/docs

Pri prvom pokretanju kreira se početni voditelj (zadano `voditelj` / `bravel123` —
**promijeni lozinku**, mijenja se preko `SEED_ADMIN_*` u `.env`).

### Frontend
```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173 (proxy /api → :8000)
```

## Deploy na fly.io

```bash
cd radni-nalozi
fly launch --no-deploy        # ili koristi postojeći fly.toml
fly volumes create nalozi_data --size 1 --region ams
fly secrets set JWT_SECRET="$(openssl rand -hex 32)"
# (opcionalno, umjesto SQLite) fly secrets set DATABASE_URL="postgresql+psycopg2://…"
fly deploy
```

Aplikacija poslužuje PWA na korijenu domene — radnici otvore link i „Dodaj na
početni zaslon”.

## Push obavijesti (opcionalno)

Generiraj VAPID par i postavi tajne:
```bash
python -m py_vapid --gen        # ili bilo koji VAPID generator
fly secrets set VAPID_PUBLIC_KEY="…" VAPID_PRIVATE_KEY="…" VAPID_SUBJECT="mailto:info@bravel.hr"
```
Bez ovih ključeva aplikacija radi normalno, samo bez push obavijesti.

## API pregled

- `POST /api/auth/login` · `GET /api/auth/me`
- `GET/POST/PATCH /api/korisnici` (voditelj)
- `GET/POST/PATCH /api/vozila`
- `GET/POST /api/prijave`, `PATCH /api/prijave/{id}/status`
- `GET/POST/PATCH /api/nalozi`, `PATCH /api/nalozi/{id}/status`, `PUT /api/nalozi/{id}/dodjele`
- `POST /api/nalozi/{id}/sati|dijelovi|fotografije`
- `GET /api/push/kljuc` · `POST /api/push/pretplata`
