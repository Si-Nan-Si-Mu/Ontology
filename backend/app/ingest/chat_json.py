"""聊天 JSON 规范化：兼容 wx-cli 导出及常见通用结构。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

# Pydantic / API 中 ``limit``、``probe_message_limit`` 的硬上限（与配置可下调的「有效上限」不同）
ABSOLUTE_MESSAGE_LIST_CAP = 500_000

# 超大 messages 数组时，规范化按块遍历以降低单次循环占用（结果仍合并为全量一次分析）
_NORMALIZE_SLICE = 8_000


def wx_chat_import_max_messages() -> int:
    """单份导入允许的最大原始消息条数（来自 Settings，夹在 1000 与 ABSOLUTE_MESSAGE_LIST_CAP 之间）。"""
    from app.config import get_settings

    try:
        v = int(get_settings().wx_chat_import_max_messages)
    except (TypeError, ValueError):
        v = 100_000
    return max(1_000, min(ABSOLUTE_MESSAGE_LIST_CAP, v))


_CONTENT_KEYS = ("content", "text", "body", "message", "msg")
_SENDER_KEYS = ("sender", "from", "author", "name", "speaker", "user", "nickname")
_TIME_KEYS = ("time", "timestamp", "created_at", "date", "ts")


def _first_str(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = data.get(k)
        if v is None:
            continue
        if isinstance(v, str):
            s = v.strip()
            if s:
                return s
        elif isinstance(v, (int, float)):
            return str(v)
    return ""


def _normalize_message_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        if isinstance(item, str) and item.strip():
            return {"sender": "", "content": item.strip(), "time": ""}
        return None

    content = _first_str(item, _CONTENT_KEYS)
    if not content:
        return None

    sender = _first_str(item, _SENDER_KEYS)
    if not sender and item.get("role") is not None:
        sender = str(item.get("role", "")).strip()

    return {
        "sender": sender,
        "content": content,
        "time": _first_str(item, _TIME_KEYS),
    }


def _extract_messages_blob(data: Any) -> tuple[list[Any], str, bool, str]:
    """从多种根结构取出 messages 列表与 chat / is_group / format 标签。"""
    if isinstance(data, list):
        return data, "", False, "array_root"

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="根节点须为 JSON 对象或消息数组")

    if isinstance(data.get("messages"), list):
        chat = _first_str(data, ("chat", "title", "session", "conversation_id", "name"))
        is_group = bool(
            data.get("is_group")
            or str(data.get("chat_type", "")).lower() in ("group", "群", "group_chat")
        )
        return data["messages"], chat, is_group, "wx_cli"

    for key in ("conversation", "session", "data"):
        inner = data.get(key)
        if isinstance(inner, dict) and isinstance(inner.get("messages"), list):
            chat = _first_str(inner, ("chat", "title", "name")) or _first_str(data, ("chat", "title"))
            is_group = bool(inner.get("is_group") or data.get("is_group"))
            return inner["messages"], chat, is_group, f"nested_{key}"

    if isinstance(data.get("conversations"), list) and data["conversations"]:
        first = data["conversations"][0]
        if isinstance(first, dict) and isinstance(first.get("messages"), list):
            chat = _first_str(first, ("chat", "title", "name", "id"))
            is_group = bool(first.get("is_group"))
            return first["messages"], chat, is_group, "conversations[0]"

    if isinstance(data.get("records"), list):
        return data["records"], _first_str(data, ("chat", "title")), bool(data.get("is_group")), "records"

    raise HTTPException(
        status_code=400,
        detail="无法识别聊天 JSON：需要 messages 数组（wx-cli / 通用对话导出）",
    )


def normalize_chat_export(data: Any) -> dict[str, Any]:
    """规范为 ingest 使用的 {chat, is_group, messages, source_format}。

    超长 ``messages`` 按块调用 ``_normalize_message_item``，合并后仍是一次性全量列表，
    供 ``build_persona_digest`` 单次分析（不断开为多轮入库）。
    """
    raw_messages, chat, is_group, source_format = _extract_messages_blob(data)
    mx = wx_chat_import_max_messages()
    n_raw = len(raw_messages)
    if n_raw > mx:
        raise HTTPException(
            status_code=400,
            detail=(
                f"消息条数 {n_raw} 超过当前上限 {mx}（可在 backend/.env 设置 WX_CHAT_IMPORT_MAX_MESSAGES，"
                f"绝对上限 {ABSOLUTE_MESSAGE_LIST_CAP}），或缩小 wx export -n / 分段导出。"
            ),
        )

    messages: list[dict[str, Any]] = []
    for start in range(0, n_raw, _NORMALIZE_SLICE):
        chunk = raw_messages[start : start + _NORMALIZE_SLICE]
        for item in chunk:
            norm = _normalize_message_item(item)
            if norm:
                messages.append(norm)

    if not messages:
        raise HTTPException(status_code=400, detail="未解析到任何有效消息（需含 content/text 等字段）")

    chat_username: str | None = None
    group_sender_wxid_map: dict[str, str] = {}
    if isinstance(data, dict):
        from app.ingest.wx_identity import normalize_chat_username

        chat_username = normalize_chat_username(data.get("username"))

    if is_group:
        from app.ingest.wx_group_members import mine_sender_wxid_from_messages

        group_sender_wxid_map = mine_sender_wxid_from_messages(messages)

    return {
        "chat": chat,
        "is_group": is_group,
        "messages": messages,
        "source_format": source_format,
        "messages_raw_count": n_raw,
        "messages_normalized_count": len(messages),
        "chat_username": chat_username,
        "group_sender_wxid_map": group_sender_wxid_map,
    }


def parse_chat_json_text(raw_text: str) -> dict[str, Any]:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="JSON 内容为空")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}") from e
    return normalize_chat_export(data)
