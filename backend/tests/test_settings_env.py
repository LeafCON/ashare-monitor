import os
import unittest
from pathlib import Path

from app.services.env_store import apply_updates, hint


class EnvStoreTests(unittest.TestCase):
    def test_hint_keeps_only_the_last_four(self):
        self.assertEqual(hint(""), "")
        self.assertEqual(hint("abcd"), "••••")
        self.assertEqual(hint("secret-token-9876"), "••••9876")

    def test_apply_updates_preserves_comments_and_process_env(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# keep\nOTHER=1\nBINANCE_API_KEY=old-key\n", encoding="utf-8")
            os.environ.pop("BINANCE_API_KEY", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            apply_updates(
                {"BINANCE_API_KEY": "new-secret-1234", "TELEGRAM_CHAT_ID": "42"},
                path,
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("# keep", text)
            self.assertIn("OTHER=1", text)
            self.assertIn("BINANCE_API_KEY=new-secret-1234", text)
            self.assertIn("TELEGRAM_CHAT_ID=42", text)
            self.assertNotIn("old-key", text)
            self.assertEqual(os.environ["BINANCE_API_KEY"], "new-secret-1234")
            self.assertEqual(os.environ["TELEGRAM_CHAT_ID"], "42")
            os.environ.pop("BINANCE_API_KEY", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
