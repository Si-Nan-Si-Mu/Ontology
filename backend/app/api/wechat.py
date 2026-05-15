"""本机 wx-cli 会话列表与按会话导出 → 复用 wechat_export 写入逻辑。"""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.deps import Neo4jDep
from app.ingest.wx_cli import (
    WX_EXPORT_MAX_MESSAGES,
    analyze_wx_cli_export_senders,
    ingest_wx_cli_export_json,
)
from app.wechat_cli.runner import export_chat_json, fetch_sessions_json

router = APIRouter(prefix="/api/v1/wechat", tags=["wechat"])


def _require_wx_cli_enabled() -> None:
    s = get_settings()
    if not s.wx_cli_enabled:
        raise HTTPException(
            status_code=503,
            detail="微信本机导入未启用：在 backend/.env 设置 WX_CLI_ENABLED=true，并确保本机已安装 wx-cli 且微信已登录。",
        )


@router.get("/status")
def wechat_status() -> dict[str, Any]:
    s = get_settings()
    raw = (s.wx_cli_command or "wx").strip()
    token = raw.split()[0] if raw else "wx"
    on_path = shutil.which(token) is not None
    return {
        "wx_cli_enabled": s.wx_cli_enabled,
        "wx_cli_command": s.wx_cli_command,
        "wx_cli_timeout_sec": s.wx_cli_timeout_sec,
        "executable_resolves": on_path,
    }


@router.get("/sessions")
def wechat_sessions(
    limit: int = Query(30, ge=1, le=200),
) -> dict[str, Any]:
    _require_wx_cli_enabled()
    s = get_settings()
    items = fetch_sessions_json(
        wx_command=s.wx_cli_command,
        limit=limit,
        timeout_sec=s.wx_cli_timeout_sec,
    )
    return {"sessions": items, "count": len(items)}


class PreviewExportBody(BaseModel):
    """拉取少量消息用于统计说话人（与正式导入的 -n 无关）。"""

    chat: str = Field(..., min_length=1, max_length=200)
    probe_limit: int = Field(500, ge=30, le=3000)

    @field_validator("chat", mode="before")
    @classmethod
    def strip_chat(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


@router.post("/preview-export")
def wechat_preview_export(body: PreviewExportBody) -> dict[str, Any]:
    _require_wx_cli_enabled()
    s = get_settings()
    lim = min(body.probe_limit, WX_EXPORT_MAX_MESSAGES)
    raw_text = export_chat_json(
        wx_command=s.wx_cli_command,
        chat=body.chat,
        limit=lim,
        timeout_sec=s.wx_cli_timeout_sec,
    )
    return analyze_wx_cli_export_senders(raw_text)


class AnalyzeJsonBody(BaseModel):
    raw_text: str = Field(..., min_length=3, max_length=30_000_000)
    probe_message_limit: int = Field(
        default=800,
        ge=50,
        le=8000,
        description="仅取前 N 条消息统计说话人（大文件探针）；正式导入仍用全文",
    )


@router.post("/analyze-json")
def wechat_analyze_json(body: AnalyzeJsonBody) -> dict[str, Any]:
    """解析 JSON 片段/全文，用前 ``probe_message_limit`` 条消息统计说话人（不写入库）。"""
    return analyze_wx_cli_export_senders(
        body.raw_text.strip(),
        probe_message_limit=body.probe_message_limit,
    )


@router.post("/analyze-json-file")
async def wechat_analyze_json_file(
    file: UploadFile = File(..., description="聊天 JSON 文件"),
    probe_message_limit: int = Form(800, ge=50, le=8000),
) -> dict[str, Any]:
    """上传 JSON 文件，仅在服务端读取；用前 N 条消息统计说话人，不把正文回传前端。"""
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
    result = analyze_wx_cli_export_senders(raw_text, probe_message_limit=probe_message_limit)
    result["probe_filename"] = file.filename
    result["probe_bytes"] = len(raw)
    return result


class WechatSessionImportBody(BaseModel):
    subject_id: str = Field(..., min_length=1, max_length=128)
    profiled_speaker_label: str = Field(..., min_length=1, max_length=128)
    wx_me_sender_label: str | None = Field(default=None, max_length=128)
    self_speaker_label: str | None = Field(default=None, max_length=128)
    subject_display_name: str | None = Field(default=None, max_length=256)
    chat: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(default=500, ge=1, le=WX_EXPORT_MAX_MESSAGES)
    note: str | None = Field(default=None, max_length=512)
    use_llm: bool = True

    @field_validator("subject_id", "profiled_speaker_label", "chat", mode="before")
    @classmethod
    def strip_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


@router.post("/import-from-session")
def wechat_import_from_session(
    neo4j: Neo4jDep,
    body: WechatSessionImportBody,
) -> dict[str, Any]:
    _require_wx_cli_enabled()
    s = get_settings()
    lim = min(body.limit, WX_EXPORT_MAX_MESSAGES)
    raw_text = export_chat_json(
        wx_command=s.wx_cli_command,
        chat=body.chat,
        limit=lim,
        timeout_sec=s.wx_cli_timeout_sec,
    )
    return ingest_wx_cli_export_json(
        neo4j,
        subject_id=body.subject_id,
        subject_display_name=body.subject_display_name,
        profiled_speaker_label=body.profiled_speaker_label,
        wx_me_sender_label=(body.wx_me_sender_label or "").strip(),
        self_speaker_label=(body.self_speaker_label or "").strip() or None,
        raw_text=raw_text,
        note=body.note,
        use_llm=body.use_llm,
    )
