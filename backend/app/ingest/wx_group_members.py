"""群聊说话人展示名 → wxid 解析（wx-cli members + 消息正文挖掘）。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from app.ingest.wx_identity import normalize_chat_username
from app.ingest.wx_speakers import EMPTY_SENDER_UI_LABEL

_QUOTE_WXID_RE = re.compile(
    r"↳\s*([^:\n]{1,64}?):\s*(wxid_[a-z0-9]+)",
    re.IGNORECASE,
)
_FROMUSER_RE = re.compile(
    r'fromusername\s*=\s*["\']?(wxid_[a-z0-9]+)',
    re.IGNORECASE,
)
_CARD_USER_RE = re.compile(
    r'username\s*=\s*["\']?(wxid_[a-z0-9]+)["\']?',
    re.IGNORECASE,
)
_CARD_NICK_RE = re.compile(
    r'nickname\s*=\s*["\']([^"\']{1,64})',
    re.IGNORECASE,
)


def build_sender_directory_from_members(members: list[dict[str, Any]]) -> dict[str, str]:
    """wx-cli ``members --json`` → 展示名/群昵称/备注 → wxid。"""
    out: dict[str, str] = {}
    for row in members:
        if not isinstance(row, dict):
            continue
        wxid = normalize_chat_username(row.get("username"))
        if not wxid:
            continue
        for key in (
            row.get("display"),
            row.get("group_nickname"),
            row.get("contact_display"),
        ):
            if not key:
                continue
            lab = str(key).strip()
            if lab:
                out[lab] = wxid
    return out


def _pick_majority(counter: Counter[str]) -> str | None:
    if not counter:
        return None
    wxid, _ = counter.most_common(1)[0]
    return wxid


def mine_sender_wxid_from_messages(messages: list[Any]) -> dict[str, str]:
    """从群消息正文（引用行、fromusername、名片 XML）统计展示名 → wxid。"""
    votes: dict[str, Counter[str]] = defaultdict(Counter)

    for m in messages:
        if not isinstance(m, dict):
            continue
        sender = (m.get("sender") or "").strip()
        content = str(m.get("content") or "")
        if not content:
            continue

        if sender:
            direct = normalize_chat_username(sender)
            if direct:
                votes[sender][direct] += 5

        for name, raw_wxid in _QUOTE_WXID_RE.findall(content):
            wxid = normalize_chat_username(raw_wxid)
            if not wxid:
                continue
            name = name.strip()
            votes[name][wxid] += 1
            if sender and name == sender:
                votes[sender][wxid] += 4

        for raw_wxid in _FROMUSER_RE.findall(content):
            wxid = normalize_chat_username(raw_wxid)
            if wxid and sender:
                votes[sender][wxid] += 2

        card_wxids = _CARD_USER_RE.findall(content)
        card_nicks = _CARD_NICK_RE.findall(content)
        if card_wxids and card_nicks:
            wxid = normalize_chat_username(card_wxids[0])
            nick = card_nicks[0].strip()
            if wxid and nick:
                votes[nick][wxid] += 2

    out: dict[str, str] = {}
    for name, counter in votes.items():
        wxid = _pick_majority(counter)
        if wxid:
            out[name] = wxid
    return out


def merge_sender_wxid_maps(*maps: dict[str, str]) -> dict[str, str]:
    """合并映射；先出现的优先（调用方把 members 放在最前）。"""
    out: dict[str, str] = {}
    for m in maps:
        for k, v in m.items():
            if k not in out and v:
                out[k] = v
    return out


def lookup_group_sender_wxid(
    sender_display_label: str,
    sender_wxid_map: dict[str, str],
) -> str | None:
    if not sender_wxid_map:
        return None
    if sender_display_label == EMPTY_SENDER_UI_LABEL:
        return None
    lab = (sender_display_label or "").strip()
    if not lab:
        return None
    hit = sender_wxid_map.get(lab)
    if hit:
        return hit
    direct = normalize_chat_username(lab)
    if direct:
        return direct
    return None


def build_group_sender_wxid_map(
    *,
    chat: str,
    messages: list[Any],
    members_rows: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """群聊 Person 主键映射：members 目录优先，消息挖掘补全。"""
    members_map = (
        build_sender_directory_from_members(members_rows) if members_rows else {}
    )
    mined = mine_sender_wxid_from_messages(messages)
    return merge_sender_wxid_maps(members_map, mined)


def try_fetch_group_members(
    chat: str,
) -> list[dict[str, Any]] | None:
    """本机 wx-cli 可用时拉取群成员；失败返回 None（不抛错）。"""
    chat = (chat or "").strip()
    if not chat:
        return None
    try:
        from app.config import get_settings
        from app.wechat_cli.runner import fetch_group_members_json

        s = get_settings()
        if not s.wx_cli_enabled:
            return None
        return fetch_group_members_json(
            wx_command=s.wx_cli_command,
            chat=chat,
            timeout_sec=s.wx_cli_timeout_sec,
        )
    except Exception:
        return None
