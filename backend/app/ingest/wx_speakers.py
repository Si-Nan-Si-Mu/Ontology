"""wx-cli 说话人标签规范化与私聊角色推断。"""

from __future__ import annotations

from typing import Any

EMPTY_SENDER_UI_LABEL = "(空 sender)"

_EMPTY_ALIASES = frozenset(
    {
        "",
        EMPTY_SENDER_UI_LABEL,
        "(空sender)",
        "空 sender",
        "空sender",
        "__empty__",
    }
)


def canonical_sender_label(label: str | None) -> str:
    """UI/API 标签 → 与 JSON `sender` 比对用的规范值（空 sender 为 ''）。"""
    if label is None:
        return ""
    s = label.strip()
    if s in _EMPTY_ALIASES:
        return ""
    return s


def display_sender_label(sender: str | None) -> str:
    """JSON `sender` → 前端下拉展示标签。"""
    if sender is None or not str(sender).strip():
        return EMPTY_SENDER_UI_LABEL
    return str(sender).strip()


def suggest_private_chat_roles(
    chat: str,
    senders: list[dict[str, Any]],
    *,
    is_group: bool,
) -> dict[str, Any]:
    """私聊双说话人时推断「被分析对象 / 本机微信」默认选项。"""
    if is_group or len(senders) < 2:
        return {
            "suggested_profiled_speaker_label": None,
            "suggested_wx_me_sender_label": EMPTY_SENDER_UI_LABEL,
            "hint": None,
        }

    labels = [str(s.get("label", "")) for s in senders if not s.get("is_session_alias")]
    has_empty = EMPTY_SENDER_UI_LABEL in labels
    named = [s for s in senders if s.get("label") != EMPTY_SENDER_UI_LABEL and not s.get("is_session_alias")]
    chat_name = (chat or "").strip()

    profiled: str | None = None
    me = EMPTY_SENDER_UI_LABEL
    hint: str | None = None

    if chat_name and chat_name in labels:
        profiled = chat_name
        if has_empty and chat_name != EMPTY_SENDER_UI_LABEL:
            me = EMPTY_SENDER_UI_LABEL
    elif has_empty and len(named) == 1:
        other = str(named[0]["label"])
        # 会话名常为对方昵称/wxid 展示名，但 sender 里可能只有「空 + 另一昵称」
        profiled = EMPTY_SENDER_UI_LABEL
        me = other
        if chat_name and chat_name not in labels:
            hint = (
                f"会话「{chat_name}」未出现在 sender 字段中。"
                f"wx-cli 私聊里「{EMPTY_SENDER_UI_LABEL}」与「{other}」二选一为对方消息时，"
                f"若要对会话对象建 Person，请将被分析对象选为 {EMPTY_SENDER_UI_LABEL}，"
                f"本机微信选为「{other}」（若实际相反请对调）。"
            )
    elif len(named) >= 2:
        profiled = str(named[0]["label"])
        me = str(named[1]["label"]) if len(named) > 1 else EMPTY_SENDER_UI_LABEL

    return {
        "suggested_profiled_speaker_label": profiled,
        "suggested_wx_me_sender_label": me,
        "hint": hint,
    }
