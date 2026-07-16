# ============================================================
#  BENZINSKE - registar benzinskih lanaca/postaja koje Bravel koristi
#  + pracenje promjene cijena goriva (evidencija).
#
#  KONTEKST / OGRANICENJA (procitaj prije diranja scrapera):
#    - U Hrvatskoj NE postoji sluzbeni javni JSON API za cijene goriva.
#      Ministarstvo (mzoe-gor.hr / cijenegoriva.hr) drzi cijene centralno i
#      SVI lanci ondje moraju objavljivati, ali programski pristup nije
#      dokumentiran. Zato cijene skidamo scrapingom (HTML).
#    - AS24 i DKV su KARTICNE (B2B) mreze — cijena je ugovorna i NEMA javnog
#      cjenika po postaji. Za njih pratimo samo lokaciju/mrezu (cijena = None).
#    - Brebric je pojedinacna postaja (Lipovljani).
#    - Adria Oil, Shell, Petrol, Tifon su maloprodajni lanci s dnevnim
#      cijenama (javno, preko agregatora).
#
#  ARHITEKTURA:
#    - PROVIDERI: registar (naziv, tip, izvor cijena, goriva).
#    - _fetch(url): robustan HTTP (UA, timeout, retry) — koristi proxy iz okoline.
#    - _izvuci_cijene(text): GENERICKI ekstraktor (kljucna rijec goriva + najbliza
#      cijena). Best-effort dok se na produkciji (Fly) ne vidi stvarni HTML pa
#      se po potrebi zamijeni preciznim parserom po provideru.
#    - osvjezi_sve(): skine sve, u bazu upise SAMO promjene, vrati sazetak.
#    - trenutno(): snapshot za /api/benzinske (zadnja cijena + prethodna + promjena).
#    - probe(url): dijagnostika — dohvat + uzorak sadrzaja + nadjene cijene
#      (za validaciju s Fly-a; odatle vidimo je li stranica dostupna i kakav je HTML).
#
#  BAZA: SQLite (isti bot.db kao ostatak). setup(db_file) postavi putanju.
# ============================================================

import re
import time
import sqlite3
from datetime import datetime, timezone

import requests

import monitoring

# ---- Konfiguracija ----
_TIMEOUT = 20
_RETRIES = 2
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_DB_FILE = "bot.db"  # postavlja se preko setup()


# ============================================================
#  REGISTAR PROVIDERA / POSTAJA
#
#  tip:  'maloprodaja' -> javni dnevni cjenik (scrapamo cijene)
#        'kartica'     -> B2B kartica/mreza, cijena ugovorna (bez javnog cjenika)
#
#  cjenik_url: stranica s cijenama po kompaniji na agregatoru
#    cijene-goriva.autoportal.hr (podaci iz ministarskog izvora mzoe-gor.hr;
#    stranice su staticne pa ih parser cita). POTVRDENO s Fly-a (16.7.):
#    autoportal se razrjesava i parser hvata cijene; cijenegoriva.hr NE
#    (DNS 'Name or service not known'), nafta.hr vraca 200 ali bez cijena u HTML-u.
#  postaje_url: sluzbeni pretrazivac postaja (za lokacije).
#  goriva: koja goriva pratimo za taj lanac (nazivi se normaliziraju u ekstraktoru).
#
#  NAPOMENA o cijenama: autoportal prikazuje RASPON (min–max po postajama) i
#  varijante "sa aditivima/bez aditiva"; genericki ekstraktor uzima prvu cijenu
#  uz naziv goriva (donja granica / reprezentativna). Za pracenje PROMJENE je
#  dovoljno (dosljedno iz runda u rundu); nije nuzno cijena bas svake postaje.
#
#  SLUG: potvrdeni tifon-doo, adria-oil-doo. Za shell/petrol/brebric slug je
#  POGODAK — potvrdi /benzinske probe pa po potrebi ispravi.
# ============================================================

_AUTOPORTAL = "https://cijene-goriva.autoportal.hr"

