"""可插拔 LLM 客户端（默认 DeepSeek OpenAI 兼容 API）。"""

from app.llm.client import deepseek_configured, get_deepseek_client
from app.llm.persona_llm import maybe_enrich_persona_digest

__all__ = [
    "deepseek_configured",
    "get_deepseek_client",
    "maybe_enrich_persona_digest",
]
