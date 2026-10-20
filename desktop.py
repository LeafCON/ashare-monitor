"""Desktop window for the A-share monitor.

Double-click launches this file with pythonw.exe. It starts the local
service and opens its own window. It does not open a browser tab.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
LOG_PATH = ROOT / "data" / "desktop.log"
HOST = "127.0.0.1"
PORT = 8802


def _message(text: str, title: str = "股票监测台") -> None:
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=1) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _start_server():
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    import uvicorn
    from app.main import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="monitor-server", daemon=True)
    thread.start()
    return server


def _ensure_stdio() -> None:
    """pythonw.exe has no console, and uvicorn calls sys.stdout.isatty()."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _bind_file_drop(window) -> None:
    """WebView2 leaves dataTransfer.files empty. Paths arrive only after a native drop listener is registered."""
    from webview.dom import DOMEventHandler, _dnd_state

    def deliver(paths: list[str]) -> None:
        logging.info("native file drop: %s", len(paths))
        window.evaluate_js("window.__nativeDrop && window.__nativeDrop(%s)" % json.dumps(paths))

    def take_stored() -> list[str]:
        stored = list(_dnd_state.get("paths") or [])
        if not stored:
            return []
        _dnd_state["paths"] = []
        return [item[1] for item in stored if isinstance(item, (list, tuple)) and len(item) > 1 and item[1]]

    def handle(event):
        files = (event.get("dataTransfer") or {}).get("files") or []
        ready = [
            item.get("pywebviewFullPath")
            for item in files
            if isinstance(item, dict) and item.get("pywebviewFullPath")
        ]
        if ready:
            deliver(ready)
            return

        def wait_for_paths():
            for _ in range(25):
                found = take_stored()
                if found:
                    deliver(found)
                    return
                time.sleep(0.04)
            deliver([])

        threading.Thread(target=wait_for_paths, daemon=True).start()

    def setup():
        def bind():
            time.sleep(0.2)
            try:
                allow = DOMEventHandler(lambda _event: None, prevent_default=True)
                window.dom.document.on("dragover", allow)
                window.dom.document.on("drop", DOMEventHandler(handle, prevent_default=True))
                logging.info("native file drop ready")
            except Exception:
                logging.exception("native file drop failed")

        threading.Thread(target=bind, daemon=True).start()

    window.events.loaded += setup


def main() -> None:
    _ensure_stdio()
    _setup_logging()
    logging.info("desktop start")
    owned = False
    server = None
    try:
        if not _healthy():
            server = _start_server()
            owned = True
            for _ in range(40):
                if _healthy():
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("监测服务没有在 10 秒内启动，请查看 data\\desktop.log")

        import webview

        window = webview.create_window(
            "A股 / 港股 / 美股行情监测台",
            f"http://{HOST}:{PORT}/",
            width=1360,
            height=860,
            min_size=(1100, 720),
            text_select=True,
        )
        _bind_file_drop(window)
        webview.start(gui="edgechromium")
        logging.info("window closed")
        if owned and server is not None:
            server.should_exit = True
    except Exception as exc:
        logging.exception("desktop failed")
        _message(f"{exc}\n\n详细日志：{LOG_PATH}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        _setup_logging()
        logging.error(traceback.format_exc())
        _message(traceback.format_exc())
