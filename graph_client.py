# ============================================================
#  GRAPH CLIENT - pristup SharePointu preko Microsoft Graph API
#  - Autentikacija: client credentials (app-only), MSAL
#    scope https://graph.microsoft.com/.default
#  - Token se kesira u memoriji do isteka (MSAL cache + tanak wrapper)
#  - Helperi: dohvat site/drive ID-a, download, upload, append retka
#    u Excel tablicu preko workbook API-ja
#
#  Napomena o hrvatskim znakovima: biblioteku "Zajednički dokumenti"
#  NE adresiramo po imenu (URL-encoding hrvatskih znakova je nezgodan).
#  Umjesto toga koristimo default drive sajta (/sites/{id}/drive), a
#  fajlove adresiramo po ASCII putanji (/root:/BRAVEL/ime.xlsx:).
#
#  Potrebne env varijable (fly secrets):
#    GRAPH_CLIENT_ID, GRAPH_TENANT_ID, GRAPH_CLIENT_SECRET
#  Azure app registracija: Application permission Sites.ReadWrite.All
#  + admin consent (omogucuje i citanje i PISANJE fajlova).
# ============================================================

import os
import threading

import requests

try:
    import msal
except ImportError:  # msal je opcionalan dok se ne konfigurira Graph
    msal = None

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
_SCOPE = ["https://graph.microsoft.com/.default"]
# (connect, read) timeout u sekundama - nijedan poziv ne smije visjeti
# ni na uspostavi veze ni na citanju odgovora.
_HTTP_TIMEOUT = (10, 30)

# ---- Konfiguracija sajta / lokacije fajlova ----
SITE_HOST = "braveldoo.sharepoint.com"
SITE_PATH = "/sites/tendenzanova"
FOLDER = "BRAVEL"  # folder unutar biblioteke "Zajednički dokumenti"

# ---- Kredencijali iz okoline ----
CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "").strip()
TENANT_ID = os.getenv("GRAPH_TENANT_ID", "").strip()
CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "").strip()


def _glog(msg):
    print(f"[graph] {msg}", flush=True)


class GraphError(Exception):
    """Greska pri komunikaciji s Graph API-jem. status_code je HTTP kod
    (ili None za mrezne/konfiguracijske greske)."""

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class _TimeoutSession(requests.Session):
    """requests.Session koja svakom pozivu namece default timeout.
    MSAL poziva token endpoint preko ove sesije pa auth vise NE MOZE
    visjeti zauvijek (MSAL sam ne postavlja timeout)."""

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", 30)
        return super().request(*args, **kwargs)


# ==================== AUTENTIKACIJA ====================

_app = None
_app_lock = threading.Lock()

# Kes za site/drive ID (rijetko se mijenjaju, drzimo ih do restarta).
# RLock (reentrant) da isti thread ne moze zablokirati sam sebe.
_ids = {"site": None, "drive": None}
_ids_lock = threading.RLock()


def is_configured():
    """True ako su svi Graph kredencijali postavljeni (i msal dostupan)."""
    return bool(CLIENT_ID and TENANT_ID and CLIENT_SECRET and msal)


def _get_app():
    global _app
    if _app is not None:
        return _app
    with _app_lock:
        if _app is None:
            if not is_configured():
                raise GraphError(
                    "Graph nije konfiguriran (nedostaju kredencijali ili msal).")
            authority = f"https://login.microsoftonline.com/{TENANT_ID}"
            _app = msal.ConfidentialClientApplication(
                client_id=CLIENT_ID,
                authority=authority,
                client_credential=CLIENT_SECRET,
                http_client=_TimeoutSession(),  # MSAL dobiva timeout
            )
    return _app


def _get_token():
    """Dohvati app-only token. MSAL sam kesira i vraca vazeci token dok
    ne istekne, pa ne moramo rucno pratiti expiry."""
    app = _get_app()
    _glog("token: pozivam MSAL acquire_token_for_client...")
    result = app.acquire_token_for_client(scopes=_SCOPE)
    if not result or "access_token" not in result:
        desc = (result or {}).get("error_description", "nepoznata greska")
        raise GraphError(f"Neuspjela autentikacija na Graph: {desc}")
    _glog("token: dobiven")
    return result["access_token"]


def ensure_token():
    """Eksplicitno pribavi token (koristi se za jasan 'auth' korak u logu)."""
    _get_token()


def _headers(extra=None):
    h = {"Authorization": f"Bearer {_get_token()}"}
    if extra:
        h.update(extra)
    return h