PROVIDERI = [
    {
        "kljuc": "adria_oil",
        "naziv": "Adria Oil",
        "tip": "maloprodaja",
        "postaje_url": "https://www.adriaoil.hr/benzinske-postaje/",
        "cjenik_url": _AUTOPORTAL + "/adria-oil-doo",   # potvrđen slug
        "goriva": ["dizel", "eurosuper95", "lpg"],
    },
    {
        "kljuc": "tifon",
        "naziv": "Tifon",
        "tip": "maloprodaja",
        "postaje_url": "https://pretrazivacpostaja.tifon.hr/",
        "cjenik_url": _AUTOPORTAL + "/tifon-doo",   # potvrđen slug
        "goriva": ["dizel", "eurosuper95", "eurosuper100", "lpg"],
    },
    {
        "kljuc": "shell",
        "naziv": "Shell",
        "tip": "maloprodaja",
        "postaje_url": "https://find.shell.com/hr",
        "cjenik_url": _AUTOPORTAL + "/coral-croatia-doo",   # POGODAK (Shell = Coral Croatia) — potvrdi probe-om
        "goriva": ["dizel", "eurosuper95"],
    },
    {
        "kljuc": "petrol",
        "naziv": "Petrol",
        "tip": "maloprodaja",
        "postaje_url": "https://www.petrol.hr/na-putu/benzinske-postaje",
        "cjenik_url": _AUTOPORTAL + "/petrol-doo",   # POGODAK — potvrdi probe-om
        "goriva": ["dizel", "eurosuper95", "lpg"],
    },
    {
        "kljuc": "brebric",
        "naziv": "Brebrić (Lipovljani)",
        "tip": "maloprodaja",
        "postaje_url": "https://bp-brebric.hr/",
        "cjenik_url": _AUTOPORTAL + "/benzinska-pumpa-brebric-doo",   # potvrđen slug (-doo)
        "adresa": "Zagrebačka ulica 51B, Lipovljani",
        "goriva": ["dizel", "eurosuper95"],
    },
    {
        "kljuc": "as24",
        "naziv": "AS24 (TotalEnergies)",
        "tip": "kartica",
        "postaje_url": "https://www.as24.com/en/stations",
        "cjenik_url": None,   # B2B kartica — nema javnog cjenika po postaji
        "goriva": ["dizel"],
    },
    {
        "kljuc": "dkv",
        "naziv": "DKV Mobility",
        "tip": "kartica",
        "postaje_url": "https://www.dkv-mobility.com/en/services/dkv-station-finder/",
        "cjenik_url": None,   # B2B kartica — nema javnog cjenika po postaji
        "goriva": ["dizel"],
    },
]


def provider(kljuc):
    for p in PROVIDERI:
        if p["kljuc"] == kljuc:
            return p
    return None


# ==================== BAZA ====================

def setup(db_file):
    """Postavi putanju baze i kreiraj tablicu povijesti cijena."""
    global _DB_FILE
    _DB_FILE = db_file
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS benzinske_cijene (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT    NOT NULL,   -- kljuc iz PROVIDERI
                gorivo   TEXT    NOT NULL,   -- normaliziran naziv (dizel, eurosuper95…)
                cijena   REAL    NOT NULL,   -- €/l
                ts       REAL    NOT NULL,   -- unix timestamp (UTC)
                dan      TEXT    NOT NULL     -- 'YYYY-MM-DD' (za brzi upit)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bz_lookup "
            "ON benzinske_cijene (provider, gorivo, ts)"
        )
    _log(f"tablica benzinske_cijene spremna ({_DB_FILE})")


