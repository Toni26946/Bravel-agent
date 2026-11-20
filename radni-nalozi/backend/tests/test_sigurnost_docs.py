"""Sigurnost (#349): /docs, /redoc i /openapi.json nisu javni; sigurnosna zaglavlja ostaju."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi.testclient import TestClient  # noqa: E402


def test_docs_nisu_javni_i_zaglavlja():
    from app.main import app
    c = TestClient(app)          # bez `with` → lifespan (migracije, pozadinske petlje) se ne pokreće
    for put in ("/docs", "/redoc", "/openapi.json"):
        r = c.get(put)
        # SPA fallback smije vratiti index.html (ako je frontend sastavljen), ali ne Swagger/shemu
        assert "swagger" not in r.text.lower() and '"openapi"' not in r.text, put
    r = c.get("/api/cartec/ping")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "max-age=" in r.headers.get("strict-transport-security", "")
