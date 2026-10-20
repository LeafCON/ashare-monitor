import os
import unittest

from app.agent.reflex import load_reflex
from app.routers.quant import condition_hit


class StrategyTests(unittest.TestCase):
    def test_all_conditions_must_pass(self):
        rules = [
            {"metric": "pe_ttm_pct", "op": "lte", "value": 20},
            {"metric": "roe", "op": "gte", "value": 15},
        ]
        self.assertTrue(condition_hit(rules, {"pe_ttm_pct": 12, "roe": 18}))
        self.assertFalse(condition_hit(rules, {"pe_ttm_pct": 12, "roe": 10}))
        self.assertFalse(condition_hit(rules, {"pe_ttm_pct": 12}))

    def test_local_mode_ignores_an_api_key(self):
        saved = {key: os.environ.get(key) for key in ("REFLEX_MODE", "JEV_API_KEY", "REFLEX_API_KEY", "LLAMA_SERVER_URL")}
        os.environ["REFLEX_MODE"] = "local"
        os.environ["JEV_API_KEY"] = "secret"
        os.environ["REFLEX_API_KEY"] = "secret"
        os.environ["LLAMA_SERVER_URL"] = "http://127.0.0.1:1"
        try:
            self.assertEqual(load_reflex().backend, "local_calibrated")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_api_mode_without_a_key_waits(self):
        saved = {key: os.environ.get(key) for key in ("REFLEX_MODE", "JEV_API_KEY", "REFLEX_API_KEY")}
        os.environ["REFLEX_MODE"] = "api"
        os.environ.pop("JEV_API_KEY", None)
        os.environ.pop("REFLEX_API_KEY", None)
        try:
            self.assertEqual(load_reflex().backend, "api_unconfigured")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
