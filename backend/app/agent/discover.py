"""Find AI servers already running on this computer. Nothing here is specific to one machine."""

from __future__ import annotations

import json
import os
import urllib.request

from .local_models import list_local_models

_VISION_HINTS = ("vl", "vision", "llava", "moondream", "minicpm", "internvl", "bakllava")


def _local_json(url: str) -> dict | list | None:
    request = urllib.request.Request(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=3) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None


def _ollama_cli_models() -> list[str]:
    import shutil
    import subprocess
    exe = shutil.which("ollama") or shutil.which("ollama.exe")
    if not exe:
        local = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
        exe = local if os.path.isfile(local) else ""
    if not exe:
        return []
    try:
        done = subprocess.run([exe, "list"], capture_output=True, text=True, timeout=4, check=False)
    except Exception:
        return []
    names = []
    for line in (done.stdout or "").splitlines()[1:]:
        name = line.split()[0] if line.split() else ""
        if name and name.lower() != "name":
            names.append(name)
    return names


def _vision(names: list[str]) -> bool:
    text = " ".join(names).lower()
    return any(hint in text for hint in _VISION_HINTS)


def discover_agents() -> list[dict]:
    found = []
    llama = os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8091").rstrip("/")
    probes = [
        ("llama-server", llama, "openai"),
        ("Ollama", "http://127.0.0.1:11434", "ollama"),
        ("LM Studio", "http://127.0.0.1:1234", "openai"),
    ]
    seen = set()
    for name, base, kind in probes:
        if base in seen:
            continue
        seen.add(base)
        if kind == "ollama":
            body = _local_json(base + "/api/tags")
            models = [item.get("name", "") for item in (body or {}).get("models", []) if isinstance(item, dict)]
        else:
            body = _local_json(base + "/v1/models")
            data = (body or {}).get("data", []) if isinstance(body, dict) else []
            models = [item.get("id", "") for item in data if isinstance(item, dict)]
        if body is None and kind == "ollama":
            models = _ollama_cli_models()
            if not models:
                continue
            body = {"models": [{"name": name} for name in models]}
        elif body is None:
            continue
        found.append({
            "id": base,
            "name": name,
            "url": base,
            "models": [item for item in models if item][:8],
            "vision": _vision(models),
            "running": True,
        })
    for item in list_local_models():
        found.append({
            "id": "file:" + item["file"],
            "name": item["label"],
            "url": "",
            "models": [item["file"]],
            "vision": _vision([item["file"]]),
            "running": False,
            "bytes": item["bytes"],
        })
    return found
