import json
import os
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AlertHistory, AlertSetting, MarketType
from app.routers.alerts import test_alert_send
from app.routers.settings import _grok_status
from app.services.alert_service import _emit, send_grok_bot_alert
from app.services.env_store import FIELDS

ENV_KEYS = (
    "ALERT_DRY_RUN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_THREAD_ID",
    "GROK_BOT_WEBHOOK_URL",
    "GROK_BOT_WEBHOOK_KEY",
    "GROK_BOT_ALERTS",
)
WEBHOOK = "https://hooks.example.test/grok"


class EnvIsolation(unittest.TestCase):
    def setUp(self):
        self._yaml = patch("app.services.alert_service._load_yaml", return_value={})
        self._hydrate = patch("app.services.env_store.hydrate_environ", lambda *args, **kwargs: None)
        self._yaml.start()
        self._hydrate.start()
        self._saved = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["ALERT_DRY_RUN"] = "false"

    def tearDown(self):
        self._yaml.stop()
        self._hydrate.stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def configure_grok(self, key: str = "test-key") -> None:
        os.environ["GROK_BOT_WEBHOOK_URL"] = WEBHOOK
        os.environ["GROK_BOT_WEBHOOK_KEY"] = key

    def configure_telegram(self) -> None:
        os.environ["TELEGRAM_BOT_TOKEN"] = "123:test"
        os.environ["TELEGRAM_CHAT_ID"] = "9"


class GrokBotAlertTests(EnvIsolation):
    def test_fields_mark_the_key_as_secret(self):
        self.assertEqual(FIELDS["grok_bot_webhook_url"], ("GROK_BOT_WEBHOOK_URL", False))
        self.assertEqual(FIELDS["grok_bot_webhook_key"], ("GROK_BOT_WEBHOOK_KEY", True))
        self.assertEqual(FIELDS["grok_bot_alerts"], ("GROK_BOT_ALERTS", False))

    def test_dry_run_does_not_post(self):
        os.environ["ALERT_DRY_RUN"] = "true"
        self.configure_grok()
        with patch("app.services.alert_service.requests.post") as post:
            sent = send_grok_bot_alert("hello", payload={"symbol": "600519.SS"})
        self.assertFalse(sent)
        post.assert_not_called()

    def test_missing_url_or_key_does_not_post(self):
        os.environ["GROK_BOT_WEBHOOK_KEY"] = "test-key"
        with patch("app.services.alert_service.requests.post") as post:
            self.assertFalse(send_grok_bot_alert("hello", force_live=True))
            os.environ["GROK_BOT_WEBHOOK_URL"] = WEBHOOK
            os.environ.pop("GROK_BOT_WEBHOOK_KEY")
            self.assertFalse(send_grok_bot_alert("hello", force_live=True))
        post.assert_not_called()

    def test_disabled_flag_skips_scheduled_send_but_not_force_live(self):
        self.configure_grok()
        os.environ["GROK_BOT_ALERTS"] = "false"
        response = Mock(status_code=200)
        with patch("app.services.alert_service.requests.post", return_value=response) as post:
            self.assertFalse(send_grok_bot_alert("hello"))
            post.assert_not_called()
            self.assertTrue(send_grok_bot_alert("hello", force_live=True))
        self.assertEqual(post.call_count, 1)

    def test_success_posts_structured_json(self):
        self.configure_grok()
        response = Mock(status_code=204)
        payload = {
            "symbol": "600519.SS",
            "name": "贵州茅台",
            "alert_type": "pct_change",
            "price": 1688.0,
            "change_pct": 1.2,
            "rule": "pct_change>=3",
            "group": "A股",
            "side": "sell",
        }
        with patch("app.services.alert_service.requests.post", return_value=response) as post:
            sent = send_grok_bot_alert("hello", payload=payload)
        self.assertTrue(sent)
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], WEBHOOK)
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        body = kwargs["json"]
        self.assertEqual(body["text"], "hello")
        self.assertEqual(body["message"], "hello")
        self.assertEqual(body["source"], "ashare-monitor")
        self.assertTrue(str(body["timestamp"]).endswith("+08:00"))
        for key, value in payload.items():
            self.assertEqual(body[key], value)

    def test_http_error_and_exception_return_false(self):
        self.configure_grok()
        with patch("app.services.alert_service.requests.post", return_value=Mock(status_code=500)) as post:
            self.assertFalse(send_grok_bot_alert("hello"))
        post.assert_called_once()
        with patch("app.services.alert_service.requests.post", side_effect=TimeoutError("slow")):
            self.assertFalse(send_grok_bot_alert("hello"))

    def test_settings_status_hides_the_key(self):
        self.configure_grok(key="secret-token-9876")
        status = _grok_status()
        self.assertEqual(status["url"], WEBHOOK)
        self.assertTrue(status["configured"])
        self.assertTrue(status["enabled"])
        self.assertIsNone(status["alerts"])
        self.assertEqual(status["key_hint"], "••••9876")
        self.assertNotIn("secret-token-9876", json.dumps(status))


