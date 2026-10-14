from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AP_", env_file=".env", extra="ignore")

    env: str = "dev"
    http_port: int = 8900

    db_dsn: str = "sqlite+pysqlite:///:memory:"
    redis_url: str = "redis://localhost:6379/0"

    default_tenant: str = "changzhou"

    cloud_gateway_base_url: str = ""
    cloud_gateway_client_id: str = ""
    cloud_gateway_client_secret: str = ""
    cloud_gateway_llm_app_id: str = ""

    openai_base_url: str = ""
    openai_api_key: str = ""

    light_rag_base_url: str = ""
    light_rag_api_key: str = ""
    knowflow_base_url: str = ""
    knowledge_graph_base_url: str = ""

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    sm4_key: str = ""
    sm4_iv: str = ""

    # 工具服务注册表：{name: {"url": str, "kind": "http" | "mcp", "headers": {...}, "timeout": float}}
    tool_servers: dict[str, dict[str, Any]] = {}

    # 护栏（先上不启用：guard_enabled=False 时全部短路，双跑期与 Java 各持一份）
    guard_enabled: bool = False
    guard_sensitive_enabled: bool = False
    guard_quota_enabled: bool = False
    guard_rate_enabled: bool = False
    guard_round_enabled: bool = False
    guard_daily_token_quota: int = 0
    guard_rate_per_minute: int = 0
    guard_max_rounds: int = 0
    guard_default_reply: str = ""

    # 内置向量库
    embedding_dim: int = 256
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""

    # 兼容层鉴权：{client_id: client_secret}
    oauth_clients: dict[str, str] = {}
    jwt_secret: str = "agent-platform-dev-secret"

    # 记忆：窗口条数（0 关闭，历史以 history 变量注入图输入）
    history_window: int = 0
    # 记忆：窗口之外的历史压缩为 summary 变量注入（依赖 window 开启；调用模型失败时降级为仅窗口）
    history_summary_enabled: bool = False
    history_summary_provider: str = "cloud_gateway"
    history_summary_model: str = ""
    history_summary_max_chars: int = 4000

    # 幂等 / 并发
    idempotency_ttl_seconds: int = 600
    idempotency_derive_key: bool = False
    max_concurrency_per_app: int = 0
    concurrency_wait_seconds: float = 0.0

    # 中台账号体系（独立自建）：false 时 /admin 免鉴权，行为与改造前一致
    admin_auth_enabled: bool = False
    admin_seed_username: str = "admin"
    admin_seed_password: str = "admin123"
    admin_token_ttl_seconds: int = 7200


@lru_cache
def get_settings() -> Settings:
    return Settings()
