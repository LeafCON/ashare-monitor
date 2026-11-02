"""Work the desktop app cannot finish: a skill for an installed agent, and a prompt for the configured API."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from .research import public_facts

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / ".cursor" / "skills" / "market-research" / "SKILL.md"

PROMPT = """请先阅读并遵守本项目 .cursor/skills/market-research/SKILL.md，再做研究。软件自己只提供下面「已核实」列表里的数字。没有列出的数字一律写未取得，不要编造。

已核实：
{facts}

请完成：
1. 用 BTC、ETH 的趋势、主导地位、稳定币流动性、资金费率、持仓量和宏观，判断当前是 trending、mean_reverting、high_vol 还是 crisis，并写出会推翻这个判断的证据。
2. 只有在你能引用真实来源和日期时，才列出 5 到 10 个价格与基本面、采用或催化剂脱节的标的。每个写清：已确认与猜测、价值是否回到代币、空头理由、什么证据会证伪、成本和滑点会不会吃掉优势。
3. 不要下单，也不要放宽软件里 15% 回撤、5% 当日亏损、10% 仓位和急停开关。
4. 最后一节标题必须是 WHAT COULD I BE WRONG ABOUT?
"""


def _facts_block() -> str:
    rows = public_facts()
    if not rows:
        return "（这次没有从公开接口拿到任何数字）"
    lines = []
    for row in rows:
        if row.get("missing"):
            lines.append(f"- {row['name']}：未取得（{row['source']}）")
        else:
            lines.append(f"- {row['name']}：{row['value']}（{row['source']}，{row['as_of']}）")
    return "\n".join(lines)


def prompt_text() -> str:
    return PROMPT.format(facts=_facts_block())


def find_agents() -> list[dict]:
    import shutil
    found = []
    for name, exe in (
        ("Claude", "claude"),
        ("Codex", "codex"),
        ("Gemini", "gemini"),
        ("OpenCode", "opencode"),
        ("Aider", "aider"),
        ("Agent", "agent"),
        ("Cursor", "cursor"),
    ):
        path = shutil.which(exe) or shutil.which(exe + ".cmd") or shutil.which(exe + ".exe")
        if path:
            found.append({"name": name, "exe": path})
    return found


def status() -> dict:
    found = find_agents()
    return {
        "skill": ".cursor/skills/market-research/SKILL.md",
        "skill_ready": SKILL.is_file(),
        "agents": [item["name"] for item in found],
        "running": _state["running"],
        "items": [
            "行情阶段：BTC 与 ETH 趋势、主导地位、稳定币流动性、资金费率、持仓量、宏观和叙事轮动",
            "5 到 10 个价格与基本面、采用或即将发生的催化剂脱节的标的",
            "每个标的的供给、解锁、收入、费用、TVL、活跃用户、持仓集中度，以及价值是否回到代币",
            "已确认的催化剂和猜测分开写",
            "每个判断都写空头理由",
            "写清什么证据会证伪",
            "成本和滑点会不会吃掉优势，硬限制是否仍在代码里而不是交给模型",
            "最后一节写 WHAT COULD I BE WRONG ABOUT",
        ],
    }


_state = {"running": False, "text": "", "detail": "", "agent_id": ""}


def _command(agent: dict, instruction: str) -> list[str]:
    exe = agent["exe"]
    name = agent["name"]
    if name == "Cursor":
        return [exe, "agent", "-p", instruction, "--workspace", str(ROOT), "--trust"]
    if name == "Codex":
        return [exe, "exec", instruction]
    if name == "Aider":
        return [exe, "--message", instruction]
    if name == "OpenCode":
        return [exe, "run", instruction]
    return [exe, "-p", instruction]


def _launch() -> None:
    agents = find_agents()
    if not agents:
        _state["running"] = False
        _state["detail"] = "这台电脑上没有找到可以拉起的 agent。"
        return
    agent = agents[0]
    task = ROOT / "data" / "research-task.md"
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text(prompt_text(), encoding="utf-8")
    instruction = "请先阅读并遵守 .cursor/skills/market-research/SKILL.md，再按 data/research-task.md 完成研究。不要编造数字。"
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    cmd = _command(agent, instruction)
    if cmd[0].lower().endswith((".cmd", ".bat")):
        cmd = ["cmd.exe", "/c", *cmd]
    try:
        subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags)
    except Exception as exc:
        _state["running"] = False
        _state["detail"] = str(exc)[:300]
        return
    _state["detail"] = f"已拉起 {agent['name']}。"
    _state["running"] = False
    _save(agent["name"], _state["detail"])


def run_agent() -> dict:
    if _state["running"]:
        return {"ok": True, "launched": True, "running": True, "detail": "agent 已在启动。"}
    agents = find_agents()
    if not agents:
        return {"ok": False, "detail": "这台电脑上没有找到可以拉起的 agent。"}
    _state["running"] = True
    _state["text"] = ""
    _state["detail"] = f"正在拉起 {agents[0]['name']}。"
    threading.Thread(target=_launch, name="research-agent", daemon=True).start()
    return {"ok": True, "launched": True, "agent": agents[0]["name"], "detail": _state["detail"]}


def run_api() -> dict:
    from ..services.vision_holdings import complete_text
    try:
        text = complete_text(prompt_text())[:4000]
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:300]}
    _save("api", text)
    return {"ok": True, "agent": "api", "text": text}


def _save(agent: str, text: str) -> None:
    path = ROOT / "data" / "agent_research.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "agent": agent, "text": text}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
