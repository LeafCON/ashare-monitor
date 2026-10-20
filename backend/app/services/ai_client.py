"""Call any OpenAI-compatible chat API, including a local Ollama server."""

from __future__ import annotations

import os

import requests


def resolve_endpoint(url: str = "", model: str = "", key: str = "") -> tuple[str, str, str]:
    base = (url or os.getenv("AI_API_URL", "") or os.getenv("VISION_API_URL", "") or os.getenv("REFLEX_API_URL", "")).strip().rstrip("/")
    chosen = (model or os.getenv("AI_API_MODEL", "") or os.getenv("VISION_MODEL", "")).strip()
    secret = (key or os.getenv("AI_API_KEY", "") or os.getenv("VISION_API_KEY", "") or os.getenv("REFLEX_API_KEY", "")).strip()
    return base, chosen, secret


def chat(prompt: str, *, url: str = "", model: str = "", key: str = "", image_data_url: str = "") -> str:
    base, chosen, secret = resolve_endpoint(url, model, key)
    local = base.startswith("http://127.0.0.1") or base.startswith("http://localhost")
    if not base:
        raise RuntimeError("先选一个本机模型，或填写接口地址和模型名")
    if not local and not secret:
        raise RuntimeError("这个接口需要密钥")
    if not chosen:
        raise RuntimeError("请填写模型名")
    endpoint = base if base.endswith("/chat/completions") else base + "/v1/chat/completions"
    if base.endswith("/v1"):
        endpoint = base + "/chat/completions"
    content: str | list = prompt
    if image_data_url:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    response = requests.post(
        endpoint,
        json={"model": chosen, "temperature": 0, "messages": [{"role": "user", "content": content}]},
        headers=headers,
        timeout=120,
    )
    if response.status_code >= 400:
        detail = response.text[:180]
        try:
            detail = response.json().get("error", {}).get("message") or detail
        except Exception:
            pass
        raise RuntimeError(detail or "接口没有返回结果")
    body = response.json()["choices"][0]["message"]["content"]
    return body if isinstance(body, str) else str(body)
