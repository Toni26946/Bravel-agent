# ============================================================
#  Testovi — dispečerska „brava" vezana na IMENIK (Flota OS).
#
#  Cilj (zaključava ponašanje CILJA zadatka):
#    - whatsapp._dispecer_dozvoljen PROPUŠTA broj koji je u (mockiranom) Imeniku,
#      i kad ga NEMA na ručnoj allowlisti WHATSAPP_DISPECER_BROJEVI.
#    - FALLBACK: kad Imenik ne odgovara → propušta se SAMO ručna allowlista,
#      a broj koji bi bio samo u Imeniku je blokiran (ne otvara se slanje svima).
#    - imenik_flota.brojevi_mehanicara: filtrira RADIONA + aktivne, normalizira
#      broj (0/00/+ → 385…) i NIKAD ne baca (na HTTP/greški vrati prazan skup).
#
#  Bez mreže/baze: requests.get se mockira, env/keš se resetira po testu.
#  Pokreni iz korijena repoa:  python -m unittest discover -s tests -v
# ============================================================

import os
import unittest

import imenik_flota
import whatsapp


class _FakeResp:
    def __init__(self, status_code=200, data=None, boom=False):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self._boom = boom

    def json(self):
        if self._boom:
            raise ValueError("nije JSON")
        return self._data


def _reset_imenik():
    imenik_flota._cache_brojevi = None
    imenik_flota._cache_ts = 0.0


class _Baza(unittest.TestCase):
    """Čuva/obnavlja env i keš Imenika oko svakog testa."""

    _ENV = ("WHATSAPP_DISPECER_BROJEVI", "IMENIK_KLJUC", "FLOTA_OS_API_URL")

    def setUp(self):
        self._spremljeno = {k: os.environ.get(k) for k in self._ENV}
        self._orig_get = imenik_flota.requests.get
        _reset_imenik()

    def tearDown(self):
        imenik_flota.requests.get = self._orig_get
        for k, v in self._spremljeno.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _reset_imenik()

    def _mock_imenik(self, zapisi, status_code=200):
        os.environ["IMENIK_KLJUC"] = "test-kljuc"
        imenik_flota.requests.get = lambda *a, **k: _FakeResp(status_code, {"zapisi": zapisi})

    def _mock_imenik_pad(self):
        os.environ["IMENIK_KLJUC"] = "test-kljuc"

        def _boom(*a, **k):
            raise RuntimeError("Flota ne odgovara")

        imenik_flota.requests.get = _boom


class TestBrojeviMehanicara(_Baza):
    def test_filtrira_radionu_i_aktivne_i_normalizira(self):
        self._mock_imenik([
            {"ime": "Kovač Marko", "broj": "0994396448", "odjel": "RADIONA", "aktivan": True},
            {"ime": "Vozač Ivan", "broj": "0981112223", "odjel": "VOZACI", "aktivan": True},
            {"ime": "Bivši Mehaničar", "broj": "0995556667", "odjel": "RADIONA", "aktivan": False},
            {"ime": "Strani", "broj": "00385915554443", "odjel": "radiona", "aktivan": True},
        ])
        brojevi = imenik_flota.brojevi_mehanicara()
        # Marko (RADIONA, aktivan) i Strani (radiona, 00385…) prolaze; vozač i
        # neaktivni ne. Normalizacija: 0994… → 385994…, 00385… → 385…
        self.assertIn("385994396448", brojevi)
        self.assertIn("385915554443", brojevi)
        self.assertNotIn("385981112223", brojevi)   # vozač (krivi odjel)
        self.assertNotIn("385995556667", brojevi)   # neaktivan
        self.assertEqual(len(brojevi), 2)

    def test_na_gresci_ne_baca_i_vraca_prazno(self):
        self._mock_imenik_pad()
        # Ne smije baciti; bez poznatog keša → prazan skup.
        self.assertEqual(imenik_flota.brojevi_mehanicara(), frozenset())

    def test_bez_kljuca_ne_baca_i_vraca_prazno(self):
        os.environ.pop("IMENIK_KLJUC", None)
        self.assertEqual(imenik_flota.brojevi_mehanicara(), frozenset())


class TestDispecerDozvoljen(_Baza):
    def test_broj_iz_imenika_prolazi_bez_rucne_allowliste(self):
        os.environ.pop("WHATSAPP_DISPECER_BROJEVI", None)   # ručni popis prazan
        self._mock_imenik([
            {"ime": "Kovač Marko", "broj": "0994396448", "odjel": "RADIONA", "aktivan": True},
        ])
        # Broj dolazi normaliziran (kao iz handle_vozac_nalog): 385…
        self.assertTrue(whatsapp._dispecer_dozvoljen("385994396448"))
        # Broj koji nije u Imeniku ni na ručnom popisu → blokiran.
        self.assertFalse(whatsapp._dispecer_dozvoljen("385911111111"))

    def test_fallback_na_rucni_popis_kad_imenik_padne(self):
        os.environ["WHATSAPP_DISPECER_BROJEVI"] = "385111222333"
        self._mock_imenik_pad()   # Imenik nedostupan
        # Ručni popis i dalje radi…
        self.assertTrue(whatsapp._dispecer_dozvoljen("385111222333"))
        # …ali se slanje NE otvara broju koji bi bio samo u (nedostupnom) Imeniku.
        self.assertFalse(whatsapp._dispecer_dozvoljen("385994396448"))

    def test_rucni_popis_je_override_uz_imenik(self):
        os.environ["WHATSAPP_DISPECER_BROJEVI"] = "385111222333"
        self._mock_imenik([
            {"ime": "Kovač Marko", "broj": "0994396448", "odjel": "RADIONA", "aktivan": True},
        ])
        self.assertTrue(whatsapp._dispecer_dozvoljen("385111222333"))   # ručni
        self.assertTrue(whatsapp._dispecer_dozvoljen("385994396448"))   # imenik


if __name__ == "__main__":
    unittest.main()
