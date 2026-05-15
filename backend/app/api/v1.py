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
from app.llm.client import deepseek_configured
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


@router.get("/person/{subject_id}/persona-export")
def persona_export_endpoint(
    neo4j: Neo4jDep,
    subject_id: str,
    format: str = Query("json", description="json | text（别名 txt）"),
) -> Response:
    """按 Person.subject_id 导出当前 last_persona_batch_id 下的人格特质子图（非原始聊天 JSON）。"""
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
