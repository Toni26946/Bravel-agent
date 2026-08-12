"""Pretraga povijesti zamjene dijelova kroz sve kamione (voditelj)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, Uloga, ZamjenaDijela
from ..schemas import ZamjenaDijelaSVozilom

router = APIRouter(prefix="/dijelovi", tags=["dijelovi"])

samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)

# Normalizacija za pretragu: mala slova + bez hrvatskih kvačica.
# Tako "plocice" pronađe "Pločice", a "PLOČICE" pronađe "pločice"
# (jednako radi na SQLite i Postgresu, bez ovisnosti o bazi).
_MAPA = str.maketrans({
    "č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d",
    "Č": "c", "Ć": "c", "Š": "s", "Ž": "z", "Đ": "d",
})


def _norm(s: str) -> str:
    return (s or "").translate(_MAPA).lower()


@router.get("/pretraga", response_model=list[ZamjenaDijelaSVozilom])
def pretraga(
    q: str = Query(default=""),
    _: Korisnik = Depends(samo_voditelj),
    db: Session = Depends(get_db),
):
    upit = _norm(q.strip())
    rows = (
        db.query(ZamjenaDijela)
        .order_by(ZamjenaDijela.datum.desc(), ZamjenaDijela.id.desc())
        .all()
    )
    if upit:
        rows = [r for r in rows if upit in _norm(r.naziv)]
    return rows[:200]