def _db():
    conn = sqlite3.connect(_DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _log(msg):
    print(f"[benzinske] {msg}", flush=True)


# ==================== HTTP ====================

def _fetch(url):
    """GET s UA/timeoutom i retryjem. Vrati (status_code, text) ili baci."""
    last = None
    for attempt in range(_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=_TIMEOUT,
                                headers={"User-Agent": _UA,
                                         "Accept-Language": "hr,en;q=0.8"})
            return resp.status_code, resp.text
        except requests.RequestException as e:
            last = e
            if attempt < _RETRIES:
                time.sleep(1 + attempt)
                continue
    raise RuntimeError(f"Mrežna greška ({url}): {last}")


# ==================== EKSTRAKCIJA CIJENA ====================

# Mapiranje kljucnih rijeci -> normaliziran naziv goriva. Redoslijed je bitan:
# specificnije prije opcenitog ("eurosuper 100" prije "eurosuper", "plavi" prije "dizel").
_GORIVO_KLJUC = [
    ("eurosuper100", ["eurosuper 100", "eurosuper100", "super 100", "bmb 100"]),
    ("eurosuper95",  ["eurosuper 95", "eurosuper95", "super 95", "bmb 95",
                      "eurosuper", "benzin"]),
    ("plavi_dizel",  ["plavi dizel", "plavi diesel", "plavo gorivo"]),
    ("dizel",        ["eurodizel", "eurodiesel", "euro dizel", "dizel", "diesel"]),
    ("lpg",          ["autoplin", "auto plin", "ukapljeni naftni plin", "lpg", "plin"]),
]

# Cijena goriva u HR: ~0,3–3,0 €/l, obicno 3 decimale ("1,452 €"), ponekad 2.
# VAZNO: trazimo SAMO broj iza kojeg stoji € (ili EUR) — to je vidljivi cjenik.
# Bez toga bi parser hvatao gole brojeve iz Next.js JSON blobova u <script>
# tagovima (npr. dizel=0.64) umjesto stvarnih cijena.
_CIJENA_RE = re.compile(r"(\d{1,2})[.,](\d{2,3})\s*(?:€|eur\b)", re.IGNORECASE)


def _norm_gorivo(tekst):
    """Vrati normaliziran kljuc goriva za dani tekst (ili None)."""
    t = tekst.lower()
    for kljuc, rijeci in _GORIVO_KLJUC:
        for r in rijeci:
            if r in t:
                return kljuc
    return None


def _parse_cijena(token_int, token_dec):
    """('1','452') -> 1.452, uz sanity provjeru raspona (0.3–3.0 €/l)."""
    try:
        val = float(f"{token_int}.{token_dec}")
    except ValueError:
        return None
    if 0.3 <= val <= 3.0:
        return round(val, 3)
    return None


def _ocisti_tekst(html):
    """HTML -> citljiv plain tekst. VAZNO: prvo izbaci <script>/<style> blokove
    (Next.js JSON, Google Tag Manager) jer sadrze gole brojeve koji zavaraju
    ekstraktor; tek onda skini tagove i entitete."""
    h = re.sub(r"(?is)<script\b.*?</script>", " ", html)
    h = re.sub(r"(?is)<style\b.*?</style>", " ", h)
    h = re.sub(r"<[^>]+>", " ", h)
    # Euro entitet -> znak € PRIJE brisanja ostalih entiteta (inace nestane).
    h = re.sub(r"&euro;|&#8364;|&#x20ac;", "€", h, flags=re.IGNORECASE)
    h = re.sub(r"&[a-z]+;|&#\d+;", " ", h)
    return re.sub(r"\s+", " ", h)


def _izvuci_cijene(text):
    """GENERICKI ekstraktor za autoportal.hr. Vrati {gorivo: cijena}.

    VAZNO — RASPORED: na autoportalu cijena stoji ISPRED naziva goriva, npr.
      '… 1,54€ - 1,64€  Eurosuper 95 sa aditivima  2,02€ - 2,10€  Eurosuper 100…'
    Dakle za svaki naziv goriva uzimamo cijenu(e) NEPOSREDNO PRIJE njega
    (donja granica raspona = 'od' cijena). Trazi se samo broj iza kojeg je €
    (vidljivi cjenik), a <script>/<style> su vec izbaceni u _ocisti_tekst.

    Stranice prikazuju RASPON (min–max) i varijante sa/bez aditiva — za pracenje
    PROMJENE je dosljedno i dovoljno; nije nuzno cijena bas svake postaje."""
    plain = _ocisti_tekst(text)
    low = plain.lower()

    out = {}
    for kljuc, rijeci in _GORIVO_KLJUC:
        for r in rijeci:
            idx = low.find(r)
            if idx == -1:
                continue
            # Prozor ~45 znakova PRIJE naziva goriva — ondje je pripadna cijena.
            prije = plain[max(0, idx - 45): idx]
            matches = list(_CIJENA_RE.finditer(prije))
            if matches:
                # Zadnje (najbliže nazivu) 1–2 cijene = raspon tog goriva; uzmi donju.
                vals = [_parse_cijena(m.group(1), m.group(2)) for m in matches[-2:]]
                vals = [v for v in vals if v is not None]
                if vals and kljuc not in out:
                    out[kljuc] = min(vals)
                    break  # nasli za ovo gorivo -> sljedeci tip
    return out


# ==================== OSVJEZAVANJE / POHRANA ====================

def _zadnja_cijena(conn, provider_kljuc, gorivo):
    row = conn.execute(
        "SELECT cijena FROM benzinske_cijene WHERE provider=? AND gorivo=? "
        "ORDER BY ts DESC LIMIT 1", (provider_kljuc, gorivo)).fetchone()
    return row["cijena"] if row else None


def _spremi_ako_promjena(provider_kljuc, cijene):
    """Za svako gorivo upisi red SAMO ako se cijena promijenila u odnosu na
    zadnju pohranjenu. Vrati listu promjena [(gorivo, stara, nova)]."""
    promjene = []
    now = datetime.now(timezone.utc)
    ts = now.timestamp()
    dan = now.strftime("%Y-%m-%d")
    with _db() as conn:
        for gorivo, nova in cijene.items():
            stara = _zadnja_cijena(conn, provider_kljuc, gorivo)
            if stara is not None and abs(stara - nova) < 0.0005:
                continue  # nema promjene
            conn.execute(
                "INSERT INTO benzinske_cijene (provider, gorivo, cijena, ts, dan) "
                "VALUES (?, ?, ?, ?, ?)", (provider_kljuc, gorivo, nova, ts, dan))
            promjene.append((gorivo, stara, nova))
    return promjene


def osvjezi_provider(p):
    """Skini i parsiraj cijene za jednog providera. Vrati dict:
      {'kljuc','naziv','tip','cijene':{...},'promjene':[...], 'greska':str|None}.
    Karticne mreze (bez cjenik_url) preskace (cijena ugovorna)."""
    rez = {"kljuc": p["kljuc"], "naziv": p["naziv"], "tip": p["tip"],
           "cijene": {}, "promjene": [], "greska": None}
    if not p.get("cjenik_url"):
        rez["greska"] = ("kartična mreža — nema javnog cjenika (cijena ugovorna)"
                         if p["tip"] == "kartica"
                         else "izvor cijena još nije postavljen (treba točan slug)")
        return rez
    try:
        status, text = _fetch(p["cjenik_url"])
        if status != 200:
            rez["greska"] = f"HTTP {status}"
            return rez
        cijene = _izvuci_cijene(text)
        # Zadrzi samo goriva koja pratimo za taj lanac (ako je popis zadan).
        prati = set(p.get("goriva") or [])
        if prati:
            cijene = {g: c for g, c in cijene.items() if g in prati}
        rez["cijene"] = cijene
        if not cijene:
            rez["greska"] = "cijene nisu pronađene u sadržaju (parser treba doradu)"
        else:
            rez["promjene"] = _spremi_ako_promjena(p["kljuc"], cijene)
    except Exception as e:
        rez["greska"] = str(e)
        monitoring.warning(f"Benzinske {p['kljuc']}: {e}", source="benzinske")
    return rez


def osvjezi_sve():
    """Osvjezi sve providere, vrati citljiv sazetak (str) + broj promjena."""
    linije = []
    ukupno_promjena = 0
    for p in PROVIDERI:
        r = osvjezi_provider(p)
        if r["cijene"]:
            dijelovi = ", ".join(f"{g}={c:.3f}" for g, c in sorted(r["cijene"].items()))
            oznaka = ""
            if r["promjene"]:
                ukupno_promjena += len(r["promjene"])
                oznaka = f"  ✏️ {len(r['promjene'])} promjena"
            linije.append(f"• {r['naziv']}: {dijelovi}{oznaka}")
        else:
            linije.append(f"• {r['naziv']}: — ({r['greska']})")
    zaglavlje = (f"⛽ Cijene goriva osvježene "
                 f"({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})\n"
                 f"Promjena zabilježeno: {ukupno_promjena}\n")
    return zaglavlje + "\n".join(linije), ukupno_promjena


# ==================== SNAPSHOT ZA API ====================

def _prethodne_dvije(conn, provider_kljuc, gorivo):
    """Zadnje dvije cijene (nova, prethodna) za promjenu. Vrati (row_new, row_prev)."""
    rows = conn.execute(
        "SELECT cijena, ts FROM benzinske_cijene WHERE provider=? AND gorivo=? "
        "ORDER BY ts DESC LIMIT 2", (provider_kljuc, gorivo)).fetchall()
    new = rows[0] if len(rows) >= 1 else None
    prev = rows[1] if len(rows) >= 2 else None
    return new, prev


def trenutno():
    """Snapshot svih providera za /api/benzinske. Vrati listu dictova:
      {kljuc, naziv, tip, postaje_url, adresa?, goriva:[
          {gorivo, cijena, valuta, prethodna, promjena, smjer, vrijeme}]}.
    smjer: 'gore'|'dolje'|'isto'|None. Vozila bez zabiljezene cijene -> prazna lista."""
    out = []
    with _db() as conn:
        for p in PROVIDERI:
            stavke = []
            for gorivo in (p.get("goriva") or []):
                new, prev = _prethodne_dvije(conn, p["kljuc"], gorivo)
                if not new:
                    continue
                cijena = new["cijena"]
                prethodna = prev["cijena"] if prev else None
                promjena = None
                smjer = None
                if prethodna is not None:
                    promjena = round(cijena - prethodna, 3)
                    smjer = ("gore" if promjena > 0 else
                             "dolje" if promjena < 0 else "isto")
                stavke.append({
                    "gorivo": gorivo,
                    "cijena": cijena,
                    "valuta": "EUR/l",
                    "prethodna": prethodna,
                    "promjena": promjena,
                    "smjer": smjer,
                    "vrijeme": datetime.fromtimestamp(
                        new["ts"], timezone.utc).isoformat(),
                })
            zapis = {
                "kljuc": p["kljuc"],
                "naziv": p["naziv"],
                "tip": p["tip"],
                "postaje_url": p.get("postaje_url"),
                "goriva": stavke,
            }
            if p.get("adresa"):
                zapis["adresa"] = p["adresa"]
            out.append(zapis)
    return out


# ==================== DIJAGNOSTIKA (probe) ====================

def probe(url):
    """Dohvati URL i vrati dijagnostiku: {url, status, duljina, nadjene_cijene, uzorak}.
    Sluzi da se S FLY-A vidi je li izvor dostupan i kakav je HTML (za pisanje
    preciznog parsera). Ne baca — greske vraca u 'greska'."""
    try:
        status, text = _fetch(url)
    except Exception as e:
        return {"url": url, "greska": str(e)}
    cijene = _izvuci_cijene(text)
    plain = _ocisti_tekst(text).strip()
    return {
        "url": url,
        "status": status,
        "duljina": len(text),
        "nadjene_cijene": cijene,
        "uzorak": plain[:600],
    }
