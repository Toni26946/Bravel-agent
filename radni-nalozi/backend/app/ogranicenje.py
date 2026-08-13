"""Jednostavno ograničavanje brzine (in-memory) za osjetljive rute — npr. prijavu.

Namjena je usporiti napade grubom silom (brute-force). Držano u memoriji procesa,
što je dovoljno za jednu instancu; za više instanci koristiti zajednički spremnik
(Redis) ili vanjski WAF.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# kljuc -> vremenske oznake (monotonic) nedavnih neuspjeha
_neuspjesi: dict[str, deque] = defaultdict(deque)

# Ograniči rast rječnika u dugotrajnom procesu.
_MAKS_KLJUCEVA = 10_000


def klijent_ip(request: Request) -> str:
    """Najbolji pokušaj dohvata IP-a klijenta iza reverse proxyja (Fly)."""
    fwd = request.headers.get("fly-client-ip") or request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "nepoznato"


def _pocisti(dq: deque, sada: float, prozor_s: int) -> None:
    while dq and sada - dq[0] > prozor_s:
        dq.popleft()


def provjeri(kljuc: str, maks: int, prozor_s: int) -> None:
    """Podigni 429 ako je za `kljuc` zabilježeno >= `maks` neuspjeha u prozoru."""
    sada = time.monotonic()
    dq = _neuspjesi.get(kljuc)
    if dq is None:
        return
    _pocisti(dq, sada, prozor_s)
    if len(dq) >= maks:
        cekaj = int(prozor_s - (sada - dq[0])) + 1
        raise HTTPException(
            status_code=429,
            detail="Previše neuspjelih pokušaja. Pokušajte ponovno za koju minutu.",
            headers={"Retry-After": str(max(cekaj, 1))},
        )


def zabiljezi_neuspjeh(kljuc: str, prozor_s: int) -> None:
    """Zabilježi neuspjeli pokušaj za `kljuc`."""
    sada = time.monotonic()
    if len(_neuspjesi) > _MAKS_KLJUCEVA:
        _neuspjesi.clear()
    dq = _neuspjesi[kljuc]
    _pocisti(dq, sada, prozor_s)
    dq.append(sada)


def ocisti(kljuc: str) -> None:
    """Očisti brojač nakon uspješne prijave."""
    _neuspjesi.pop(kljuc, None)
