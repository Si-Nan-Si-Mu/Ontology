"""本机调用 [wx-cli](https://github.com/jackwener/wx-cli)，仅建议在受信本地环境开启（见 WX_CLI_ENABLED）。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from typing import Any

from fastapi import HTTPException


def _wx_executable(command: str) -> str:
    c = command.strip() or "wx"
    base = c.split()[0]
    found = shutil.which(base)
    return found or base


def run_wx_json(
    *,
    wx_command: str,
    args: list[str],
    timeout_sec: int,
) -> Any:
    """执行 `wx <args>`，将 stdout 解析为 JSON。"""
    exe = _wx_executable(wx_command)
    cmd = [exe, *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail=f"未找到可执行文件: {exe}。请安装 wx-cli 并加入 PATH。",
        ) from e
    except subprocess.TimeoutExpired as e:
        raise HTTPException(status_code=504, detail=f"wx-cli 超时（{timeout_sec}s）") from e

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:2000]
        raise HTTPException(
            status_code=502,
            detail=f"wx-cli 退出码 {proc.returncode}: {err}",
        )

    raw = (proc.stdout or "").strip()
    if not raw:
        raise HTTPException(status_code=502, detail="wx-cli 无输出")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"wx-cli 输出非 JSON: {e}; 前 200 字符: {raw[:200]!r}",
        ) from e


def validate_export_chat_name(chat: str) -> str:
    chat = chat.strip()
    if not chat or len(chat) > 200:
        raise HTTPException(status_code=400, detail="会话名 chat 长度须在 1–200")
    if "\x00" in chat or chat.startswith("-"):
        raise HTTPException(status_code=400, detail="会话名 chat 含非法字符")
    if re.search(r"[\r\n]", chat):
        raise HTTPException(status_code=400, detail="会话名 chat 不可含换行")
    return chat


def fetch_sessions_json(*, wx_command: str, limit: int, timeout_sec: int) -> list[dict[str, Any]]:
    data = run_wx_json(
        wx_command=wx_command,
        args=["sessions", "--json", "-n", str(limit)],
        timeout_sec=timeout_sec,
    )
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and "sessions" in data:
        inner = data["sessions"]
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
    raise HTTPException(status_code=502, detail="wx sessions --json 结构非预期（应为数组或含 sessions 数组）")


def run_wx_export_json_with_retries(
    *,
    wx_command: str,
    chat_arg: str,
    limit: int,
    timeout_sec: int,
    attempts: int = 3,
) -> Any:
    """对 `wx export`：守护进程偶发忙/瞬时错误时，502 做短暂退避重试。"""
    args = ["export", chat_arg, "--format", "json", "-n", str(limit)]
    for attempt in range(attempts):
        try:
            return run_wx_json(wx_command=wx_command, args=args, timeout_sec=timeout_sec)
        except HTTPException as exc:
            if exc.status_code != 502 or attempt == attempts - 1:
                raise
            detail = str(exc.detail) if isinstance(exc.detail, str) else ''
            if '找不到' in detail or 'not found' in detail.lower():
                raise
            time.sleep(0.35 * (attempt + 1))


def export_chat_json(
    *,
    wx_command: str,
    chat: str,
    limit: int,
    timeout_sec: int,
) -> str:
    """调用 `wx export`；对单字母 ASCII 会话名，若首次失败则尝试大小写互换（sessions 与 export 标识偶有不一致）。"""
    chat = validate_export_chat_name(chat)
    alts: list[str] = [chat]
    if len(chat) == 1 and chat.isascii() and chat.isalpha():
        sc = chat.swapcase()
        if sc != chat:
            alts.append(sc)

    for c in alts:
        try:
            data = run_wx_export_json_with_retries(
                wx_command=wx_command,
                chat_arg=c,
                limit=limit,
                timeout_sec=timeout_sec,
            )
            if not isinstance(data, dict):
                raise HTTPException(status_code=502, detail="wx export --format json 根节点须为对象")
            return json.dumps(data, ensure_ascii=False)
        except HTTPException as exc:
            if exc.status_code == 502 and c != alts[-1]:
                continue
            raise
