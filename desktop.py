"""Desktop window for the A-share monitor.

Double-click launches this file with pythonw.exe. It starts the local
service and opens its own window. It does not open a browser tab.
"""

from __future__ import annotations

import ctypes
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


def _message(text: str, title: str = "A股监测台") -> None:
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
            "A股行情监测台",
            f"http://{HOST}:{PORT}/",
            width=1360,
            height=860,
            min_size=(1100, 720),
            text_select=True,
        )
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
