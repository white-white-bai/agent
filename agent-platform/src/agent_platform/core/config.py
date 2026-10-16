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

    # OpenAI 兼容模型清单：{"<key>": {"label": str, "base_url": str, "api_key": str, "model": str}}
    # 任意 OpenAI 兼容端点（云端兼容网关 / DeepSeek / 私有部署等）都按此配置接入
    llm_models: dict[str, dict[str, Any]] = {}

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

    # 文件导入：图 DSL 单文件字节上限
    upload_max_bytes: int = 5 * 1024 * 1024
    # 知识库文档：单文件字节上限（默认 15MB）、分块字符数与重叠字符数
    document_max_bytes: int = 15 * 1024 * 1024
    document_chunk_chars: int = 800
    document_chunk_overlap: int = 0
    # 上传超过该字节数走异步入库（Redis 可用入 worker 队列，否则进程内后台任务）；0 = 全部异步
    knowledge_async_threshold_bytes: int = 1024 * 1024

    # 工具调用治理：参数校验 / 瞬时错误重试 / 失败兜底（兜底默认关）
    tool_validate: bool = True
    tool_retry_attempts: int = 2
    tool_retry_backoff_seconds: float = 0.5
    tool_fallback_enabled: bool = False

    # 智能体：ReAct 等模式的默认步数上限
    agent_max_steps: int = 6

    # 检索流水线
    # 粗召回（向量）候选数；0 表示用知识节点自己的 top_k
    retrieval_coarse_top_k: int = 0
    # 精召回：混合检索（向量 + 关键词，RRF 融合）；默认关闭，关闭时与只用向量逐字节一致
    retrieval_hybrid_enabled: bool = False
    retrieval_lexical_top_k: int = 10
    retrieval_rrf_k: int = 60
    # 重排序：默认关闭；开启后对候选调 {base_url}/rerank 取最终 top_k
    rerank_enabled: bool = False
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = ""
    rerank_top_k: int = 0

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
    # 摘要用哪个模型（llm_models 的 key）；留空则用清单里的第一个
    history_summary_provider: str = ""
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
