"""解析 [wx-cli](https://github.com/jackwener/wx-cli) `wx export …` JSON：内存中解析后，
为被分析的 `Person` 创建特质子图（摘要 / 表达风格 / 口癖 / 情绪维度 / 社会关系草图 / 九型占位 / 大五词典草图 / MBTI 占位与文献注记 / 典型对话 / 元数据节点）并建立关系，不写入逐条 Utterance。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from fastapi import HTTPException

from app.db.neo4j import Neo4jConnection
from app.ingest.persona_neo4j import (
    FACET_SCHEMA_VERSION,
    delete_old_persona_batch,
    parse_analysis_meta,
    write_persona_facet_graph,
)
from app.ingest.wx_persona import build_persona_digest
from app.ingest.wx_speakers import (
    EMPTY_SENDER_UI_LABEL,
    canonical_sender_label,
    display_sender_label,
    suggest_private_chat_roles,
)

from app.ingest.chat_json import parse_chat_json_text

WX_EXPORT_MAX_MESSAGES = 8000


def parse_wx_cli_export_payload(raw_text: str) -> dict[str, Any]:
    """解析 wx-cli 或通用聊天 JSON（见 ``chat_json.normalize_chat_export``）。"""
    return parse_chat_json_text(raw_text)


def suggested_subject_id_from_sender(sender: str) -> str:
    """由说话人标签生成稳定 Person.subject_id（ASCII，便于 Neo4j 与 URL）。"""
    s = (sender or "").strip() or "(unknown)"
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]
    return f"wxp_{h}"


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
    senders = [
        {
            "label": lab,
            "count": c,
            "suggested_subject_id": suggested_subject_id_from_sender(
                "" if lab == EMPTY_SENDER_UI_LABEL else lab
            ),
        }
        for lab, c in rows
    ]
    chat_name = payload["chat"]
    is_group = payload["is_group"]
    if chat_name and not is_group:
        senders.insert(
            0,
            {
                "label": chat_name,
                "count": 0,
                "suggested_subject_id": suggested_subject_id_from_sender(chat_name),
                "is_session_alias": True,
            },
        )
    role_hint = suggest_private_chat_roles(chat_name, senders, is_group=is_group)
    return {
        "chat": chat_name,
        "is_group": is_group,
        "message_count": total_norm,
        "messages_probed_for_senders": len(scan),
        "senders": senders,
        "source_format": payload.get("source_format"),
        "messages_normalized_count": payload.get("messages_normalized_count"),
        **role_hint,
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
) -> dict[str, Any]:
    """解析 wx-cli JSON：删除该 Person 上一批特质子图后，写入新一批特质节点并连到 Person。"""
    payload = parse_wx_cli_export_payload(raw_text)
    messages: list[Any] = payload["messages"]
    chat: str = payload["chat"]
    is_group: bool = payload["is_group"]
    profiled = (profiled_speaker_label or self_speaker_label or "").strip()
    if not profiled:
        raise HTTPException(status_code=400, detail="须指定被分析对象的 sender（profiled_speaker_label）")

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

    def work(tx: Any) -> int:
        row = tx.run(
            "MATCH (p:Person {subject_id: $sid}) RETURN p.last_persona_batch_id AS bid",
            sid=subject_id,
        ).single()
        old_batch = row.get("bid") if row else None
        if old_batch:
            delete_old_persona_batch(tx, old_batch)

        return write_persona_facet_graph(
            tx,
            subject_id=subject_id,
            batch_id=job_id,
            display_name=display_in,
            fallback_display=fallback_display,
            digest=digest,
            persona_summary=persona_summary,
        )

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
            "subject_display_name": subject_display_name,
            "self_speaker_label": display_sender_label(profiled),
            "profiled_speaker_label": display_sender_label(profiled),
            "wx_me_sender_label": display_sender_label(wx_me_sender_label),
            "chat_session": chat,
        },
        "wx_cli": {
            "mode": "persona_facet_graph",
            "chat": chat,
            "is_group": is_group,
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
