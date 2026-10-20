"""Read a broker screenshot into holding rows."""

from __future__ import annotations

import base64
import json
import os

import requests

DEFAULT_URL = ""
DEFAULT_MODEL = ""
PROMPT = (
    "这是一张券商或基金持仓截图。只返回一个 JSON 对象，不要解释。"
    "格式: {\"holdings\":[{\"name\":\"\",\"symbol\":\"\",\"market\":\"cn|hk|us\","
    "\"mode\":\"shares|amount\",\"shares\":null,\"cost_price\":null,"
    "\"cost_amount\":null,\"market_amount\":null}]}。"
    "看得到股数或份额就用 shares，碎股保留小数。"
    "只看得到金额、没有份额时用 amount，cost_amount 是成本，market_amount 是当前市值。"
    "市场按人民币 cn、港币 hk、美元 us。看不清的数字留 null，不要编造。"
)


def vision_config() -> dict:
    url = os.getenv("VISION_API_URL", "").strip() or os.getenv("REFLEX_API_URL", "").strip() or DEFAULT_URL
    key = os.getenv("VISION_API_KEY", "").strip() or os.getenv("REFLEX_API_KEY", "").strip()
    model = os.getenv("VISION_MODEL", "").strip() or DEFAULT_MODEL
    return {"url": url.rstrip("/"), "key": key, "model": model}


def extract_holdings(text: str) -> list[dict]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    rows = data.get("holdings") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    cleaned = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        mode = "amount" if str(item.get("mode") or "") == "amount" else "shares"
        market = str(item.get("market") or "cn").lower()
        if market not in {"cn", "hk", "us"}:
            market = "cn"
        cleaned.append({
            "name": str(item.get("name") or "").strip()[:100],
            "symbol": str(item.get("symbol") or item.get("name") or "").strip()[:20],
            "market": market,
            "mode": mode,
            "shares": _num(item.get("shares")),
            "cost_price": _num(item.get("cost_price")),
            "cost_amount": _num(item.get("cost_amount")),
            "market_amount": _num(item.get("market_amount")),
        })
    return [row for row in cleaned if row["symbol"] or row["name"]]


def normalize_target(url: str, model: str) -> tuple[str, str]:
    blob = f"{url} {model}".lower().replace(" ", "")
    if "deepseek" in blob:
        return "https://api.deepseek.com", "deepseek-flash"
    return (url or "").strip(), (model or "").strip()


def complete_text(prompt: str, url: str = "", model: str = "", key: str = "") -> str:
    cfg = vision_config()
    target, chosen = normalize_target(url or cfg["url"], model or cfg["model"])
    secret = (key or cfg["key"]).strip()
    if not target or not chosen or not secret:
        raise RuntimeError("请填写接口地址、模型名称和密钥")
    return _post_chat(target, secret, chosen, [{"role": "user", "content": prompt}])


def extract_strategy(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("接口没有返回策略")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("接口返回的不是策略 JSON") from exc
    return {
        "name": str(data.get("name") or "未命名策略").strip()[:80],
        "symbol": str(data.get("symbol") or "").strip()[:20],
        "action": str(data.get("action") or "watch"),
        "conditions": data.get("conditions") or [],
    }


def _post_chat(base: str, key: str, model: str, messages: list) -> str:
    root = base.rstrip("/")
    url = root if root.endswith("/chat/completions") else root + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = requests.post(url, json={"model": model, "temperature": 0, "messages": messages}, headers=headers, timeout=90)
    except requests.RequestException as exc:
        raise RuntimeError(f"接口连不上：{exc.__class__.__name__}") from exc
    try:
        body = response.json()
    except Exception:
        raise RuntimeError((response.text or "接口没有返回 JSON")[:180])
    if response.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        message = ""
        if isinstance(err, dict):
            message = err.get("message") or ""
        raise RuntimeError(message or str(body)[:180])
    try:
        content = body["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(str(body)[:180]) from exc
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def read_screenshot(image: bytes, mime: str, agent_url: str = "", model_name: str = "", api_url: str = "", api_key: str = "") -> list[dict]:
    cfg = vision_config()
    base = (agent_url or "").rstrip("/")
    local = base.startswith("http://127.0.0.1") or base.startswith("http://localhost")
    if len(image) > 6_000_000:
        raise RuntimeError("截图请小于 6MB")
    encoded = base64.b64encode(image).decode("ascii")
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ],
    }]
    if local:
        text = _post_chat(base + "/v1" if not base.endswith("/v1") else base, "", model_name or "local", messages)
    else:
        target, chosen = normalize_target(api_url or cfg["url"], model_name or cfg["model"])
        secret = (api_key or cfg["key"]).strip()
        if not target or not chosen or not secret:
            raise RuntimeError("请填写接口地址、模型名称和密钥")
        text = _post_chat(target, secret, chosen, messages)
    return extract_holdings(text)


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
