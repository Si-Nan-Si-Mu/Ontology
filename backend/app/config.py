from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置；Neo4j 相关变量可由环境变量或 .env 覆盖。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    neo4j_uri: str = "bolt://127.0.0.1:7687"
    # Aura 控制台导出多为 NEO4J_USERNAME；本地常为 NEO4J_USER
    neo4j_user: str = Field(
        default="neo4j",
        validation_alias=AliasChoices("NEO4J_USER", "NEO4J_USERNAME"),
    )
    neo4j_password: str = "neo4j"
    neo4j_database: str | None = None

    # 本机 wx-cli：仅受信本地环境建议开启（子进程调用 `wx sessions` / `wx export`）
    wx_cli_enabled: bool = False
    wx_cli_command: str = "wx"
    wx_cli_timeout_sec: int = Field(default=120, ge=10, le=600)

    # DeepSeek（OpenAI 兼容）：https://api-docs.deepseek.com/zh-cn/
    deepseek_enabled: bool = False
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_sec: int = Field(default=120, ge=10, le=600)
    deepseek_thinking_enabled: bool = False

    @field_validator("deepseek_api_key", mode="before")
    @classmethod
    def empty_api_key_to_none(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return value.strip() or None
        return str(value).strip() or None

    @field_validator("neo4j_database", mode="before")
    @classmethod
    def empty_str_to_none(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return value
        return str(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
