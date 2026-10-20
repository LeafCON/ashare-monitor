"""GGUF files already downloaded on this machine."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "models"


def list_local_models() -> list[dict]:
    if not MODELS.is_dir():
        return []
    rows = []
    for path in sorted(MODELS.glob("*.gguf")):
        if not path.is_file():
            continue
        rows.append({
            "file": path.name,
            "label": _label(path.stem),
            "bytes": path.stat().st_size,
        })
    return rows


def model_path(file_name: str) -> Path | None:
    name = (file_name or "").strip()
    if not name or Path(name).name != name or not name.lower().endswith(".gguf"):
        return None
    path = MODELS / name
    if not path.is_file():
        return None
    return path


def llama_executable() -> str:
    found = shutil.which("llama-server") or shutil.which("llama-server.exe")
    if found:
        return found
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if not packages.is_dir():
        return ""
    matches = sorted(packages.glob("ggml.llamacpp*/llama-server.exe"))
    return str(matches[0]) if matches else ""


def _label(stem: str) -> str:
    text = stem.replace("_", "-")
    parts = text.split("-")
    if parts and parts[0].lower() == "qwen":
        parts[0] = "Qwen"
    return " ".join(part for part in parts if part)