def _request(method, url, *, json=None, data=None, headers=None, stream=False):
    """Tanak wrapper oko requests koji dize GraphError na ne-2xx odgovor.
    Svaki poziv ima timeout i logira se (pocetak + status)."""
    short = url.replace(GRAPH_ROOT, "")
    _glog(f"HTTP {method} {short} ...")
    hdrs = _headers(headers)  # ovo moze pozvati MSAL (token) - logira se zasebno
    try:
        resp = requests.request(
            method, url,
            headers=hdrs,
            json=json,
            data=data,
            stream=stream,
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as e:
        _glog(f"HTTP {method} {short} MREZNA GRESKA: {e}")
        raise GraphError(f"Mrezna greska prema Graphu: {e}")
    _glog(f"HTTP {method} {short} -> {resp.status_code}")

    if resp.status_code < 200 or resp.status_code >= 300:
        # Pokusaj izvuci poruku iz Graph JSON greske
        detail = ""
        try:
            body = resp.json()
            detail = body.get("error", {}).get("message", "")
        except Exception:
            detail = (resp.text or "")[:300]
        raise GraphError(
            f"Graph {method} {url} -> {resp.status_code}: {detail}",
            status_code=resp.status_code,
        )
    return resp


# ==================== SITE / DRIVE ====================

def get_site_id():
    """Dohvati (i kesiraj) ID SharePoint sajta preko host+path adrese.
    Mrezni poziv je IZVAN locka; lock se drzi samo za upis u kes — tako se
    lock ne drzi preko I/O niti se ugnjezduje (nema deadlocka)."""
    if _ids["site"]:
        return _ids["site"]
    _glog("site: dohvacam site ID")
    url = f"{GRAPH_ROOT}/sites/{SITE_HOST}:{SITE_PATH}"
    data = _request("GET", url).json()
    with _ids_lock:
        _ids["site"] = data["id"]
    _glog(f"site: id={_ids['site']}")
    return _ids["site"]


def get_drive_id():
    """Dohvati (i kesiraj) ID default biblioteke sajta ("Zajednički
    dokumenti"). Site se rjesava PRIJE ulaska u lock (nema ugnijezdenog
    zakljucavanja); mrezni poziv izvan locka."""
    if _ids["drive"]:
        return _ids["drive"]
    site_id = get_site_id()  # rijesi site prvo (vlastiti, ne-ugnijezdeni lock)
    _glog("drive: dohvacam drive ID")
    url = f"{GRAPH_ROOT}/sites/{site_id}/drive"
    data = _request("GET", url).json()
    with _ids_lock:
        _ids["drive"] = data["id"]
    _glog(f"drive: id={_ids['drive']}")
    return _ids["drive"]


def _item_path(filename):
    """Graph 'path addressing' do fajla u BRAVEL folderu. Folder i ime su
    ASCII pa je adresa sigurna bez rucnog URL-encodinga."""
    return f"/root:/{FOLDER}/{filename}"


# ==================== FAJLOVI ====================

def file_exists(filename):
    """True ako fajl postoji u BRAVEL folderu, False ako 404, GraphError
    inace."""
    drive_id = get_drive_id()
    url = f"{GRAPH_ROOT}/drives/{drive_id}{_item_path(filename)}"
    try:
        _request("GET", url)
        return True
    except GraphError as e:
        if e.status_code == 404:
            return False
        raise


def get_item_id(filename):
    """DriveItem ID fajla (potreban za workbook API)."""
    drive_id = get_drive_id()
    url = f"{GRAPH_ROOT}/drives/{drive_id}{_item_path(filename)}"
    return _request("GET", url).json()["id"]


def download_file(filename):
    """Vrati sadrzaj fajla kao bytes."""
    drive_id = get_drive_id()
    url = f"{GRAPH_ROOT}/drives/{drive_id}{_item_path(filename)}:/content"
    resp = _request("GET", url, stream=True)
    return resp.content


def upload_file(filename, content_bytes):
    """Kreiraj ili zamijeni fajl (simple upload, za fajlove < 4 MB — nas
    Excel je sitan). Vraca metapodatke (ukljucujuci 'id')."""
    drive_id = get_drive_id()
    url = f"{GRAPH_ROOT}/drives/{drive_id}{_item_path(filename)}:/content"
    resp = _request(
        "PUT", url,
        data=content_bytes,
        headers={"Content-Type":
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    )
    return resp.json()


# ==================== EXCEL WORKBOOK API ====================

def append_table_row(filename, table_name, values):
    """Dodaj redak u imenovanu Excel tablicu preko workbook API-ja
    (bez download/upload cijelog fajla).

    values: lista vrijednosti (redoslijed = redoslijed kolona tablice).
            Graph umece kao JEDAN redak.
    Brojevi ostaju brojevi (JSON broj -> Excel broj), stringovi ostaju
    tekst.
    """
    item_id = get_item_id(filename)
    drive_id = get_drive_id()
    url = (f"{GRAPH_ROOT}/drives/{drive_id}/items/{item_id}"
           f"/workbook/tables/{table_name}/rows/add")
    body = {"values": [values]}  # [[...]] = jedan redak
    return _request("POST", url, json=body).json()
