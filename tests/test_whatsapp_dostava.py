# ============================================================
#  Testovi — statusi isporuke WhatsApp poruka (whatsapp_dostava).
#  Meta 200 ≠ isporučeno; neuspjeh stiže webhookom (status „failed").
#  Pokreni iz korijena repoa:  python -m unittest discover -s tests -v
# ============================================================
import unittest

import whatsapp_dostava as wd


def _value(mid, status, errors=None, rid="385911234567"):
    s = {"id": mid, "status": status, "recipient_id": rid}
    if errors is not None:
        s["errors"] = errors
    return {"statuses": [s]}


class TestDostava(unittest.TestCase):
    def setUp(self):
        wd._poslano.clear()

    def test_id_iz_odgovora(self):
        self.assertEqual(wd.id_iz_odgovora({"ok": True, "data": {"messages": [{"id": "wamid.A"}]}}), "wamid.A")
        self.assertIsNone(wd.id_iz_odgovora({"ok": False, "data": {"error": {}}}))

    def test_neuspjela_isporuka_naloga(self):
        wd.zapamti("wamid.A", "nalog vozaču Rai Sagar", "385911234567")
        n = wd.obradi_statuse(_value("wamid.A", "failed", [{"code": 131026, "title": "Message undeliverable"}]))
        self.assertEqual(len(n), 1)
        self.assertEqual(n[0]["opis"], "nalog vozaču Rai Sagar")
        self.assertIn("131026", n[0]["greska"])
        self.assertNotIn("385911234567", n[0]["maska"])       # broj nikad cijeli
        self.assertEqual(wd.stanje("wamid.A")["status"], "failed")
        txt = wd.poruka_vlasnicima(n)
        self.assertIn("NIJE isporučena", txt)
        self.assertIn("Rai Sagar", txt)

    def test_uspjesni_statusi_nisu_greska(self):
        wd.zapamti("wamid.B", "nalog vozaču X", "385911234567")
        self.assertEqual(wd.obradi_statuse(_value("wamid.B", "sent")), [])
        self.assertEqual(wd.obradi_statuse(_value("wamid.B", "read")), [])
        self.assertEqual(wd.obradi_statuse(_value("wamid.B", "delivered")), [])
        self.assertEqual(wd.stanje("wamid.B")["status"], "read")   # ne ide unatrag

    def test_nepoznata_poruka_i_los_ulaz(self):
        n = wd.obradi_statuse(_value("wamid.Z", "failed", [{"code": 131049}]))
        self.assertEqual(n[0]["opis"], "poruka")
        self.assertEqual(wd.obradi_statuse(None), [])
        self.assertEqual(wd.obradi_statuse({"messages": []}), [])

    def test_skupljac_jedna_poruka(self):
        poslano = []
        s = wd.Skupljac(poslano.append, odgoda_s=60)
        s.dodaj([{"opis": "a", "maska": "1", "greska": "x"}])
        s.dodaj([{"opis": "b", "maska": "2", "greska": "y"}])
        s._timer.cancel()
        s.isprazni()
        self.assertEqual(len(poslano), 1)
        self.assertIn("(2)", poslano[0])


if __name__ == "__main__":
    unittest.main()
