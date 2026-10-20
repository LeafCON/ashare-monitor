import unittest

from app.services.vision_holdings import extract_holdings


class VisionParseTests(unittest.TestCase):
    def test_amount_and_fractional_shares(self):
        text = """
        好的
        {"holdings":[
          {"name":"沪深300ETF","symbol":"510300","market":"cn","mode":"amount","cost_amount":10000,"market_amount":10880},
          {"name":"Apple","symbol":"AAPL","market":"us","mode":"shares","shares":0.25,"cost_price":180}
        ]}
        """
        rows = extract_holdings(text)
        self.assertEqual(rows[0]["mode"], "amount")
        self.assertEqual(rows[0]["market_amount"], 10880)
        self.assertEqual(rows[1]["shares"], 0.25)
