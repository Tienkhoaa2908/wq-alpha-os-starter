import unittest

from wq_alpha_os.exporter import decode_payload, encode_payload, simulator_link


class ExporterTests(unittest.TestCase):
    def test_round_trip(self):
        expression = "rank(ts_rank(close, 252))"
        settings = {"region": "USA", "delay": 1}
        self.assertEqual(decode_payload(encode_payload(expression, settings)), {"expression": expression, "settings": settings})

    def test_url_is_browser_safe(self):
        url = simulator_link("rank(close)", {})
        self.assertTrue(url.startswith("https://platform.worldquantbrain.com/simulate?alpha_os="))
        self.assertNotIn("=", url.split("alpha_os=", 1)[1])


if __name__ == "__main__":
    unittest.main()
