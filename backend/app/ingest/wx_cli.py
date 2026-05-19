"""解析 [wx-cli](https://github.com/jackwener/wx-cli) `wx export …` JSON：内存中解析后，
为被分析的 `Person` 创建特质子图（摘要 / 表达风格 / 口癖 / 情绪维度 / 社会关系草图 / 九型占位 / 大五词典草图 / MBTI 占位与文献注记 / 典型对话 / 元数据节点）并建立关系，不写入逐条 Utterance。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException

from app.db.neo4j import Neo4jConnection
from app.ingest.wx_group_members import build_group_sender_wxid_map, try_fetch_group_members
from app.ingest.wx_identity import (
    export_chat_username,
    normalize_chat_username,
    resolve_peer_subject_id,
    resolve_person_subject_id,
    suggested_subject_id_for_sender_row,
)
from app.ingest.wx_speakers import (
    EMPTY_SENDER_UI_LABEL,
    display_sender_label,
    infer_local_sender_ui_label,
    is_local_sender_ui_label,
)
from app.ingest.persona_neo4j import (
    FACET_SCHEMA_VERSION,
    delete_old_persona_batch,
    merge_person_shell,
    parse_analysis_meta,
    write_conversation_peer_links,
    write_persona_facet_graph,
)
from app.ingest.wx_persona import build_persona_digest
from app.ingest.wx_speakers import (
    display_sender_label,
    infer_local_sender_ui_label,
    is_local_sender_ui_label,
    suggest_private_chat_roles,
)

from app.ingest.chat_json import ABSOLUTE_MESSAGE_LIST_CAP, parse_chat_json_text

# 与 wechat API 中 Pydantic ``le=`` 对齐；单次请求实际条数上限为 ``wx_chat_import_max_messages()``（默认 10 万）
WX_EXPORT_MAX_MESSAGES = ABSOLUTE_MESSAGE_LIST_CAP


def parse_wx_cli_export_payload(raw_text: str) -> dict[str, Any]:
    """解析 wx-cli 或通用聊天 JSON（见 ``chat_json.normalize_chat_export``）。"""
    return parse_chat_json_text(raw_text)


def _load_group_sender_wxid_map(
    payload: dict[str, Any],
    messages: list[Any],
) -> dict[str, str]:
    if not payload.get("is_group"):
        return {}
    chat = str(payload.get("chat") or "")
    members = try_fetch_group_members(chat)
    return build_group_sender_wxid_map(
        chat=chat,
        messages=messages,
        members_rows=members,
    )


def _sender_displays_in_messages(messages: list[Any]) -> set[str]:
    """消息中出现过的 sender 展示标签集合（与 profiled / wx_me 下拉一致）。"""
    out: set[str] = set()
    for m in messages:
        if not isinstance(m, dict):
            continue
        raw = m.get("sender")
        out.add(display_sender_label(raw if isinstance(raw, str) else ""))
    return out


def analyze_wx_cli_export_senders(
    raw_text: str,
    *,
    probe_message_limit: int | None = 800,
) -> dict[str, Any]:
    """从聊天 JSON 统计 sender 频次，供前端选择本体对象与说话人角色。

    ``probe_message_limit``：仅用前 N 条**已规范化**消息参与统计（大文件探针，避免全量遍历）；
    若为 ``None`` 则使用全部消息。
    """
    payload = parse_wx_cli_export_payload(raw_text)
    chat_username = export_chat_username(payload)
    messages: list[Any] = payload["messages"]
    total_norm = len(messages)
    if probe_message_limit is None or probe_message_limit <= 0:
        scan = messages
    else:
        scan = messages[: min(probe_message_limit, total_norm)]
    counts: dict[str, int] = {}
    for m in scan:
        if not isinstance(m, dict):
            continue
        lab = (m.get("sender") or "").strip()
        disp = display_sender_label(lab)
        counts[disp] = counts.get(disp, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    is_group = payload["is_group"]
    chat_name = payload["chat"]
    speaker_ui_labels = [lab for lab, _ in rows]
    local_sender_ui_label = infer_local_sender_ui_label(
        chat_name, speaker_ui_labels, is_group=is_group
    )
    group_wxid_map = _load_group_sender_wxid_map(payload, scan)
    senders = []
    for lab, c in rows:
        sid = suggested_subject_id_for_sender_row(
            sender_display_label=lab,
            chat_username=chat_username,
            is_group=is_group,
            local_sender_ui_label=local_sender_ui_label,
            group_sender_wxid_map=group_wxid_map,
        )
        is_local = is_local_sender_ui_label(lab, local_sender_ui_label)
        if is_local:
            role = "local"
        elif is_group:
            role = "member" if normalize_chat_username(sid) else "unknown"
        else:
            role = "peer"
        senders.append(
            {
                "label": lab,
                "count": c,
                "username": sid,
                "suggested_subject_id": sid,
                "is_local_sender": is_local,
                "role": role,
            }
        )
    if chat_name and not is_group:
        alias_sid = suggested_subject_id_for_sender_row(
            sender_display_label=chat_name,
            chat_username=chat_username,
            is_group=False,
            is_session_alias=True,
            local_sender_ui_label=local_sender_ui_label,
        )
        senders.insert(
            0,
            {
                "label": chat_name,
                "count": 0,
                "username": alias_sid,
                "suggested_subject_id": alias_sid,
                "is_session_alias": True,
                "is_local_speaker": False,
                "role": "peer",
            },
        )
    role_hint = suggest_private_chat_roles(chat_name, senders, is_group=is_group)
    group_hint: str | None = None
    if is_group:
        unresolved = [
            s["label"]
            for s in senders
            if not s.get("is_session_alias")
            and not s.get("is_local_sender")
            and not normalize_chat_username(s.get("suggested_subject_id") or "")
        ]
        if unresolved:
            group_hint = (
                f"以下说话人未解析到 wxid（将使用临时主键 wxp_…，易与他人混淆）："
                f"{'、'.join(unresolved[:8])}"
                f"{'…' if len(unresolved) > 8 else ''}。"
                "请开启 WX_CLI_ENABLED 后重新预分析以拉取群成员，或确认 JSON 来自 wx-cli。"
            )
        elif not group_wxid_map:
            group_hint = (
                "群聊未建立成员 wxid 映射：建议在 backend/.env 设置 WX_CLI_ENABLED=true "
                "并重新预分析（将调用 wx members）。"
            )
    raw_total = int(payload.get("messages_raw_count") or total_norm)
    return {
        "chat": chat_name,
        "chat_username": chat_username,
        "is_group": is_group,
        "group_sender_wxid_map_size": len(group_wxid_map),
        "message_count": total_norm,
        "messages_raw_in_export": raw_total,
        "messages_dropped_no_body": max(0, raw_total - total_norm),
        "messages_probed_for_senders": len(scan),
        "senders": senders,
        "local_sender_ui_label": local_sender_ui_label,
        "source_format": payload.get("source_format"),
        "messages_normalized_count": payload.get("messages_normalized_count"),
        "hint": role_hint.get("hint") or group_hint,
        "suggested_profiled_speaker_label": role_hint.get(
            "suggested_profiled_speaker_label"
        ),
        "suggested_wx_me_sender_label": role_hint.get("suggested_wx_me_sender_label"),
    }


def ingest_wx_cli_export_json(
    neo4j: Neo4jConnection,
    *,
    subject_id: str,
    subject_display_name: str | None,
    profiled_speaker_label: str,
    wx_me_sender_label: str = "",
    self_speaker_label: str | None = None,
    raw_text: str,
    note: str | None,
    use_llm: bool = True,
    replace_previous_persona: bool = False,
    peer_subject_id: str | None = None,
    peer_speaker_label: str | None = None,
    peer_display_name: str | None = None,
    analyze_peer: bool = False,
) -> dict[str, Any]:
    """解析 wx-cli / 聊天 JSON：写入 Person 特质子图。

    默认 **追加**（``replace_previous_persona=False``）：不删除该 Person 既有批次 facet，仅更新
    ``last_persona_batch_id`` 指向本批；旧批次节点仍保留在库中。

    若提供 ``peer_subject_id`` + ``peer_speaker_label``：建立双方 ``Person`` 间双向
    ``CONVERSATION_WITH`` 链接；可选 ``analyze_peer`` 对对方再跑一套 digest 并写入对方子图
    （群聊下不允许 ``analyze_peer``）。
    """
    payload = parse_wx_cli_export_payload(raw_text)
    messages: list[Any] = payload["messages"]
    raw_export_count = int(payload.get("messages_raw_count") or len(messages))
    normalized_count = int(payload.get("messages_normalized_count") or len(messages))
    chat: str = payload["chat"]
    is_group: bool = payload["is_group"]
    chat_username = export_chat_username(payload)
    profiled = (profiled_speaker_label or self_speaker_label or "").strip()
    if not profiled:
        raise HTTPException(status_code=400, detail="须指定被分析对象的 sender（profiled_speaker_label）")

    speaker_ui_labels = sorted(_sender_displays_in_messages(messages))
    local_sender_ui_label = infer_local_sender_ui_label(
        chat, speaker_ui_labels, is_group=is_group
    )
    group_wxid_map = _load_group_sender_wxid_map(payload, messages)
    subject_id = resolve_person_subject_id(
        chat_username=chat_username,
        profiled_speaker_label=profiled,
        is_group=is_group,
        client_subject_id=subject_id,
        chat=chat,
        speaker_ui_labels=speaker_ui_labels,
        local_sender_ui_label=local_sender_ui_label,
        group_sender_wxid_map=group_wxid_map,
    )
    if subject_id == "wxp_local_unconfigured":
        raise HTTPException(
            status_code=400,
            detail=(
                "分析本机微信发言（sender 为空）须在 backend/.env 配置 WX_LOCAL_USERNAME=你的 wxid，"
                "例如 wxid_xxxxxxxx。分析聊天对象时请选对方昵称而非 (空 sender)。"
            ),
        )

    peer_lab_raw = (peer_speaker_label or "").strip() or None
    peer_sid: str | None = None
    if peer_lab_raw:
        peer_sid = resolve_peer_subject_id(
            chat_username=chat_username,
            profiled_speaker_label=profiled,
            peer_speaker_label=peer_lab_raw,
            is_group=is_group,
            client_peer_subject_id=(peer_subject_id or "").strip() or None,
            chat=chat,
            speaker_ui_labels=speaker_ui_labels,
            local_sender_ui_label=local_sender_ui_label,
            group_sender_wxid_map=group_wxid_map,
        )
        if peer_sid == "wxp_local_unconfigured":
            raise HTTPException(
                status_code=400,
                detail="链接对方为本机微信时，请在 .env 配置 WX_LOCAL_USERNAME。",
            )
    elif (peer_subject_id or "").strip() and not peer_lab_raw:
        raise HTTPException(
            status_code=400,
            detail="已提供 peer_subject_id 时须同时提供 peer_speaker_label。",
        )
    elif (peer_subject_id or "").strip() and peer_lab_raw and not peer_sid:
        peer_sid = (peer_subject_id or "").strip()

    if peer_lab_raw and not peer_sid:
        raise HTTPException(
            status_code=400,
            detail=(
                "无法解析客体 Person 主键：私聊中客体为「(空 sender)」时请配置 WX_LOCAL_USERNAME；"
                "或检查 peer_speaker_label 是否与 JSON 中 sender 一致。"
            ),
        )
    if peer_sid and peer_sid == subject_id:
        raise HTTPException(status_code=400, detail="peer 与本体不能为同一 Person（相同 username）。")
    if analyze_peer and is_group:
        raise HTTPException(
            status_code=400,
            detail="群聊暂不支持「同时分析对方」人格子图；可仅建立 CONVERSATION_WITH 链接或改用私聊双说话人。",
        )

    try:
        digest = build_persona_digest(
            messages,
            profiled_speaker_label=profiled,
            wx_me_sender_label=wx_me_sender_label,
            chat=chat,
            is_group=is_group,
            use_llm=use_llm,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if peer_sid and peer_lab_raw:
        displays = _sender_displays_in_messages(messages)
        peer_disp = display_sender_label(peer_lab_raw)
        if peer_disp not in displays:
            raise HTTPException(
                status_code=400,
                detail=f"peer_speaker_label 在消息中未出现：{peer_disp!r}。可选 sender：{sorted(displays)[:12]}",
            )

    job_id = str(uuid.uuid4())
    note_suffix = f" · {note.strip()[:200]}" if (note or "").strip() else ""
    persona_summary = digest["persona_summary"]
    if note_suffix:
        persona_summary = f"{persona_summary}{note_suffix}"[:4000]

    fallback_display = (
        (subject_display_name or "").strip()
        or display_sender_label(profiled)
        or chat
        or subject_id
    )[:256]
    display_in = (subject_display_name or "").strip()
    profiled_disp = display_sender_label(profiled)

    def work(tx: Any) -> int:
        row = tx.run(
            """
            MATCH (p:Person) WHERE p.username = $sid OR p.subject_id = $sid
            RETURN p.last_persona_batch_id AS bid
            LIMIT 1
            """,
            sid=subject_id,
        ).single()
        old_batch = row.get("bid") if row else None
        if replace_previous_persona and old_batch:
            delete_old_persona_batch(tx, old_batch)

        facet_count = write_persona_facet_graph(
            tx,
            subject_id=subject_id,
            batch_id=job_id,
            display_name=display_in,
            fallback_display=fallback_display,
            digest=digest,
            persona_summary=persona_summary,
        )

        if peer_sid and peer_lab_raw:
            peer_dn = ((peer_display_name or "").strip() or display_sender_label(peer_lab_raw))[:256]
            merge_person_shell(tx, subject_id=peer_sid, display_name=peer_dn)
            dyadic_rel = digest.get("dyadic_relationship")
            if not isinstance(dyadic_rel, dict):
                sk = digest.get("social_relation_sketch")
                if isinstance(sk, dict) and sk.get("dyadic_relation_type"):
                    dyadic_rel = {
                        "type": sk.get("dyadic_relation_type"),
                        "type_zh": sk.get("dyadic_relation_type_zh"),
                        "confidence": sk.get("dyadic_relation_confidence", 0.0),
                        "rationale": sk.get("dyadic_relation_rationale", ""),
                        "inference_source": sk.get("interpretation_source", "heuristic"),
                    }
            write_conversation_peer_links(
                tx,
                subject_id_a=subject_id,
                subject_id_b=peer_sid,
                batch_id=job_id,
                chat_session=chat,
                sender_a_display=profiled_disp,
                sender_b_display=display_sender_label(peer_lab_raw),
                relationship=dyadic_rel if isinstance(dyadic_rel, dict) else None,
            )
            if analyze_peer:
                prow = tx.run(
                    """
                    MATCH (p:Person) WHERE p.username = $sid OR p.subject_id = $sid
                    RETURN p.last_persona_batch_id AS bid
                    LIMIT 1
                    """,
                    sid=peer_sid,
                ).single()
                peer_old = prow.get("bid") if prow else None
                if replace_previous_persona and peer_old:
                    delete_old_persona_batch(tx, peer_old)
                peer_digest = build_persona_digest(
                    messages,
                    profiled_speaker_label=peer_lab_raw,
                    wx_me_sender_label=profiled,
                    chat=chat,
                    is_group=is_group,
                    use_llm=use_llm,
                )
                peer_summary = peer_digest["persona_summary"]
                if note_suffix:
                    peer_summary = f"{peer_summary}{note_suffix}"[:4000]
                peer_fallback = (peer_dn or display_sender_label(peer_lab_raw) or chat or peer_sid)[:256]
                facet_count += write_persona_facet_graph(
                    tx,
                    subject_id=peer_sid,
                    batch_id=job_id,
                    display_name=(peer_display_name or "").strip(),
                    fallback_display=peer_fallback,
                    digest=peer_digest,
                    persona_summary=peer_summary,
                )

        return facet_count

    with neo4j.session() as session:
        facet_count = session.execute_write(work)

    try:
        analysis_meta = parse_analysis_meta(digest)
    except Exception:
        analysis_meta = {}

    return {
        "job_id": job_id,
        "status": "done",
        "message": (
            f"已写入 Neo4j：Person 特质子图（schema {FACET_SCHEMA_VERSION}），"
            "含统一 inference_source / 大五分项节点 / MBTI type_code 等规范字段。"
        ),
        "ontology_subject": {
            "subject_id": subject_id,
            "username": subject_id,
            "chat_username": chat_username,
            "subject_display_name": subject_display_name,
            "self_speaker_label": display_sender_label(profiled),
            "profiled_speaker_label": display_sender_label(profiled),
            "wx_me_sender_label": display_sender_label(wx_me_sender_label),
            "chat_session": chat,
        },
        "ingest_options": {
            "replace_previous_persona": replace_previous_persona,
            "peer_subject_id": peer_sid,
            "peer_speaker_label": display_sender_label(peer_lab_raw) if peer_lab_raw else None,
            "analyze_peer": bool(analyze_peer and peer_sid and peer_lab_raw),
            "dyadic_relationship": digest.get("dyadic_relationship"),
        },
        "wx_cli": {
            "mode": "persona_facet_graph",
            "chat": chat,
            "is_group": is_group,
            "messages_raw_in_export": raw_export_count,
            "messages_normalized_in_export": normalized_count,
            "messages_dropped_no_body": max(0, raw_export_count - normalized_count),
            "messages_in_file": len(messages),
            "messages_used_for_digest": digest["messages_used"],
            "exemplar_thread_count": digest["exemplar_thread_count"],
            "facet_nodes_created": facet_count,
            "persona_batch_id": job_id,
            "person_subject_id": subject_id,
            "facet_schema_version": FACET_SCHEMA_VERSION,
            "inference_mode": analysis_meta.get("inference_mode", "heuristic"),
            "llm_status": analysis_meta.get("llm_status"),
            "llm_model": analysis_meta.get("llm_model"),
        },
    }
