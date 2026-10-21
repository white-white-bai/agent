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
    tool_audit_enabled: bool = False

    # 智能体：ReAct 等模式的默认步数上限
    agent_max_steps: int = 6
    # 智能体自主循环：单个工具结果回灌模型时的最大字符数
    agent_tool_result_max_chars: int = 4000

    # 代码节点沙箱：inprocess（默认，受限 exec，兼容旧行为）/ docker（隔离容器，推荐生产）
    code_sandbox_mode: str = "inprocess"
    code_sandbox_image: str = "python:3.11-slim"
    code_sandbox_timeout_seconds: float = 5.0
    code_sandbox_memory: str = "128m"
    code_sandbox_cpus: str = "0.5"
    code_sandbox_pids_limit: int = 64
    code_sandbox_max_output_bytes: int = 65536
    code_sandbox_allowed_images: str = ""

    # 不可信内容隔离：开启后对工具/知识/子 Agent 输出剥离指令注入并加边界标记
    prompt_guard_enabled: bool = False
    prompt_guard_max_chars: int = 12000

    # HITL 外部通知：中断时 POST Webhook；留空关闭
    hitl_webhook_url: str = ""
    hitl_webhook_secret: str = ""
    hitl_webhook_timeout_seconds: float = 3.0
    hitl_webhook_attempts: int = 2
    hitl_webhook_backoff_seconds: float = 0.2
    hitl_outbox_enabled: bool = False
    hitl_outbox_poll_seconds: float = 5.0
    hitl_outbox_max_attempts: int = 6
    hitl_outbox_backoff_seconds: float = 5.0
    hitl_callback_base_url: str = ""
    hitl_action_ttl_seconds: int = 86400

    # 浏览器操作（Playwright 可选依赖；AgentAppDef.browser=true 时才装配工具）
    browser_enabled: bool = False
    browser_headless: bool = True
    browser_timeout_ms: int = 15000
    browser_max_chars: int = 4000
    browser_allowed_hosts: str = ""
    browser_allow_private: bool = False
    browser_screenshot_dir: str = ".run/browser"
    browser_download_dir: str = ".run/downloads"
    browser_upload_dir: str = ""
    browser_storage_state: str = ""

    # MCP 工具运行时发现：默认关闭，关闭时只用 ap_tool 声明
    tool_discovery_enabled: bool = False
    tool_discovery_ttl_seconds: int = 300
    tool_discovery_max_tools: int = 50

    # 模型调用：0 表示沿用 endpoint 默认超时；重试次数与 ChatOpenAI 默认一致
    llm_timeout_seconds: float = 0.0
    llm_max_retries: int = 2

    # checkpointer / 人在环（默认关闭）
    checkpointer_enabled: bool = False
    hitl_enabled: bool = False
    # 等待审批的运行超过该秒数后标记 expired；0 = 不自动过期
    hitl_run_timeout_seconds: int = 0

    # 动态子图（默认关闭）
    subgraph_enabled: bool = False
    subgraph_max_depth: int = 2

    # 用户级长期记忆（默认关闭；关闭时不查不写、不注入图输入）
    user_memory_enabled: bool = False
    user_memory_write_enabled: bool = False
    user_memory_recall_enabled: bool = False
    user_memory_extract_async: bool = True
    user_memory_provider: str = ""
    user_memory_max_chars: int = 4000
    user_memory_top_k: int = 5
    user_memory_score_threshold: float | None = None
    user_memory_mode: str = "vector"
    user_memory_scope: str = "app"
    user_memory_max_per_user: int = 200
    user_memory_ttl_days: int = 0
    user_memory_dedup_threshold: float = 0.92
    user_memory_inject_var: str = "user_memory_text"

    # Agent 应用（自主 agent，原生 function-calling）：总闸默认关，关闭时 app_type=agent 仍走工作流路径
    agent_app_enabled: bool = False
    agent_app_max_steps: int = 6
    # 子 agent 委派递归深度上限
    agent_app_depth: int = 2
    agent_app_tool_timeout: float = 30.0

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
