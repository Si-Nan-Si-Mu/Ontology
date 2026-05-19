"""API v1：导入占位、图数据分页等。"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator

from app.deps import Neo4jDep
from app.ingest.wx_cli import analyze_wx_cli_export_senders, ingest_wx_cli_export_json
from app.config import get_settings
from app.json_safe import json_safe
from app.graph_context import build_graph_context_pack
from app.llm.client import deepseek_configured
from app.llm.persona_simulate import simulate_first_person
from app.persona_export import (
    build_persona_export_bundle,
    format_persona_export_text,
    persona_export_json_bytes,
)

router = APIRouter(prefix="/api/v1", tags=["v1"])


class IngestRequest(BaseModel):
    """导入请求：必须声明被本体化的主体（Person 锚点），否则无法正确建图与合并。"""

    subject_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="被本体化对象的稳定主键，对应 Person.subject_id（UUID 或业务用户 ID）",
    )
    subject_display_name: str | None = Field(
        default=None,
        max_length=256,
        description="展示名，可选",
    )
    profiled_speaker_label: str | None = Field(
        default=None,
        max_length=128,
        description="被分析对象在 wx JSON 中的 sender（其消息用于人格画像）；空 sender 填 (空 sender)",
    )
    wx_me_sender_label: str | None = Field(
        default=None,
        max_length=128,
        description="本机微信在 JSON 中的 sender，wx-cli 私聊多为 (空 sender)",
    )
    self_speaker_label: str | None = Field(
        default=None,
        max_length=128,
        description="已废弃：等同 profiled_speaker_label（旧版误标为「对话中的我」）",
    )
    source_type: str = Field(
        default="plain_text",
        description="plain_text | wechat_export | chat_json（聊天 JSON 文件，同 wechat_export）| other",
    )
    raw_text: str | None = Field(default=None, description="原始文本（演示用）")
    note: str | None = Field(default=None, description="备注")
    use_llm: bool = Field(
        default=True,
        description="微信导入时是否尝试 DeepSeek 增强（须 DEEPSEEK_ENABLED 与 API Key）",
    )
    replace_previous_persona: bool = Field(
        default=False,
        description="为 True 时删除本体 Person 上一批 facet 后再写入（旧行为）；默认 False 为追加补充。",
    )
    peer_subject_id: str | None = Field(
        default=None,
        max_length=128,
        description="会话中另一 Person 的 subject_id；与 peer_speaker_label 同时提供时建立 CONVERSATION_WITH 双向边",
    )
    peer_speaker_label: str | None = Field(
        default=None,
        max_length=128,
        description="对方在 JSON messages[].sender 中的展示标签（须与预分析 sender 一致）",
    )
    peer_display_name: str | None = Field(default=None, max_length=256, description="对方 Person 展示名（可选）")
    analyze_peer: bool = Field(
        default=False,
        description="为 True 且非群聊时，对 peer 再跑一套 digest 并写入对方子图（须同时提供 peer_*）",
    )

    @field_validator("subject_id", mode="before")
    @classmethod
    def strip_subject_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def validate_wechat_export(self) -> IngestRequest:
        if self.source_type not in ("wechat_export", "chat_json"):
            return self
        if not (self.raw_text or "").strip():
            raise ValueError(
                "聊天 JSON 导入：请上传 .json 文件或将完整 JSON 粘贴在正文（须含 messages 数组）",
            )
        profiled = (self.profiled_speaker_label or self.self_speaker_label or "").strip()
        if not profiled:
            raise ValueError(
                "微信导入须填写「被分析对象 sender」（profiled_speaker_label）："
                "其消息将用于人格画像；须与 JSON 里 sender 字段一致（本机多为 (空 sender)）。"
            )
        ps = (self.peer_subject_id or "").strip() or None
        pl = (self.peer_speaker_label or "").strip() or None
        if bool(ps) ^ bool(pl):
            raise ValueError("peer_subject_id 与 peer_speaker_label 须同时填写或同时留空。")
        if ps and ps == self.subject_id.strip():
            raise ValueError("peer_subject_id 不能与 subject_id 相同。")
        return self


@router.post("/ingest")
def ingest_endpoint(neo4j: Neo4jDep, body: IngestRequest) -> dict[str, Any]:
    if body.source_type in ("wechat_export", "chat_json"):
        return ingest_wx_cli_export_json(
            neo4j,
            subject_id=body.subject_id,
            subject_display_name=body.subject_display_name,
            profiled_speaker_label=(body.profiled_speaker_label or body.self_speaker_label or "").strip(),
            wx_me_sender_label=(body.wx_me_sender_label or "").strip(),
            self_speaker_label=(body.self_speaker_label or "").strip() or None,
            raw_text=body.raw_text or "",
            note=body.note,
            use_llm=body.use_llm,
            replace_previous_persona=body.replace_previous_persona,
            peer_subject_id=(body.peer_subject_id or "").strip() or None,
            peer_speaker_label=(body.peer_speaker_label or "").strip() or None,
            peer_display_name=(body.peer_display_name or "").strip() or None,
            analyze_peer=body.analyze_peer,
        )
    return {
        "job_id": "stub-accepted",
        "status": "accepted",
        "message": "导入管线（非微信）：请求已接收（占位），未写入 Neo4j。",
        "ontology_subject": {
            "subject_id": body.subject_id,
            "subject_display_name": body.subject_display_name,
            "self_speaker_label": body.self_speaker_label,
        },
    }


@router.post("/ingest/chat-json")
async def ingest_chat_json_file(
    neo4j: Neo4jDep,
    file: UploadFile = File(..., description="聊天 JSON 文件（wx-cli 或含 messages 的通用格式）"),
    subject_id: str = Form(...),
    profiled_speaker_label: str = Form(...),
    wx_me_sender_label: str = Form(""),
    subject_display_name: str | None = Form(None),
    note: str | None = Form(None),
    use_llm: bool = Form(True),
    replace_previous_persona: bool = Form(False),
    peer_subject_id: str | None = Form(None),
    peer_speaker_label: str | None = Form(None),
    peer_display_name: str | None = Form(None),
    analyze_peer: bool = Form(False),
) -> dict[str, Any]:
    """multipart 上传 JSON 聊天文件并写入 Person 特质子图。"""
    name = (file.filename or "").lower()
    if name and not name.endswith(".json"):
        raise HTTPException(status_code=400, detail="仅支持 .json 文件")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        raw_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            raw_text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail="文件须为 UTF-8 编码") from e

    result = ingest_wx_cli_export_json(
        neo4j,
        subject_id=subject_id.strip(),
        subject_display_name=(subject_display_name or "").strip() or None,
        profiled_speaker_label=profiled_speaker_label.strip(),
        wx_me_sender_label=(wx_me_sender_label or "").strip(),
        raw_text=raw_text,
        note=(note or "").strip() or None,
        use_llm=use_llm,
        replace_previous_persona=replace_previous_persona,
        peer_subject_id=(peer_subject_id or "").strip() or None,
        peer_speaker_label=(peer_speaker_label or "").strip() or None,
        peer_display_name=(peer_display_name or "").strip() or None,
        analyze_peer=analyze_peer,
    )
    result["upload"] = {"filename": file.filename, "bytes": len(raw)}
    return result


@router.get("/llm/status")
def llm_status() -> dict[str, Any]:
    """DeepSeek 是否已配置（不返回 API Key）。"""
    s = get_settings()
    return {
        "provider": "deepseek",
        "docs_url": "https://api-docs.deepseek.com/zh-cn/",
        "enabled": s.deepseek_enabled,
        "configured": deepseek_configured(s),
        "base_url": s.deepseek_base_url,
        "model": s.deepseek_model,
        "thinking_enabled": s.deepseek_thinking_enabled,
    }


@router.get("/persons")
def list_persons(neo4j: Neo4jDep) -> dict[str, Any]:
    """列出库中所有 Person 锚点，供前端选择本体化对象。"""
    rows = neo4j.execute_read(
        """
        MATCH (p:Person)
        RETURN coalesce(p.username, p.subject_id) AS subject_id,
               coalesce(p.username, '') AS username,
               coalesce(p.display_name, '') AS display_name,
               p.last_persona_batch_id AS last_persona_batch_id,
               p.last_persona_analyzed_at AS last_analyzed,
               elementId(p) AS element_id
        ORDER BY subject_id
        """
    )
    items: list[dict[str, Any]] = []
    for r in rows or []:
        sid = r.get("subject_id")
        if sid is None or str(sid).strip() == "":
            continue
        items.append(
            {
                "subject_id": str(sid).strip(),
                "username": str(r.get("username") or sid or "").strip(),
                "display_name": str(r.get("display_name") or "").strip(),
                "last_persona_batch_id": json_safe(r.get("last_persona_batch_id")),
                "last_persona_analyzed_at": json_safe(r.get("last_analyzed")),
                "element_id": r.get("element_id"),
            }
        )
    return {"total": len(items), "items": items}


@router.get("/person/{subject_id}/subgraph")
def person_subgraph(neo4j: Neo4jDep, subject_id: str) -> dict[str, Any]:
    """返回某 Person 外向人格特质子图（Person-(HAS_*)->Facet），用于前端可视化。"""
    sid = subject_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="subject_id 不能为空")
    rows = neo4j.execute_read(
        """
        MATCH (p:Person) WHERE p.username = $sid OR p.subject_id = $sid
        OPTIONAL MATCH (p)-[r]->(n)
        WITH p, r, n
        WITH p,
             collect(
               CASE
                 WHEN r IS NULL THEN null
                 ELSE {
                   relationship: type(r),
                   relationship_properties: properties(r),
                   target_element_id: elementId(n),
                   target_labels: labels(n),
                   target_properties: properties(n)
                 }
               END
             ) AS raw
        RETURN properties(p) AS person_props,
               elementId(p) AS person_element_id,
               [e IN raw WHERE e IS NOT NULL] AS edges
        """,
        {"sid": sid},
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"未找到 Person: {sid}")
    row = rows[0]
    edges_raw = row.get("edges") or []
    edges: list[dict[str, Any]] = []
    for e in edges_raw:
        if not isinstance(e, dict):
            continue
        rel = str(e.get("relationship") or "")
        if not rel:
            continue
        props = e.get("target_properties")
        rel_props = e.get("relationship_properties")
        edges.append(
            {
                "relationship": rel[:64],
                "relationship_properties": json_safe(rel_props) if rel_props is not None else {},
                "target_element_id": e.get("target_element_id"),
                "target_labels": list(e.get("target_labels") or []),
                "target_properties": json_safe(props) if props is not None else {},
            }
        )
    return {
        "subject_id": sid,
        "person": {
            "element_id": row.get("person_element_id"),
            "properties": json_safe(row.get("person_props") or {}),
        },
        "edges": edges,
        "stats": {"facet_node_count": len(edges)},
    }


@router.get("/graph/nodes")
def graph_nodes(
    neo4j: Neo4jDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """分页列出库中节点（labels + properties），用于前端结果窗。"""
    skip = (page - 1) * page_size
    total_rows = neo4j.execute_read("MATCH (n) RETURN count(n) AS total")
    total = int(total_rows[0]["total"]) if total_rows else 0
    rows = neo4j.execute_read(
        """
        MATCH (n)
        RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS properties
        ORDER BY element_id
        SKIP $skip
        LIMIT $limit
        """,
        {"skip": skip, "limit": page_size},
    )
    items = [
        {
            "element_id": r.get("element_id"),
            "labels": r.get("labels") or [],
            "properties": json_safe(r.get("properties") or {}),
        }
        for r in rows
    ]
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": items,
    }


def _persona_export_attachment_headers(subject_id: str, ext: str) -> dict[str, str]:
    safe = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", subject_id).strip("._")[:96] or "persona"
    ascii_fn = f"{safe}.{ext}"
    try:
        ascii_fn.encode("ascii")
    except UnicodeEncodeError:
        ascii_fn = f"persona_export.{ext}"
    utf8_fn = f"{subject_id}.{ext}"
    star = quote(utf8_fn, safe="")
    return {"Content-Disposition": f'attachment; filename="{ascii_fn}"; filename*=UTF-8\'\'{star}'}


class SimulateTurn(BaseModel):
    role: str = Field(..., description="user | assistant")
    content: str = Field(..., min_length=1, max_length=4000)


class PersonSimulateBody(BaseModel):
    user_message: str = Field(..., min_length=1, max_length=4000)
    scenario: str | None = Field(
        default=None,
        max_length=512,
        description="可选情境，如「对方问你最近忙什么」",
    )
    history: list[SimulateTurn] = Field(default_factory=list, max_length=20)

    @field_validator("user_message", "scenario", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


@router.post("/person/{subject_id}/simulate")
def person_simulate(
    neo4j: Neo4jDep,
    subject_id: str,
    body: PersonSimulateBody,
) -> dict[str, Any]:
    """第一人称风格模拟：仅以该 Person 在 Neo4j 中的人格子图为依据（须配置 DeepSeek）。"""
    if not deepseek_configured():
        raise HTTPException(
            status_code=503,
            detail="DeepSeek 未启用：请在 backend/.env 设置 DEEPSEEK_ENABLED=true 与 DEEPSEEK_API_KEY",
        )
    sid = subject_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="subject_id 不能为空")
    bundle = build_persona_export_bundle(neo4j, sid)
    pack = build_graph_context_pack(bundle)
    hist = [{"role": t.role, "content": t.content} for t in body.history]
    try:
        result = simulate_first_person(
            context_pack=pack,
            user_message=body.user_message,
            scenario=body.scenario,
            history=hist,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return result


@router.get("/simulate/status")
def simulate_status() -> dict[str, Any]:
    return {"deepseek_configured": deepseek_configured()}


@router.get("/person/{subject_id}/persona-export")
def persona_export_endpoint(
    neo4j: Neo4jDep,
    subject_id: str,
    format: str = Query("json", description="json | text（别名 txt）"),
) -> Response:
    """按 Person.subject_id 导出人格特质子图（聚合全部导入批次；``persona_batch_id`` 为最近批次指针）。"""
    sid = subject_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="subject_id 不能为空")
    fmt = (format or "json").strip().lower()
    bundle = build_persona_export_bundle(neo4j, sid)
    if fmt in ("text", "txt"):
        body = format_persona_export_text(bundle)
        return Response(
            content=body.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers=_persona_export_attachment_headers(sid, "txt"),
        )
    if fmt == "json":
        return Response(
            content=persona_export_json_bytes(bundle),
            media_type="application/json; charset=utf-8",
            headers=_persona_export_attachment_headers(sid, "json"),
        )
    raise HTTPException(status_code=400, detail="format 须为 json 或 text（txt）")
