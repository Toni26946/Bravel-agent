"""Uvoz cjenika nabavnih cijena iz „Kocka stanja": šifra se čita iz zadnje
(broj) zagrade, jedinična = |Stanje NC| / |Stanje robno|."""
import io
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from openpyxl import Workbook

from app.routers.integracije import _parse_kocka


def _xlsx(redovi) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["  ", "Prodajno mjesto", "Artikl", "JM", "Stanje robno", "Stanje NC"])
    for r in redovi:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_sifra_i_cijena():
    data = _xlsx([
        [None, "Ukupno", None, None, 7, 200.0],  # zbirni redak se preskače
        [None, "2 - Roba", "0W30 CASTROL START-STOP (4L) (20103)", "kom", 2, 17.20],
        [None, "2 - Roba", "10W40 MAGNATEC (D) (2111)", "kom", -5, -31.75],
        [None, "2 - Roba", "Artikl bez sifre", "kom", 3, 9.0],  # nema (broj) → preskače
    ])
    out = _parse_kocka("kocka stanja.xlsx", data)
    mapa = {o["sifra"]: o for o in out}
    assert set(mapa) == {20103, 2111}
    assert mapa[20103]["cijena"] == 8.6          # 17.20 / 2
    assert mapa[20103]["naziv"] == "0W30 CASTROL START-STOP (4L)"
    assert mapa[2111]["cijena"] == 6.35          # |−31.75| / |−5|


if __name__ == "__main__":
    test_parse_sifra_i_cijena()
    print("OK — cjenik parser")
