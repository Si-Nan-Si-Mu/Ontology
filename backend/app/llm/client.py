"""DeepSeek：OpenAI 兼容 Chat Completions（见 https://api-docs.deepseek.com/zh-cn/）。"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from openai import OpenAI

from app.config import Settings, get_settings

if TYPE_CHECKING:
    pass


def deepseek_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.deepseek_enabled and (s.deepseek_api_key or "").strip())


@lru_cache
def get_deepseek_client() -> OpenAI | None:
    settings = get_settings()
    if not deepseek_configured(settings):
        return None
    return OpenAI(
        api_key=settings.deepseek_api_key.strip(),
        base_url=settings.deepseek_base_url.rstrip("/"),
        timeout=float(settings.deepseek_timeout_sec),
        max_retries=1,
    )


def chat_json(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    timeout_sec: float | None = None,
) -> str:
    """调用 DeepSeek chat/completions，要求模型返回 JSON 字符串。"""
    settings = get_settings()
    client = get_deepseek_client()
    if client is None:
        raise RuntimeError("DeepSeek 未配置：请设置 DEEPSEEK_API_KEY 与 DEEPSEEK_ENABLED=true")

    kwargs: dict = {
        "model": model or settings.deepseek_model,
        "messages": messages,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    if settings.deepseek_thinking_enabled:
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("DeepSeek 返回空内容")
    return content.strip()


def chat_text(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
) -> str:
    """调用 DeepSeek chat/completions，返回纯文本（用于第一人称模拟等）。"""
    settings = get_settings()
    client = get_deepseek_client()
    if client is None:
        raise RuntimeError("DeepSeek 未配置：请设置 DEEPSEEK_API_KEY 与 DEEPSEEK_ENABLED=true")

    kwargs: dict = {
        "model": model or settings.deepseek_model,
        "messages": messages,
        "stream": False,
    }
    if settings.deepseek_thinking_enabled:
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("DeepSeek 返回空内容")
    return content.strip()
