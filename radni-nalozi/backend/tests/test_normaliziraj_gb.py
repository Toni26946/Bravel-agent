"""Diktafon: hrvatski govor „tisuću tri" → „1.003" / „1.03" → GB „1003"."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai import normaliziraj_gb


def test_razdjelnik_tisucica():
    assert normaliziraj_gb("1.003") == "1003"
    assert normaliziraj_gb("1.03") == "1003"     # diktafon izgubi nulu
    assert normaliziraj_gb("1,013") == "1013"
    assert normaliziraj_gb("1 113") == "1113"


def test_tisucu_tri_kao_1_3():
    """„tisuću tri" → diktafon „1.3": bez popisa vozila 1003; s popisom bira postojeći."""
    assert normaliziraj_gb("1.3") == "1003"
    assert normaliziraj_gb("1.3", {"1003", "13"}) == "1003"
    assert normaliziraj_gb("1.3", {"13", "500"}) == "13"      # 1003 ne postoji → 13
    assert normaliziraj_gb("1.3", {"1300"}) == "1300"


def test_obicni_brojevi_ostaju():
    assert normaliziraj_gb("21") == "21"
    assert normaliziraj_gb("1003") == "1003"
    assert normaliziraj_gb("GB 348") == "348"
    assert normaliziraj_gb(None) is None
    assert normaliziraj_gb("") is None
