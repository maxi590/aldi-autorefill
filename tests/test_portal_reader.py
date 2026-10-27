import unittest

from portal_reader import is_portal_host, parse_portal_text


class PortalReaderTests(unittest.TestCase):
    def test_real_hosts_only(self):
        self.assertTrue(is_portal_host("https://alditalk-kundenportal.de/"))
        self.assertTrue(is_portal_host("service.alditalk-kundenportal.de"))
        self.assertFalse(is_portal_host("alditalk-kundenportal.de.example.com"))

    def test_german_decimal(self):
        self.assertEqual(
            parse_portal_text("Testwert Noch 1,01 GB von 5 GB Inland +1 GB").remaining_mb,
            1010,
        )

    def test_rejects_roaming(self):
        self.assertIsNone(
            parse_portal_text("Noch 3,6 GB von 3,6 GB +1 GB Roaming EU").remaining_mb
        )

    def test_generic_reference_shape(self):
        self.assertEqual(
            parse_portal_text("Testwert Noch 950 MB von 5000 MB +1 GB").remaining_mb,
            950,
        )


if __name__ == "__main__":
    unittest.main()
