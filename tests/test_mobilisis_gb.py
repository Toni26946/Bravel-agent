# ============================================================
#  Testovi: GB se uzima iz NAZIVA vozila u Mobilisisu, ne iz registracije
#  (Toni 17.11.2026.: „fiksno gledaj samo gb").
#  Pokreni iz korijena repoa:  python -m unittest discover -s tests -v
# ============================================================

import unittest

import mobilisis as m


class TestGbIzNaziva(unittest.TestCase):
    def test_naziv_s_gb(self):
        self.assertEqual(m.gb_iz_teksta("DAF 406 Vinothkannan"), "406")
        self.assertEqual(m.gb_iz_teksta("MAN 42 Najam Agroburza"), "42")
        self.assertEqual(m.gb_iz_teksta("ACTROS 446 H Tharu"), "446")

    def test_registracija_nije_gb(self):
        for t in ("ZG1257HU", "ZG-5267-KM", "Š 303040", "MAN TGX 18.520", ""):
            self.assertIsNone(m.gb_iz_teksta(t), t)

    def test_naziv_prednost_pred_registracijom(self):
        uredaj = {"Id": 77, "Name": "ZG9464KR", "Description": "MAN 37 Novi vozač"}
        self.assertEqual(m.gb_iz_naziva(uredaj, {}), "37")

    def test_bez_gb_u_nazivu(self):
        self.assertIsNone(m.gb_iz_naziva({"Id": 5, "Name": "ZG1257HU"}, {"deviceId": 5}))


class TestVezaUredajGb(unittest.TestCase):
    """Uređaj jednom povezan s GB-om ostaje na tom GB-u i kad se ime (registracija) promijeni."""

    def setUp(self):
        import os
        import tempfile
        import gps_uredaji
        self.g = gps_uredaji
        self.tmp = tempfile.mkdtemp()
        self._stara = gps_uredaji._DATOTEKA
        gps_uredaji._DATOTEKA = os.path.join(self.tmp, "gps.json")
        gps_uredaji._veze = None
        self._orig = (m.get_devices, m.get_positions, m._get_map)

    def tearDown(self):
        self.g._DATOTEKA = self._stara
        self.g._veze = None
        m.get_devices, m.get_positions, m._get_map = self._orig

    def _pozicije(self, ime, reg2gb):
        m.get_devices = lambda: [{"Id": 9, "Name": ime, "raw": {"Id": 9, "Name": ime}}]
        m.get_positions = lambda: [{"deviceId": 9, "lat": 45.9, "lon": 16.2, "raw": {}}]
        m._get_map = lambda: ({}, reg2gb, [])
        return m.all_positions()

    def test_preregistracija_ne_mijenja_gb(self):
        self.assertEqual(self._pozicije("ZG5138FI", {"ZG5138FI": "37"})[0]["gb"], "37")
        # kamion preregistriran: novo ime, GARAŽNI BROJEVI ga još ne zna
        self.assertEqual(self._pozicije("ZG9464KR", {})[0]["gb"], "37")

    def test_rucna_veza_pobjeduje(self):
        self.g.zapamti("9", "491", "rucno")
        self.assertEqual(self._pozicije("ZG9704LH", {"ZG9704LH": "5"})[0]["gb"], "491")

    def test_odspajanje(self):
        self.g.zapamti("9", "491", "rucno")
        self.g.zapamti("9", "", "rucno")
        self.assertIsNone(self._pozicije("XX", {})[0]["gb"])


if __name__ == "__main__":
    unittest.main()
