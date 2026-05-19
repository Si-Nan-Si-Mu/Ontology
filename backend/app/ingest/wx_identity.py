"""wx-cli 导出 JSON 中的 Person 主键：优先使用根字段 ``username``（wxid）。"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.ingest.wx_speakers import (
    EMPTY_SENDER_UI_LABEL,
    infer_local_sender_ui_label,
    is_local_sender_ui_label,
)

_WXID_RE = re.compile(r"^wxid_[a-z0-9]+$", re.IGNORECASE)
_CHATROOM_RE = re.compile(r"^\d+@chatroom$", re.IGNORECASE)


def normalize_chat_username(raw: str | None) -> str | None:
    """校验并返回可作为 Person 主键的 username（wx-cli 私聊对端 wxid 或群 id）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if _WXID_RE.match(s) or _CHATROOM_RE.match(s):
        return s
    if s.startswith("wxid_") and len(s) <= 128:
        return s
    return None


def export_chat_username(payload: dict[str, Any]) -> str | None:
    return normalize_chat_username(payload.get("chat_username") or payload.get("username"))


def local_wx_username() -> str | None:
    from app.config import get_settings

    return normalize_chat_username(get_settings().wx_local_username)


def _legacy_subject_id_from_sender(sender: str) -> str:
    s = (sender or "").strip() or "(unknown)"
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]
    return f"wxp_{h}"


def resolve_person_subject_id(
    *,
    chat_username: str | None,
    profiled_speaker_label: str,
    is_group: bool,
    client_subject_id: str | None = None,
    chat: str | None = None,
    speaker_ui_labels: list[str] | None = None,
    local_sender_ui_label: str | None = None,
    group_sender_wxid_map: dict[str, str] | None = None,
) -> str:
    """根据导出 ``username`` 与被分析 sender 解析唯一 Person 主键（写入 ``username`` / ``subject_id``）。

    私聊：根 ``username`` 为**对端** wxid；本机行由 ``infer_local_sender_ui_label`` 判定
    （默认空 sender，或「会话名不在 sender 列表 + 唯一昵称」时该昵称为本机）。
    分析本机行时使用 ``WX_LOCAL_USERNAME``（须在 .env 配置）。
    群聊：根 ``username`` 为群 id；各成员经 ``group_sender_wxid_map``（wx members / 消息挖掘）解析为 wxid。
    """
    wxid = normalize_chat_username(chat_username)

    if is_group:
        local_lbl = local_sender_ui_label or EMPTY_SENDER_UI_LABEL
        if is_local_sender_ui_label(profiled_speaker_label, local_lbl):
            local = local_wx_username()
            if local:
                return local
            return "wxp_local_unconfigured"
        from app.ingest.wx_group_members import lookup_group_sender_wxid

        mapped = lookup_group_sender_wxid(
            profiled_speaker_label, group_sender_wxid_map or {}
        )
        if mapped:
            return mapped
        sid = (client_subject_id or "").strip()
        if sid:
            if normalize_chat_username(sid):
                return normalize_chat_username(sid) or sid
            return sid
        return _legacy_subject_id_from_sender(profiled_speaker_label)

    if wxid and not is_group:
        local_lbl = local_sender_ui_label
        if local_lbl is None and speaker_ui_labels is not None:
            local_lbl = infer_local_sender_ui_label(
                chat or "", speaker_ui_labels, is_group=False
            )
        elif local_lbl is None:
            local_lbl = EMPTY_SENDER_UI_LABEL

        if is_local_sender_ui_label(profiled_speaker_label, local_lbl):
            local = local_wx_username()
            if local:
                return local
            return "wxp_local_unconfigured"
        return wxid

    sid = (client_subject_id or "").strip()
    if sid:
        if normalize_chat_username(sid):
            return normalize_chat_username(sid) or sid
        return sid
    return _legacy_subject_id_from_sender(profiled_speaker_label)


def resolve_peer_subject_id(
    *,
    chat_username: str | None,
    profiled_speaker_label: str,
    peer_speaker_label: str,
    is_group: bool,
    client_peer_subject_id: str | None = None,
    chat: str | None = None,
    speaker_ui_labels: list[str] | None = None,
    local_sender_ui_label: str | None = None,
    group_sender_wxid_map: dict[str, str] | None = None,
) -> str | None:
    """解析客体 Person 主键（与本体配对的另一方）。"""
    if not (peer_speaker_label or "").strip():
        return None

    return resolve_person_subject_id(
        chat_username=chat_username,
        profiled_speaker_label=peer_speaker_label,
        is_group=is_group,
        client_subject_id=client_peer_subject_id,
        chat=chat,
        speaker_ui_labels=speaker_ui_labels,
        local_sender_ui_label=local_sender_ui_label,
        group_sender_wxid_map=group_sender_wxid_map,
    )


def suggested_subject_id_for_sender_row(
    *,
    sender_display_label: str,
    chat_username: str | None,
    is_group: bool,
    is_session_alias: bool = False,
    local_sender_ui_label: str | None = None,
    group_sender_wxid_map: dict[str, str] | None = None,
) -> str:
    """预分析说话人列表中的建议主键。"""
    wxid = normalize_chat_username(chat_username)
    local_lbl = local_sender_ui_label or EMPTY_SENDER_UI_LABEL

    if is_session_alias and wxid and not is_group:
        return wxid

    if is_group:
        if is_local_sender_ui_label(sender_display_label, local_lbl):
            local = local_wx_username()
            return local or "wxp_local_unconfigured"
        from app.ingest.wx_group_members import lookup_group_sender_wxid

        mapped = lookup_group_sender_wxid(
            sender_display_label, group_sender_wxid_map or {}
        )
        if mapped:
            return mapped
        return _legacy_subject_id_from_sender(
            "" if sender_display_label == EMPTY_SENDER_UI_LABEL else sender_display_label
        )

    if wxid and not is_group:
        if is_local_sender_ui_label(sender_display_label, local_lbl):
            local = local_wx_username()
            return local or "wxp_local_unconfigured"
        return wxid

    return _legacy_subject_id_from_sender(
        "" if sender_display_label == EMPTY_SENDER_UI_LABEL else sender_display_label
    )


def display_label_for_subject_id(subject_id: str, fallback: str = "") -> str:
    if subject_id.startswith("wxid_"):
        return fallback or subject_id
    if subject_id == "wxp_local_unconfigured":
        return fallback or "本机微信（未配置 WX_LOCAL_USERNAME）"
    return fallback or subject_id
