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


def infer_local_sender_ui_label(
    chat: str,
    speaker_ui_labels: list[str],
    *,
    is_group: bool,
) -> str:
    """推断 JSON 中哪一类 ``sender`` 展示行属于本机微信（与 ``WX_LOCAL_USERNAME`` 对应）。

    默认遵循 wx-cli：``(空 sender)`` = 本机。若会话标题不在 sender 列表、且仅有
    「空 + 一个昵称」（常见：本机在 sender 里显示微信昵称，对端消息 sender 为空），
    则该昵称为本机行。
    """
    if is_group:
        return EMPTY_SENDER_UI_LABEL
    labels = [str(l) for l in speaker_ui_labels if str(l).strip()]
    chat_name = (chat or "").strip()
    has_empty = EMPTY_SENDER_UI_LABEL in labels
    named = [l for l in labels if l != EMPTY_SENDER_UI_LABEL]

    if chat_name and chat_name in labels:
        return EMPTY_SENDER_UI_LABEL
    if has_empty and len(named) == 1:
        return named[0]
    return EMPTY_SENDER_UI_LABEL


def is_local_sender_ui_label(label: str, local_sender_ui_label: str) -> bool:
    return (label or "").strip() == (local_sender_ui_label or "").strip()


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
    local_label = infer_local_sender_ui_label(chat_name, labels, is_group=False)

    profiled: str | None = None
    me = local_label
    hint: str | None = None

    if chat_name and chat_name in labels:
        profiled = chat_name
        if has_empty and chat_name != EMPTY_SENDER_UI_LABEL:
            me = EMPTY_SENDER_UI_LABEL
        elif chat_name != local_label:
            me = local_label
    elif has_empty and len(named) == 1:
        other = str(named[0]["label"])
        # 会话名为对端；对端消息多为 (空 sender)，本机为唯一具名 sender
        profiled = EMPTY_SENDER_UI_LABEL
        me = other
        if chat_name and chat_name not in labels:
            hint = (
                f"会话「{chat_name}」为聊天对象；其消息多在 JSON 的「{EMPTY_SENDER_UI_LABEL}」下，"
                f"本机微信为「{other}」（主键见 backend/.env 的 WX_LOCAL_USERNAME）。"
                f"分析对方时请选「{EMPTY_SENDER_UI_LABEL}」或会话别名；分析自己请选「{other}」。"
            )
    elif len(named) >= 2:
        profiled = str(named[0]["label"])
        me = str(named[1]["label"]) if len(named) > 1 else EMPTY_SENDER_UI_LABEL

    return {
        "suggested_profiled_speaker_label": profiled,
        "suggested_wx_me_sender_label": me,
        "hint": hint,
    }