class EmitAndTestSendTests(EnvIsolation):
    def setUp(self):
        super().setUp()
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine, expire_on_commit=False)()
        self.alert = AlertSetting(symbol="600519.SS", name="贵州茅台", market=MarketType.cn, enabled=True)
        self.db.add(self.alert)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def emit(self) -> None:
        _emit(self.db, self.alert, "pct_change", "pct_change>=3", 1688.0, 1.2, "sell", {}, False)

    def test_scheduled_dry_run_does_not_post(self):
        os.environ["ALERT_DRY_RUN"] = "true"
        self.configure_telegram()
        self.configure_grok()
        with patch("app.services.alert_service.requests.post") as post:
            self.emit()
        post.assert_not_called()
        row = self.db.query(AlertHistory).one()
        self.assertFalse(bool(row.sent))

    def test_sent_when_telegram_fails_and_grok_succeeds(self):
        self.configure_telegram()
        self.configure_grok()

        def side_effect(url, **kwargs):
            if "api.telegram.org" in url:
                raise RuntimeError("telegram down")
            return Mock(status_code=200)

        with patch("app.services.alert_service.requests.post", side_effect=side_effect) as post:
            self.emit()
        urls = [call.args[0] for call in post.call_args_list]
        self.assertTrue(any("api.telegram.org" in url for url in urls))
        grok_call = next(call for call in post.call_args_list if call.args[0] == WEBHOOK)
        body = grok_call.kwargs["json"]
        self.assertEqual(body["source"], "ashare-monitor")
        self.assertEqual(body["symbol"], "600519.SS")
        self.assertEqual(body["name"], "贵州茅台")
        self.assertEqual(body["alert_type"], "pct_change")
        self.assertEqual(body["price"], 1688.0)
        self.assertEqual(body["change_pct"], 1.2)
        self.assertEqual(body["rule"], "pct_change>=3")
        self.assertEqual(body["group"], "A股")
        self.assertEqual(body["side"], "sell")
        self.assertEqual(grok_call.kwargs["headers"]["Authorization"], "Bearer test-key")
        row = self.db.query(AlertHistory).one()
        self.assertTrue(bool(row.sent))

    def test_grok_failure_still_records_telegram_success(self):
        self.configure_telegram()
        self.configure_grok()

        def side_effect(url, **kwargs):
            if url == WEBHOOK:
                raise ConnectionError("webhook down")
            response = Mock(status_code=200)
            response.json.return_value = {"ok": True, "result": {"message_id": 7}}
            return response

        with patch("app.services.alert_service.requests.post", side_effect=side_effect):
            self.emit()
        row = self.db.query(AlertHistory).one()
        self.assertTrue(bool(row.sent))

    def test_disabled_grok_does_not_block_telegram(self):
        self.configure_telegram()
        self.configure_grok()
        os.environ["GROK_BOT_ALERTS"] = "false"

        def side_effect(url, **kwargs):
            response = Mock(status_code=200)
            response.json.return_value = {"ok": True, "result": {"message_id": 3}}
            return response

        with patch("app.services.alert_service.requests.post", side_effect=side_effect) as post:
            self.emit()
        urls = [call.args[0] for call in post.call_args_list]
        self.assertTrue(any("api.telegram.org" in url for url in urls))
        self.assertFalse(any(url == WEBHOOK for url in urls))
        self.assertTrue(bool(self.db.query(AlertHistory).one().sent))

    def test_live_send_allows_grok_without_telegram(self):
        os.environ["ALERT_DRY_RUN"] = "true"
        os.environ["GROK_BOT_ALERTS"] = "false"
        self.configure_grok()
        with patch("app.services.alert_service.requests.post", return_value=Mock(status_code=200)) as post:
            result = test_alert_send("live")
        self.assertTrue(result["sent"])
        self.assertFalse(result["telegram"]["configured"])
        self.assertFalse(result["telegram"]["sent"])
        self.assertTrue(result["grok_bot"]["configured"])
        self.assertFalse(result["grok_bot"]["enabled"])
        self.assertTrue(result["grok_bot"]["sent"])
        post.assert_called_once()
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["source"], "ashare-monitor")
        self.assertEqual(body["symbol"], "600519.SS")
        self.assertEqual(body["rule"], "test")
        self.assertEqual(body["group"], "A股")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")

    def test_live_send_without_either_channel(self):
        result = test_alert_send("live")
        self.assertFalse(result["sent"])
        self.assertIn("Telegram", result["detail"])
        self.assertIn("Grok Bot", result["detail"])
        self.assertFalse(result["telegram"]["configured"])
        self.assertFalse(result["grok_bot"]["configured"])
